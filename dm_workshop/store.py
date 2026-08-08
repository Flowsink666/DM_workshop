"""SQLite 持久化、原子审计记录和补偿式撤销。"""

from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from pathlib import Path
from typing import Callable

from dm_workshop.errors import ConflictError, NotFoundError
from dm_workshop.state import new_campaign, new_id, normalize_campaign, now_iso


class _LegacyCampaignStore:
    """保存版本化战役快照，并为每次写入记录前后状态。"""
    def __init__(self, path: str | Path = "data/dm_workshop.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS campaigns (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operations (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(id),
                    kind TEXT NOT NULL,
                    source TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    before_json TEXT NOT NULL,
                    after_json TEXT NOT NULL,
                    before_revision INTEGER NOT NULL,
                    after_revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    undone_by TEXT REFERENCES operations(id)
                );
                CREATE INDEX IF NOT EXISTS operations_campaign_idx
                    ON operations(campaign_id, created_at DESC);
            """)

    def create_campaign(self, name: str) -> dict:
        state = new_campaign(name.strip())
        if not state["name"]:
            raise ValueError("战役名称不能为空")
        stamp = now_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO campaigns VALUES (?, ?, 0, ?, ?, ?)",
                (state["id"], state["name"], self._dump(state), stamp, stamp),
            )
        return state

    def list_campaigns(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, revision, updated_at FROM campaigns "
                "ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, campaign_id: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError(f"找不到战役: {campaign_id}")
        # 读取时在内存中补齐旧字段；下一次写事务会自然持久化升级后的快照。
        return normalize_campaign(json.loads(row["state_json"]))

    def mutate(self, campaign_id: str, kind: str, request: dict,
               mutation: Callable[[dict], dict | None], *,
               source: str = "system") -> dict:
        """在一个立即事务中完成读取、规则变更、版本推进和审计写入。"""
        with self._connect() as conn:
            # IMMEDIATE 会提前取得写锁，避免两个 AI 调用基于同一修订同时提交。
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT revision, state_json FROM campaigns WHERE id = ?",
                (campaign_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"找不到战役: {campaign_id}")
            before = normalize_campaign(json.loads(row["state_json"]))
            after = deepcopy(before)
            result = mutation(after) or {}
            before_revision = int(row["revision"])
            after_revision = before_revision + 1
            after["revision"] = after_revision
            operation_id = new_id()
            stamp = now_iso()
            conn.execute(
                "UPDATE campaigns SET name=?, revision=?, state_json=?, "
                "updated_at=? WHERE id=? AND revision=?",
                (after["name"], after_revision, self._dump(after), stamp,
                 campaign_id, before_revision),
            )
            if conn.total_changes != 1:
                raise ConflictError("战役已被其他操作修改，请重新查询")
            conn.execute(
                "INSERT INTO operations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                (operation_id, campaign_id, kind, source,
                 self._dump(request), self._dump(before), self._dump(after),
                 before_revision, after_revision, stamp),
            )
        return {
            "operation_id": operation_id,
            "revision": after_revision,
            "result": result,
        }

    def undo(self, campaign_id: str, operation_id: str, *,
             source: str = "web") -> dict:
        """用新事务恢复目标操作前态；有后续修改时拒绝覆盖。"""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            campaign = conn.execute(
                "SELECT revision, state_json FROM campaigns WHERE id=?",
                (campaign_id,),
            ).fetchone()
            op = conn.execute(
                "SELECT * FROM operations WHERE id=? AND campaign_id=?",
                (operation_id, campaign_id),
            ).fetchone()
            if campaign is None or op is None:
                raise NotFoundError("找不到战役或操作记录")
            if op["undone_by"] is not None:
                raise ConflictError("该操作已经撤销")
            if int(campaign["revision"]) != int(op["after_revision"]):
                raise ConflictError("目标操作之后已有其他修改，不能自动撤销")
            before = json.loads(campaign["state_json"])
            after = normalize_campaign(json.loads(op["before_json"]))
            revision = int(campaign["revision"]) + 1
            after["revision"] = revision
            undo_id = new_id()
            stamp = now_iso()
            conn.execute(
                "UPDATE campaigns SET name=?, revision=?, state_json=?, updated_at=? WHERE id=?",
                (after["name"], revision, self._dump(after), stamp, campaign_id),
            )
            conn.execute(
                "INSERT INTO operations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                (undo_id, campaign_id, "undo", source,
                 self._dump({"operation_id": operation_id}), self._dump(before),
                 self._dump(after), revision - 1, revision, stamp),
            )
            conn.execute(
                "UPDATE operations SET undone_by=? WHERE id=?", (undo_id, operation_id)
            )
        return {"operation_id": undo_id, "revision": revision,
                "result": {"undone_operation_id": operation_id}}

    def list_operations(self, campaign_id: str, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM campaigns WHERE id=?", (campaign_id,)
            ).fetchone()
            if exists is None:
                raise NotFoundError(f"找不到战役: {campaign_id}")
            rows = conn.execute(
                "SELECT id, kind, source, request_json, before_revision, "
                "after_revision, created_at, undone_by FROM operations "
                "WHERE campaign_id=? ORDER BY rowid DESC LIMIT ?",
                (campaign_id, max(1, min(limit, 200))),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["request"] = json.loads(item.pop("request_json"))
            result.append(item)
        return result

    @staticmethod
    def _dump(value: dict) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                          sort_keys=True)


# 保留导入路径，实际实现使用手动保存的内存工作区。
from dm_workshop.workspace_store import CampaignStore as CampaignStore
