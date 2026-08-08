import asyncio
import json
from pathlib import Path

import dm_workshop.mcp_server as mcp_server
from dm_workshop.service import WorkshopService
from dm_workshop.store import CampaignStore


def serialized_size(value: dict) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def test_mcp_writes_remain_compact_as_actor_state_grows(
        tmp_path: Path, monkeypatch):
    service = WorkshopService(CampaignStore(tmp_path / "compact.db"))
    monkeypatch.setattr(mcp_server, "get_service", lambda: service)
    created = mcp_server.create_campaign(
        "紧凑战役", [{"preset_id": "wizard", "name": "法师"}]
    )
    campaign_id = created["result"]["entity_id"]
    actor_id = next(iter(service.get_campaign(campaign_id)["actors"]))
    service.set_actor_classes(
        campaign_id, actor_id, {"wizard": 20}, override_reason="compact test"
    )

    for index in range(30):
        spell = service.define_spell(
            campaign_id, f"测试法术 {index}", 1, "utility"
        )["result"]["spell"]
        service.learn_spell(
            campaign_id, actor_id, spell["id"], source_class="wizard"
        )
    final_spell = service.define_spell(
        campaign_id, "最后法术", 1, "utility", description="很长的正文" * 100
    )["result"]["spell"]
    learned = asyncio.run(mcp_server.call_capability(
        "magic", "learn_spell", {
            "campaign_id": campaign_id,
            "actor_id": actor_id,
            "spell_id": final_spell["id"],
            "source_class": "wizard",
        },
    ))

    item = service.define_item(
        campaign_id, "测试物品", stackable=False
    )["result"]["item"]
    for _ in range(30):
        service.add_item(campaign_id, actor_id, item["id"])
    added = asyncio.run(mcp_server.call_capability(
        "inventory", "add_item", {
            "campaign_id": campaign_id,
            "owner_id": actor_id,
            "item_id": item["id"],
        },
    ))

    assert serialized_size(created) < 1024
    assert serialized_size(learned) < 1024
    assert serialized_size(added) < 1024
    assert "spell_repertoire" not in json.dumps(learned)
    assert "inventory" not in json.dumps(added)


def test_mcp_reads_are_partitioned_paginated_and_text_is_optional(
        tmp_path: Path, monkeypatch):
    service = WorkshopService(CampaignStore(tmp_path / "reads.db"))
    monkeypatch.setattr(mcp_server, "get_service", lambda: service)
    campaign_id = service.create_campaign("查询战役")["id"]
    actor_id = service.create_actor(
        campaign_id, "角色"
    )["result"]["actor"]["id"]
    spell = service.define_spell(
        campaign_id, "正文法术", 0, "utility", description="仅按需读取"
    )["result"]["spell"]

    summary = asyncio.run(mcp_server.call_capability(
        "campaign", "get_campaign_summary", {"campaign_id": campaign_id}
    ))
    actor = mcp_server.get_campaign_state(
        campaign_id, "actor", actor_id
    )
    items = asyncio.run(mcp_server.call_capability(
        "inventory", "search_items", {
            "campaign_id": campaign_id,
            "limit": 3,
        },
    ))
    metadata = mcp_server.get_spell_details(campaign_id, spell["id"])
    details = mcp_server.get_spell_details(
        campaign_id, spell["id"], include_text=True
    )

    assert "actors" not in summary
    assert "inventory" not in actor
    assert "spells" not in actor
    assert len(items["items"]) == 3
    assert items["limit"] == 3
    assert "description" not in metadata
    assert details["description"] == "仅按需读取"


def test_mcp_combat_event_stays_below_two_kilobytes(
        tmp_path: Path, monkeypatch):
    service = WorkshopService(CampaignStore(tmp_path / "combat.db"))
    monkeypatch.setattr(mcp_server, "get_service", lambda: service)
    campaign_id = service.create_campaign("战斗回执")['id']
    first_id = service.create_actor(
        campaign_id, "先攻者", max_hp=20, ac=12
    )["result"]["actor"]["id"]
    second_id = service.create_actor(
        campaign_id, "目标", max_hp=20, ac=12
    )["result"]["actor"]["id"]
    encounter_id = service.create_encounter(
        campaign_id, "预算测试", {"party": [first_id], "enemy": [second_id]}
    )["result"]["encounter"]["id"]
    service.start_encounter(campaign_id, encounter_id)
    encounter = service.get_campaign(campaign_id)["encounters"][encounter_id]
    actor_id = encounter["turn_order"][encounter["current_index"]]
    target_id = second_id if actor_id == first_id else first_id

    receipt = mcp_server.combat_attack(
        campaign_id, encounter_id, actor_id, target_id,
        to_hit=5, damage="1d8+3", damage_type="slashing",
    )

    assert serialized_size(receipt) < 2048
    assert receipt["result"]["changed"]["event"] == "attack"
    assert "encounter" not in receipt["result"]["changed"]
