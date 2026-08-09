"""MCP 专用的紧凑状态投影，避免把完整领域对象放入模型上下文。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from dm_workshop.errors import NotFoundError, RuleError


def _page(values: list[dict], limit: int, offset: int) -> dict:
    limit, offset = int(limit), int(offset)
    if not 1 <= limit <= 50 or offset < 0:
        raise RuleError("limit 必须为 1..50，offset 不能为负")
    return {
        "total": len(values), "offset": offset, "limit": limit,
        "items": values[offset:offset + limit],
    }


def campaign_summary(service, campaign_id: str) -> dict:
    state = service.get_campaign(campaign_id)
    workspace = state.get("workspace", {})
    active = []
    for encounter in state["encounters"].values():
        if encounter.get("status") != "active":
            continue
        order = encounter.get("turn_order", [])
        index = int(encounter.get("current_index", 0))
        active.append({
            "id": encounter["id"], "name": encounter["name"],
            "round": encounter.get("round", 0),
            "current_actor_id": order[index] if order else None,
            "outcome": encounter.get("outcome"),
        })
    return {
        "id": state["id"], "name": state["name"],
        "ruleset": state.get("ruleset"),
        "revision": workspace.get("saved_revision", state.get("revision", 0)),
        "dirty": bool(workspace.get("dirty")),
        "draft_changes": int(workspace.get("draft_version", 0)),
        "active_save_id": workspace.get("active_save_id"),
        "counts": {
            "actors": len(state["actors"]), "items": len(state["items"]),
            "spells": len(state["spells"]),
            "encounters": len(state["encounters"]),
        },
        "active_encounters": active,
    }


def campaign_view(service, campaign_id: str, view: str = "actors", *,
                  entity_id: str | None = None, limit: int = 10,
                  offset: int = 0) -> dict:
    state = service.get_campaign(campaign_id)
    view = str(view or "actors").strip().casefold()
    if view == "actors":
        values = [_actor_summary(actor) for actor in state["actors"].values()]
        return _page(sorted(values, key=lambda item: item["name"]), limit, offset)
    if view == "actor":
        actor = _required(state["actors"], entity_id, "角色")
        return _actor_details(actor)
    if view == "inventory":
        inventory = (
            state["party_inventory"] if entity_id == "party"
            else _required(state["actors"], entity_id, "角色")["inventory"]
        )
        values = []
        for stack in inventory.values():
            item = state["items"].get(stack["item_id"], {})
            values.append({
                "stack_id": stack["id"], "item_id": stack["item_id"],
                "name": item.get("name", ""), "kind": item.get("kind", ""),
                "quantity": stack["quantity"],
                "equipped_slot": stack.get("equipped_slot"),
                "container_id": stack.get("container_id"),
            })
        return _page(sorted(values, key=lambda item: item["name"]), limit, offset)
    if view == "encounters":
        values = [_encounter_summary(value) for value in state["encounters"].values()]
        return _page(sorted(values, key=lambda item: item["name"]), limit, offset)
    if view == "encounter":
        encounter = _required(state["encounters"], entity_id, "遭遇")
        logs = list(reversed(encounter.get("log", [])))
        result = _encounter_summary(encounter)
        result.update({
            "sides": deepcopy(encounter.get("sides", {})),
            "turn_order": deepcopy(encounter.get("turn_order", [])),
            "initiatives": deepcopy(encounter.get("initiatives", {})),
            "current_index": encounter.get("current_index", 0),
            "budgets": deepcopy(encounter.get("budgets", {})),
            "log": {**_page(logs, limit, offset), "newest_first": True},
        })
        return result
    raise RuleError(
        "view 必须是 actors、actor、inventory、encounters 或 encounter"
    )


def search_items(service, campaign_id: str, query: str = "", *,
                 limit: int = 10, offset: int = 0) -> dict:
    values = [{
        "id": item["id"], "name": item["name"],
        "name_en": item.get("name_en", ""), "kind": item.get("kind", ""),
        "weight_lb": item.get("weight_lb", 0), "price_gp": item.get("price_gp", 0),
        "stackable": bool(item.get("stackable", False)),
    } for item in service.search_items(campaign_id, query)]
    return _page(values, limit, offset)


def search_spells(service, campaign_id: str, query: str = "", *,
                  limit: int = 10, offset: int = 0) -> dict:
    values = [_spell_summary(spell) for spell in service.search_spells(
        campaign_id, query
    )]
    return _page(values, limit, offset)


def compact_catalog_page(page: dict) -> dict:
    limit, offset = int(page["limit"]), int(page["offset"])
    if not 1 <= limit <= 50 or offset < 0:
        raise RuleError("limit 必须为 1..50，offset 不能为负")
    return {
        "total": page["total"], "offset": offset, "limit": limit,
        "items": [_spell_summary(item) for item in page["items"]],
    }


def spell_details(service, campaign_id: str, spell_id: str, *,
                  include_text: bool = False) -> dict:
    spell = deepcopy(service.get_spell_details(campaign_id, spell_id))
    if not include_text:
        spell.pop("description", None)
        spell.pop("higher_levels", None)
    spell.pop("source_row_id", None)
    return spell


def actor_spellcasting(service, campaign_id: str, actor_id: str, *,
                       include_repertoire: bool = False, limit: int = 10,
                       offset: int = 0) -> dict:
    summary = deepcopy(service.get_actor_spellcasting(campaign_id, actor_id))
    repertoire = summary.pop("repertoire", {})
    if not include_repertoire:
        return summary
    state = service.get_campaign(campaign_id)
    values = []
    for entry in repertoire.values():
        spell = state["spells"].get(entry.get("spell_id"), {})
        values.append({
            "spell_id": entry.get("spell_id"), "name": spell.get("name", ""),
            "spell_level": entry.get("spell_level", spell.get("level", 0)),
            "source_class": entry.get("source_class"),
            "mode": entry.get("mode"), "prepared": bool(entry.get("prepared")),
        })
    summary["repertoire"] = _page(
        sorted(values, key=lambda item: (item["spell_level"], item["name"])),
        limit, offset,
    )
    return summary


def mutation_receipt(tool_name: str, response: dict, arguments: dict) -> dict:
    """把服务层结果限制为当前变化；未知写工具也绝不透传完整实体。"""
    result = response.get("result", {})
    changed: dict[str, Any]
    entity_id = None

    if tool_name in {"create_actor", "update_actor"}:
        actor = result.get("actor", {})
        entity_id = actor.get("id", arguments.get("actor_id"))
        if tool_name == "create_actor":
            changed = {key: actor.get(key) for key in (
                "name", "kind", "level", "hp", "max_hp", "ac"
            )}
        else:
            changed = {}
            for key in arguments.get("changes", {}):
                changed[key] = actor.get(key)
            changed["life_state"] = actor.get("life_state")
    elif tool_name == "set_actor_classes":
        casting = result.get("spellcasting", {})
        entity_id = result.get("actor_id", arguments.get("actor_id"))
        changed = {
            "class_levels": casting.get("class_levels", {}),
            "effective_caster_level": casting.get("effective_caster_level", 0),
            "shared_slots": casting.get("shared_slots", {}),
            "pact_slots": casting.get("pact_slots", {}),
            "capacities": casting.get("capacities", {}),
            "warnings": result.get("warnings", []),
        }
    elif tool_name == "learn_spell":
        entity_id = result.get("actor_id", arguments.get("actor_id"))
        entry = next((value for value in result.get("spell_repertoire", {}).values()
                      if value.get("spell_id") == arguments.get("spell_id")
                      and (not arguments.get("source_class")
                           or value.get("source_class") == arguments.get("source_class"))), {})
        changed = {
            "spell_id": arguments.get("spell_id"),
            "source_class": entry.get("source_class", arguments.get("source_class")),
            "mode": entry.get("mode", "legacy" if result.get("legacy_mode") else None),
            "prepared": entry.get("prepared", arguments.get("prepared", False)),
            "removed": bool(arguments.get("remove")),
            "warnings": result.get("warnings", []),
        }
    elif tool_name == "prepare_spell":
        entity_id = result.get("actor_id", arguments.get("actor_id"))
        changed = {
            "spell_id": result.get("spell_id", arguments.get("spell_id")),
            "source_class": arguments.get("source_class"),
            "prepared": result.get("prepared", arguments.get("prepared", True)),
            "warnings": result.get("warnings", []),
        }
    elif tool_name in {"define_item", "define_spell"}:
        value = result.get("item") or result.get("spell") or {}
        entity_id = value.get("id")
        changed = {key: value.get(key) for key in ("name", "kind", "level")
                   if key in value}
    elif tool_name in {"add_item", "equip_item", "unequip_item"}:
        stack = result.get("stack", {})
        entity_id = stack.get("id")
        changed = {key: stack.get(key) for key in (
            "item_id", "quantity", "container_id", "equipped_slot"
        )}
        if "ac" in result:
            changed["ac"] = result["ac"]
    elif tool_name in {"create_encounter", "start_encounter"}:
        encounter = result.get("encounter", {})
        entity_id = encounter.get("id", arguments.get("encounter_id"))
        changed = {
            "name": encounter.get("name"), "status": encounter.get("status"),
            "round": encounter.get("round"),
            "current_actor_id": result.get("current_actor_id"),
            "turn_order": encounter.get("turn_order", []),
            "initiatives": encounter.get("initiatives", {}),
        }
    elif tool_name in {"combat_attack", "combat_cast", "combat_death_save",
                       "combat_end_turn", "cast_spell"}:
        entity_id = result.get("actor_id", arguments.get("actor_id"))
        changed = deepcopy(result)
    else:
        entity_id = (
            result.get("actor_id")
            or result.get("stack_id") or arguments.get("actor_id")
            or arguments.get("owner_id") or arguments.get("shop_id")
        )
        changed = deepcopy(result)
        for key in ("actor", "shop", "encounter", "spell_repertoire", "spells"):
            changed.pop(key, None)

    return {
        "dirty": bool(response.get("dirty", True)),
        "result": {"entity_id": entity_id, "changed": changed},
    }


def _required(values: dict, entity_id: str | None, label: str) -> dict:
    if not entity_id or entity_id not in values:
        raise NotFoundError(f"找不到{label}: {entity_id}")
    return values[entity_id]


def _actor_summary(actor: dict) -> dict:
    return {key: deepcopy(actor.get(key)) for key in (
        "id", "name", "kind", "level", "class_levels", "hp", "max_hp",
        "temp_hp", "ac", "life_state",
    )}


def _actor_details(actor: dict) -> dict:
    return {key: deepcopy(actor.get(key)) for key in (
        "id", "name", "aliases", "kind", "level", "xp", "class_levels",
        "abilities", "proficiency_bonus", "skill_proficiencies",
        "saving_throw_proficiencies", "hp", "max_hp", "temp_hp", "ac",
        "speed", "resistances", "vulnerabilities", "immunities",
        "conditions", "life_state", "death_saves", "resources",
    )}


def _encounter_summary(encounter: dict) -> dict:
    order = encounter.get("turn_order", [])
    index = int(encounter.get("current_index", 0))
    return {
        "id": encounter["id"], "name": encounter["name"],
        "status": encounter.get("status"), "round": encounter.get("round", 0),
        "outcome": encounter.get("outcome"),
        "participant_count": sum(len(value) for value in encounter.get("sides", {}).values()),
        "current_actor_id": order[index] if order else None,
    }


def _spell_summary(spell: dict) -> dict:
    manual = spell.get("manual_resolution_required")
    if manual is None:
        manual = not bool(spell.get("automatic_resolution", False))
    return {
        "id": spell["id"], "name": spell["name"],
        "level": int(spell.get("level", 0)), "school": spell.get("school", ""),
        "ritual": bool(spell.get("ritual", False)),
        "classes": deepcopy(spell.get("classes", [])),
        "manual_resolution_required": bool(manual),
    }
