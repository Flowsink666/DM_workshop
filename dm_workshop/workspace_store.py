"""内存草稿、命名存档与 SQLite 持久化。"""

from __future__ import annotations

import json
import sqlite3
import threading
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from dm_workshop.errors import ConflictError, NotFoundError, RuleError
from dm_workshop.state import new_campaign, new_id, normalize_campaign, now_iso

STORE_VERSION = 1


@dataclass
class _Workspace:
    state: dict
    persisted_revision: int | None
    active_save_id: str | None
    created_at: str
    updated_at: str
    dirty: bool = False
    draft_version: int = 0
    is_new: bool = False


class CampaignStore:
    """在内存中维护草稿，仅在显式保存时写入 SQLite。"""

    def __init__(self, path: str | Path = "data/dm_workshop.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._workspaces: dict[str, _Workspace] = {}
        self.migration_backup: Path | None = None
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _initialize(self) -> None:
        legacy = False
        if self.path.exists() and self.path.stat().st_size:
            with sqlite3.connect(self.path) as conn:
                tables = {
                    row[0] for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                legacy = "campaigns" in tables and "save_slots" not in tables
        if legacy:
            self.migration_backup = self._backup_legacy_database()

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS campaigns (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    active_save_id TEXT
                )
            """)
            columns = {
                row[1] for row in conn.execute('PRAGMA table_info("campaigns")')
            }
            if "active_save_id" not in columns:
                conn.execute("ALTER TABLE campaigns ADD COLUMN active_save_id TEXT")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS save_slots (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(id)
                        ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    note TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(campaign_id, name)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS save_slots_campaign_idx "
                "ON save_slots(campaign_id, updated_at DESC)"
            )
            if legacy:
                self._migrate_legacy_rows(conn)
            conn.execute(f"PRAGMA user_version = {STORE_VERSION}")

        if legacy:
            try:
                with sqlite3.connect(self.path) as conn:
                    conn.execute("VACUUM")
            except sqlite3.Error:
                pass

    def _backup_legacy_database(self) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = self.path.with_name(
            f"{self.path.stem}.pre-manual-save-{timestamp}.bak"
        )
        with sqlite3.connect(self.path) as source:
            with sqlite3.connect(backup) as target:
                source.backup(target)
        return backup

    @staticmethod
    def _migrate_legacy_rows(conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT id, revision, state_json, created_at, updated_at "
            "FROM campaigns"
        ).fetchall()
        for row in rows:
            save_id = new_id()
            conn.execute(
                "INSERT INTO save_slots "
                "(id, campaign_id, name, note, state_json, revision, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    save_id, row["id"], "升级前基线",
                    "由手动存档迁移自动创建", row["state_json"],
                    int(row["revision"]), row["created_at"], row["updated_at"],
                ),
            )
            conn.execute(
                "UPDATE campaigns SET active_save_id=? WHERE id=?",
                (save_id, row["id"]),
            )
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='operations'"
        ).fetchone():
            conn.execute("DROP TABLE operations")

    def create_campaign(self, name: str) -> dict:
        state = new_campaign(name.strip())
        if not state["name"]:
            raise ValueError("战役名称不能为空")
        stamp = now_iso()
        with self._lock:
            workspace = _Workspace(
                state=state,
                persisted_revision=None,
                active_save_id=None,
                created_at=stamp,
                updated_at=stamp,
                dirty=True,
                draft_version=1,
                is_new=True,
            )
            self._workspaces[state["id"]] = workspace
            return self._state_with_workspace(workspace)

    def list_campaigns(self) -> list[dict]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT id, name, revision, created_at, updated_at, "
                    "active_save_id FROM campaigns ORDER BY updated_at DESC"
                ).fetchall()
            result = {
                row["id"]: {
                    "id": row["id"], "name": row["name"],
                    "revision": int(row["revision"]),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "active_save_id": row["active_save_id"],
                    "dirty": False, "draft_version": 0, "saved": True,
                }
                for row in rows
            }
            for campaign_id, workspace in self._workspaces.items():
                result[campaign_id] = self._campaign_row(workspace)
            return sorted(
                result.values(), key=lambda item: item["updated_at"], reverse=True
            )

    def get(self, campaign_id: str) -> dict:
        with self._lock:
            return self._state_with_workspace(self._workspace(campaign_id))

    def workspace_status(self, campaign_id: str) -> dict:
        with self._lock:
            return self._workspace_metadata(self._workspace(campaign_id))

    def mutate(self, campaign_id: str, kind: str, request: dict,
               mutation: Callable[[dict], dict | None], *,
               source: str = "system") -> dict:
        """在草稿副本上执行规则；失败时不改变工作区。"""
        del kind, request, source
        with self._lock:
            workspace = self._workspace(campaign_id)
            after = deepcopy(workspace.state)
            result = mutation(after) or {}
            workspace.state = after
            workspace.dirty = True
            workspace.draft_version += 1
            workspace.updated_at = now_iso()
            return {
                "dirty": True,
                "draft_version": workspace.draft_version,
                "revision": workspace.persisted_revision or 0,
                "result": result,
            }

    def save_campaign(self, campaign_id: str, slot_name: str | None = None, *,
                      note: str = "", overwrite: bool = False) -> dict:
        note = str(note or "").strip()
        if len(note) > 500:
            raise RuleError("存档备注不能超过 500 个字符")
        explicit_name = slot_name is not None
        normalized_name = str(slot_name or "").strip()
        if explicit_name and not 1 <= len(normalized_name) <= 64:
            raise RuleError("存档名称必须为 1 到 64 个字符")

        with self._lock:
            workspace = self._workspace(campaign_id)
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                campaign = conn.execute(
                    "SELECT revision FROM campaigns WHERE id=?", (campaign_id,)
                ).fetchone()
                if workspace.is_new:
                    if campaign is not None:
                        raise ConflictError("同一战役 ID 已被其他进程保存")
                    current_revision = 0
                else:
                    if campaign is None:
                        raise ConflictError("已保存战役被其他进程删除")
                    current_revision = int(campaign["revision"])
                    if current_revision != workspace.persisted_revision:
                        raise ConflictError("战役已被其他进程保存，请先放弃草稿并重新读取")

                existing = None
                if explicit_name:
                    existing = conn.execute(
                        "SELECT * FROM save_slots WHERE campaign_id=? AND name=?",
                        (campaign_id, normalized_name),
                    ).fetchone()
                    if existing is not None and not overwrite:
                        raise ConflictError("同名存档已存在；确认覆盖时请设置 overwrite=true")
                else:
                    if workspace.active_save_id is None:
                        raise RuleError("首次保存必须提供存档名称")
                    existing = conn.execute(
                        "SELECT * FROM save_slots WHERE id=? AND campaign_id=?",
                        (workspace.active_save_id, campaign_id),
                    ).fetchone()
                    if existing is None:
                        raise NotFoundError("当前活动存档不存在，请提供新的存档名称")
                    normalized_name = existing["name"]

                stamp = now_iso()
                revision = current_revision + 1
                saved_state = deepcopy(workspace.state)
                saved_state.pop("workspace", None)
                saved_state["revision"] = revision
                save_id = existing["id"] if existing is not None else new_id()
                created_at = existing["created_at"] if existing is not None else stamp
                effective_note = note if explicit_name or note else (
                    existing["note"] if existing is not None else ""
                )

                if workspace.is_new:
                    conn.execute(
                        "INSERT INTO campaigns "
                        "(id, name, revision, state_json, created_at, updated_at, "
                        "active_save_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            campaign_id, saved_state["name"], revision,
                            self._dump(saved_state), workspace.created_at,
                            stamp, save_id,
                        ),
                    )
                else:
                    cursor = conn.execute(
                        "UPDATE campaigns SET name=?, revision=?, state_json=?, "
                        "updated_at=?, active_save_id=? WHERE id=? AND revision=?",
                        (
                            saved_state["name"], revision,
                            self._dump(saved_state), stamp, save_id,
                            campaign_id, current_revision,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise ConflictError("战役已被其他进程保存")

                if existing is None:
                    conn.execute(
                        "INSERT INTO save_slots "
                        "(id, campaign_id, name, note, state_json, revision, "
                        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            save_id, campaign_id, normalized_name,
                            effective_note, self._dump(saved_state), revision,
                            created_at, stamp,
                        ),
                    )
                else:
                    conn.execute(
                        "UPDATE save_slots SET note=?, state_json=?, revision=?, "
                        "updated_at=? WHERE id=?",
                        (
                            effective_note, self._dump(saved_state), revision,
                            stamp, save_id,
                        ),
                    )

            workspace.state = saved_state
            workspace.persisted_revision = revision
            workspace.active_save_id = save_id
            workspace.updated_at = stamp
            workspace.dirty = False
            workspace.draft_version = 0
            workspace.is_new = False
            return {
                "dirty": False,
                "result": {
                    "campaign_id": campaign_id, "save_id": save_id,
                    "slot_name": normalized_name, "revision": revision,
                    "saved_at": stamp,
                },
            }

    def discard_campaign_changes(self, campaign_id: str) -> dict:
        with self._lock:
            workspace = self._workspace(campaign_id)
            discarded = workspace.draft_version
            if workspace.is_new:
                del self._workspaces[campaign_id]
                return {
                    "dirty": False,
                    "result": {
                        "campaign_id": campaign_id,
                        "discarded_changes": discarded,
                        "campaign_removed": True,
                    },
                }
            self._workspaces[campaign_id] = self._load_persisted(campaign_id)
            return {
                "dirty": False,
                "result": {
                    "campaign_id": campaign_id,
                    "discarded_changes": discarded,
                    "campaign_removed": False,
                },
            }

    def list_save_slots(self, campaign_id: str, *, limit: int = 10,
                        offset: int = 0) -> dict:
        limit, offset = int(limit), int(offset)
        if not 1 <= limit <= 50 or offset < 0:
            raise RuleError("limit 必须为 1..50，offset 不能为负")
        with self._lock:
            workspace = self._workspace(campaign_id)
            if workspace.is_new:
                return {"total": 0, "offset": offset, "limit": limit, "items": []}
            with self._connect() as conn:
                total = int(conn.execute(
                    "SELECT COUNT(*) FROM save_slots WHERE campaign_id=?",
                    (campaign_id,),
                ).fetchone()[0])
                rows = conn.execute(
                    "SELECT id, name, note, revision, created_at, updated_at "
                    "FROM save_slots WHERE campaign_id=? "
                    "ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                    (campaign_id, limit, offset),
                ).fetchall()
            return {
                "total": total, "offset": offset, "limit": limit,
                "items": [
                    {**dict(row), "active": row["id"] == workspace.active_save_id}
                    for row in rows
                ],
            }

    def load_save_slot(self, campaign_id: str, save_id: str) -> dict:
        with self._lock:
            workspace = self._workspace(campaign_id)
            if workspace.dirty:
                raise ConflictError("存在未保存草稿，请先保存或放弃后再加载存档")
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                campaign = conn.execute(
                    "SELECT revision FROM campaigns WHERE id=?", (campaign_id,)
                ).fetchone()
                slot = conn.execute(
                    "SELECT * FROM save_slots WHERE id=? AND campaign_id=?",
                    (save_id, campaign_id),
                ).fetchone()
                if campaign is None or slot is None:
                    raise NotFoundError("找不到战役或存档")
                current_revision = int(campaign["revision"])
                if current_revision != workspace.persisted_revision:
                    raise ConflictError("战役已被其他进程保存，请重新读取")
                revision = current_revision + 1
                state = normalize_campaign(json.loads(slot["state_json"]))
                state["revision"] = revision
                stamp = now_iso()
                cursor = conn.execute(
                    "UPDATE campaigns SET name=?, revision=?, state_json=?, "
                    "updated_at=?, active_save_id=? WHERE id=? AND revision=?",
                    (
                        state["name"], revision, self._dump(state), stamp,
                        save_id, campaign_id, current_revision,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ConflictError("战役已被其他进程保存")

            workspace.state = state
            workspace.persisted_revision = revision
            workspace.active_save_id = save_id
            workspace.updated_at = stamp
            workspace.dirty = False
            workspace.draft_version = 0
            return {
                "dirty": False,
                "result": {
                    "campaign_id": campaign_id, "save_id": save_id,
                    "slot_name": slot["name"], "revision": revision,
                    "loaded_at": stamp,
                },
            }

    def _workspace(self, campaign_id: str) -> _Workspace:
        workspace = self._workspaces.get(campaign_id)
        if workspace is None:
            workspace = self._load_persisted(campaign_id)
            self._workspaces[campaign_id] = workspace
        return workspace

    def _load_persisted(self, campaign_id: str) -> _Workspace:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT revision, state_json, active_save_id, created_at, "
                "updated_at FROM campaigns WHERE id=?", (campaign_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError(f"找不到战役: {campaign_id}")
        state = normalize_campaign(json.loads(row["state_json"]))
        state["revision"] = int(row["revision"])
        return _Workspace(
            state=state,
            persisted_revision=int(row["revision"]),
            active_save_id=row["active_save_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _workspace_metadata(workspace: _Workspace) -> dict:
        return {
            "dirty": workspace.dirty,
            "draft_version": workspace.draft_version,
            "saved_revision": workspace.persisted_revision or 0,
            "active_save_id": workspace.active_save_id,
            "saved": not workspace.is_new,
        }

    def _state_with_workspace(self, workspace: _Workspace) -> dict:
        state = deepcopy(workspace.state)
        state["workspace"] = self._workspace_metadata(workspace)
        return state

    def _campaign_row(self, workspace: _Workspace) -> dict:
        return {
            "id": workspace.state["id"], "name": workspace.state["name"],
            "revision": workspace.persisted_revision or 0,
            "created_at": workspace.created_at,
            "updated_at": workspace.updated_at,
            "active_save_id": workspace.active_save_id,
            "dirty": workspace.dirty,
            "draft_version": workspace.draft_version,
            "saved": not workspace.is_new,
        }

    @staticmethod
    def _dump(value: dict) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                          sort_keys=True)
