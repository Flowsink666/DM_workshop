from pathlib import Path

import pytest

import dm_workshop.mcp_server as mcp_server
from dm_workshop.actor_presets import ACTOR_PRESETS
from dm_workshop.errors import RuleError
from dm_workshop.service import WorkshopService
from dm_workshop.state import new_actor, normalize_campaign
from dm_workshop.store import CampaignStore


def service_at(tmp_path: Path) -> WorkshopService:
    return WorkshopService(CampaignStore(tmp_path / "presets.db"))


def test_all_core_class_presets_are_stable_and_unnamed(tmp_path: Path):
    service = service_at(tmp_path)
    rows = service.list_actor_presets()
    assert len(rows) == len(ACTOR_PRESETS) == 12
    assert len({row["preset_id"] for row in rows}) == 12
    assert all(row["name"] == "" and row["hp"] > 0 and row["ac"] >= 10
               for row in rows)
    assert all(sorted(row["abilities"].values()) == [8, 10, 12, 13, 14, 15]
               for row in rows)


def test_campaign_initializes_duplicate_presets_with_distinct_ids(tmp_path: Path):
    service = service_at(tmp_path)
    campaign = service.create_campaign("双战士", preset_characters=[
        {"preset_id": "fighter", "name": "艾琳"},
        {"preset_id": "fighter", "name": "布兰"},
        {"preset_id": "wizard", "name": "罗尔"},
    ])
    actors = list(campaign["actors"].values())
    assert len(actors) == 3
    assert len({actor["id"] for actor in actors}) == 3
    fighters = [actor for actor in actors if actor["preset_id"] == "fighter"]
    assert {actor["name"] for actor in fighters} == {"艾琳", "布兰"}
    assert all(actor["class_levels"] == {"fighter": 1} for actor in fighters)
    assert all(actor["max_hp"] == 12 and actor["ac"] == 18 for actor in fighters)
    wizard = next(actor for actor in actors if actor["preset_id"] == "wizard")
    assert wizard["spell_slots"]["1"] == {"max": 2, "used": 0}
    spell_slugs = {campaign["spells"][spell_id]["slug"] for spell_id in wizard["spells"]}
    assert {"fire-bolt", "mage-hand", "light", "mage-armor", "magic-missile", "shield"} <= spell_slugs


@pytest.mark.parametrize("characters", [
    [],
    [{"preset_id": "unknown", "name": "A"}],
    [{"preset_id": "fighter", "name": "   "}],
])
def test_invalid_preset_selection_leaves_no_campaign(tmp_path: Path, characters):
    service = service_at(tmp_path)
    with pytest.raises(RuleError):
        service.create_campaign("无效", preset_characters=characters)
    assert service.list_campaigns() == []


def test_old_actor_normalizes_to_null_preset_id():
    state = {"actors": {"old": new_actor("旧角色")}, "items": {}, "spells": {},
             "party_inventory": {}, "shops": {}, "encounters": {}}
    state["actors"]["old"].pop("preset_id")
    assert normalize_campaign(state)["actors"]["old"]["preset_id"] is None


def test_mcp_registry_replaces_create_actor_with_presets():
    internal = mcp_server._implementation_mcp._tool_manager._tools
    assert "create_actor" not in internal
    assert "list_actor_presets" in internal
    actor_actions = {row["name"] for row in mcp_server.list_group_actions("actors")["actions"]}
    assert "list_actor_presets" in actor_actions
    assert "create_actor" not in actor_actions
