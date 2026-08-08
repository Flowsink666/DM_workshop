import json
import sqlite3
from pathlib import Path

import pytest

from dm_workshop.errors import ConflictError, RuleError
from dm_workshop.service import WorkshopService
from dm_workshop.state import new_campaign, now_iso
from dm_workshop.store import CampaignStore


def test_drafts_are_in_memory_until_saved(tmp_path: Path):
    path = tmp_path / "manual.db"
    store = CampaignStore(path)
    service = WorkshopService(store)
    campaign = service.create_campaign("草稿战役")
    campaign_id = campaign["id"]
    service.create_actor(campaign_id, "未保存角色")

    assert CampaignStore(path).list_campaigns() == []
    with pytest.raises(RuleError, match="首次保存"):
        store.save_campaign(campaign_id)

    saved = store.save_campaign(campaign_id, "主存档")
    assert saved["dirty"] is False
    reopened = CampaignStore(path).get(campaign_id)
    assert reopened["name"] == "草稿战役"
    assert len(reopened["actors"]) == 1


def test_discard_and_named_slot_rules(tmp_path: Path):
    store = CampaignStore(tmp_path / "slots.db")
    service = WorkshopService(store)
    campaign_id = service.create_campaign("存档战役")["id"]
    baseline = store.save_campaign(campaign_id, "基线")
    service.create_actor(campaign_id, "A")

    with pytest.raises(ConflictError, match="未保存草稿"):
        store.load_save_slot(campaign_id, baseline["result"]["save_id"])
    store.discard_campaign_changes(campaign_id)
    store.load_save_slot(campaign_id, baseline["result"]["save_id"])
    assert store.get(campaign_id)["workspace"]["dirty"] is False

    with pytest.raises(ConflictError, match="同名存档"):
        store.save_campaign(campaign_id, "基线")
    store.save_campaign(campaign_id, "基线", overwrite=True)
    page = store.list_save_slots(campaign_id)
    assert page["total"] == 1
    assert page["items"][0]["active"] is True


def test_cross_instance_save_conflict(tmp_path: Path):
    path = tmp_path / "conflict.db"
    first_store = CampaignStore(path)
    first = WorkshopService(first_store)
    campaign_id = first.create_campaign("冲突战役")["id"]
    first_store.save_campaign(campaign_id, "主存档")

    second_store = CampaignStore(path)
    second = WorkshopService(second_store)
    second.get_campaign(campaign_id)
    first.create_actor(campaign_id, "A")
    second.create_actor(campaign_id, "B")
    first_store.save_campaign(campaign_id)
    with pytest.raises(ConflictError, match="其他进程"):
        second_store.save_campaign(campaign_id)


def test_discard_removes_unsaved_new_campaign(tmp_path: Path):
    store = CampaignStore(tmp_path / "new.db")
    campaign_id = WorkshopService(store).create_campaign("临时战役")["id"]
    result = store.discard_campaign_changes(campaign_id)
    assert result["result"]["campaign_removed"] is True
    assert store.list_campaigns() == []


