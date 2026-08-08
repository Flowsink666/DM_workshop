"""MCP capability groups exposed by the compact routing surface."""

from __future__ import annotations

from typing import Any

from dm_workshop.errors import RuleError


CAPABILITY_GROUPS: dict[str, dict[str, Any]] = {
    "campaign": {
        "name": "战役与存档",
        "description": "创建战役、读取摘要和分区状态，以及保存、加载和管理存档槽。",
        "actions": (
            "list_campaigns", "create_campaign", "get_campaign_summary",
            "get_campaign_state", "save_campaign", "discard_campaign_changes",
            "list_save_slots", "load_save_slot",
        ),
    },
    "actors": {
        "name": "角色状态",
        "description": "管理角色卡、生命值、状态效果和休息。",
        "actions": (
            "list_actor_presets", "update_actor", "apply_damage", "heal",
            "set_condition", "rest",
        ),
    },
    "inventory": {
        "name": "物品与背包",
        "description": "搜索和定义物品，管理角色或共享仓库中的物品栈与装备栏。",
        "actions": (
            "search_items", "define_item", "add_item", "remove_item",
            "transfer_item", "equip_item", "unequip_item",
        ),
    },
    "magic": {
        "name": "法术与施法",
        "description": "搜索法术目录、管理职业施法能力，并学习、准备、定义和施放法术。",
        "actions": (
            "search_spells", "get_spell_catalog_status",
            "search_spell_catalog", "get_spell_details", "set_actor_classes",
            "get_actor_spellcasting", "learn_spell", "prepare_spell",
            "define_spell", "cast_spell",
        ),
    },
    "commerce": {
        "name": "商店交易",
        "description": "创建商店、设置库存，以及执行购买和出售。",
        "actions": ("create_shop", "stock_shop", "buy_item", "sell_item"),
    },
    "encounter": {
        "name": "遭遇与战斗",
        "description": "建立和推进遭遇，执行攻击、战斗施法、死亡豁免和回合结束。",
        "actions": (
            "create_encounter", "start_encounter", "combat_attack",
            "combat_death_save", "combat_cast", "combat_end_turn",
        ),
    },
    "dice": {
        "name": "骰子",
        "description": "执行可审计的骰子表达式投掷。",
        "actions": ("roll_dice",),
    },
}


MUTATING_ACTIONS = frozenset({
    "create_campaign", "update_actor", "set_actor_classes",
    "learn_spell", "prepare_spell", "define_spell", "define_item",
    "add_item", "remove_item", "transfer_item", "equip_item", "unequip_item",
    "create_shop", "stock_shop", "buy_item", "sell_item",
    "create_encounter", "start_encounter", "combat_attack",
    "combat_death_save", "combat_cast", "cast_spell", "combat_end_turn",
    "apply_damage", "heal", "set_condition", "rest", "save_campaign",
    "discard_campaign_changes", "load_save_slot",
})


def validate_registry(tool_names: set[str]) -> None:
    """Fail fast if a registered implementation is missing from a group."""
    grouped = [
        action
        for group in CAPABILITY_GROUPS.values()
        for action in group["actions"]
    ]
    grouped_set = set(grouped)
    if len(grouped) != len(grouped_set):
        raise RuntimeError("MCP capability groups contain duplicate actions")
    missing = grouped_set - tool_names
    ungrouped = tool_names - grouped_set
    if missing or ungrouped:
        raise RuntimeError(
            "MCP capability groups do not match the internal tool registry: "
            f"missing={sorted(missing)}, ungrouped={sorted(ungrouped)}"
        )


def get_group(group: str) -> dict[str, Any]:
    try:
        return CAPABILITY_GROUPS[group]
    except KeyError as exc:
        available = ", ".join(CAPABILITY_GROUPS)
        raise RuleError(
            f"未知 MCP 功能大类: {group}；可用大类: {available}"
        ) from exc


def actions_for_group(group: str, tool_registry: Any) -> list[dict[str, Any]]:
    definition = get_group(group)
    return [
        {
            "name": action,
            "description": tool_registry[action].description,
            "mutating": action in MUTATING_ACTIONS,
        }
        for action in definition["actions"]
    ]


def resolve_action(group: str, action: str, tool_registry: Any) -> Any:
    definition = get_group(group)
    if action not in definition["actions"]:
        allowed = ", ".join(definition["actions"])
        raise RuleError(
            f"动作 {action} 不属于 MCP 功能大类 {group}；可用动作: {allowed}"
        )
    return tool_registry[action]