def test_legacy_database_is_backed_up_and_compacted(tmp_path: Path):
    path = tmp_path / "legacy.db"
    state = new_campaign("旧战役")
    stamp = now_iso()
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE campaigns (
                id TEXT PRIMARY KEY, name TEXT NOT NULL,
                revision INTEGER NOT NULL, state_json TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE operations (
                id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL,
                kind TEXT NOT NULL, source TEXT NOT NULL,
                request_json TEXT NOT NULL, before_json TEXT NOT NULL,
                after_json TEXT NOT NULL, before_revision INTEGER NOT NULL,
                after_revision INTEGER NOT NULL, created_at TEXT NOT NULL,
                undone_by TEXT
            );
        """)
        payload = json.dumps(state, ensure_ascii=False)
        conn.execute(
            "INSERT INTO campaigns VALUES (?, ?, 3, ?, ?, ?)",
            (state["id"], state["name"], payload, stamp, stamp),
        )
        conn.execute(
            "INSERT INTO operations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("op", state["id"], "test", "mcp", "{}", payload, payload,
             2, 3, stamp, None),
        )

    store = CampaignStore(path)
    assert store.migration_backup is not None
    assert store.migration_backup.exists()
    slots = store.list_save_slots(state["id"])
    assert slots["items"][0]["name"] == "升级前基线"
    with sqlite3.connect(path) as conn:
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "operations" not in tables
    assert "save_slots" in tables


def test_failed_legacy_backup_does_not_migrate(tmp_path: Path, monkeypatch):
    path = tmp_path / "failed.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE campaigns (id TEXT PRIMARY KEY, name TEXT, "
            "revision INTEGER, state_json TEXT, created_at TEXT, updated_at TEXT)"
        )
        conn.execute("CREATE TABLE operations (id TEXT PRIMARY KEY)")

    def fail_backup(_self):
        raise OSError("backup failed")

    monkeypatch.setattr(CampaignStore, "_backup_legacy_database", fail_backup)
    with pytest.raises(OSError, match="backup failed"):
        CampaignStore(path)
    with sqlite3.connect(path) as conn:
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "operations" in tables
    assert "save_slots" not in tables


def test_cp_fields_migrate_when_current_state_and_save_slot_are_loaded(
        tmp_path: Path):
    path = tmp_path / "currency-migration.db"
    store = CampaignStore(path)
    service = WorkshopService(store)
    campaign_id = service.create_campaign("旧货币战役")["id"]
    actor_id = service.create_actor(campaign_id, "角色")["result"]["actor"]["id"]
    service.update_actor(campaign_id, actor_id, {"wallet_gp": 321})
    item_id = service.define_item(
        campaign_id, "旧物品", price_gp=45,
    )["result"]["item"]["id"]
    shop_id = service.create_shop(
        campaign_id, "旧商店", wallet_gp=678,
    )["result"]["shop"]["id"]
    saved = store.save_campaign(campaign_id, "旧格式存档")
    save_id = saved["result"]["save_id"]

    def downgrade(payload: str) -> str:
        state = json.loads(payload)
        state["schema_version"] = 2
        state["party_wallet_cp"] = state.pop("party_wallet_gp")
        for actor in state["actors"].values():
            actor["wallet_cp"] = actor.pop("wallet_gp")
        for item in state["items"].values():
            item["price_cp"] = item.pop("price_gp")
        for shop in state["shops"].values():
            shop["wallet_cp"] = shop.pop("wallet_gp")
        return json.dumps(state, ensure_ascii=False)

    with sqlite3.connect(path) as conn:
        campaign_json = conn.execute(
            "SELECT state_json FROM campaigns WHERE id=?", (campaign_id,),
        ).fetchone()[0]
        slot_json = conn.execute(
            "SELECT state_json FROM save_slots WHERE id=?", (save_id,),
        ).fetchone()[0]
        conn.execute(
            "UPDATE campaigns SET state_json=? WHERE id=?",
            (downgrade(campaign_json), campaign_id),
        )
        conn.execute(
            "UPDATE save_slots SET state_json=? WHERE id=?",
            (downgrade(slot_json), save_id),
        )

    reopened = CampaignStore(path)
    current = reopened.get(campaign_id)
    assert current["schema_version"] == 3
    assert current["actors"][actor_id]["wallet_gp"] == 321
    assert current["items"][item_id]["price_gp"] == 45
    assert current["shops"][shop_id]["wallet_gp"] == 678

    reopened.load_save_slot(campaign_id, save_id)
    loaded = reopened.get(campaign_id)
    assert loaded["schema_version"] == 3
    assert loaded["actors"][actor_id]["wallet_gp"] == 321
    assert "wallet_cp" not in loaded["actors"][actor_id]
