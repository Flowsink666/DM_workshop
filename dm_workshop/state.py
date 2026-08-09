"""战役状态工厂、稳定 ID 与基础规则计算辅助函数。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from dm_workshop.errors import RuleError

ABILITIES = ("STR", "DEX", "CON", "INT", "WIS", "CHA")
CONDITIONS = {
    "blinded", "charmed", "deafened", "frightened", "grappled",
    "incapacitated", "invisible", "paralyzed", "petrified", "poisoned",
    "prone", "restrained", "stunned", "unconscious", "concentrating",
}
EQUIPMENT_SLOTS = {
    "main_hand", "off_hand", "armor", "shield", "head", "neck",
    "hands", "feet", "ring_1", "ring_2", "back",
}

SCHEMA_VERSION = 4
CURRENCY_ITEM_ID = "currency-gp"
CURRENCY_ITEM_SLUG = "gold-piece"
CURRENCY_ITEM = {
    "id": CURRENCY_ITEM_ID,
    "slug": CURRENCY_ITEM_SLUG,
    "name": "金币",
    "name_en": "Gold Piece",
    "aliases": ["GP", "gp", "gold piece", "gold pieces"],
    "kind": "currency",
    "weight_lb": 0.02,
    "price_gp": 0,
    "stackable": True,
    "source": "system",
}


def new_id() -> str:
    return str(uuid4())


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_campaign(name: str) -> dict:
    """创建空战役快照；revision 仅在显式保存或加载存档时推进。"""
    campaign_id = new_id()
    return {
        "schema_version": SCHEMA_VERSION,
        "id": campaign_id,
        "name": name,
        "ruleset": "dnd5e-2014-srd-5.1",
        "revision": 0,
        "created_at": now_iso(),
        "actors": {},
        "items": {CURRENCY_ITEM_ID: dict(CURRENCY_ITEM)},
        "spells": {},
        "party_inventory": {},
        "encounters": {},
    }


def normalize_campaign(state: dict) -> dict:
    """补齐旧快照缺失字段，使新增代码可以安全读取早期本地数据库。"""
    state["schema_version"] = max(SCHEMA_VERSION, int(state.get("schema_version", 1)))
    state.setdefault("actors", {})
    state.setdefault("items", {})
    state.setdefault("spells", {})
    state.setdefault("party_inventory", {})
    state.setdefault("encounters", {})
    for item in state["items"].values():
        _migrate_gp_field(item, "price_gp", "price_cp")
    for spell in state["spells"].values():
        spell.setdefault("name_en", "")
        spell.setdefault("aliases", [])
        spell.setdefault("school", "")
        spell.setdefault("ritual", False)
        spell.setdefault("classes", [])
        spell.setdefault("casting_time", "")
        spell.setdefault("range", "")
        spell.setdefault("components", "")
        spell.setdefault("duration", "")
        spell.setdefault("concentration", False)
        spell.setdefault("higher_levels", "")
        automatic = spell.get("kind") in {"attack", "save", "damage", "heal"}
        spell.setdefault("manual_resolution_required", not automatic)
        spell.setdefault("resolution", {
            "mode": "automatic" if automatic else "manual",
            "kind": spell.get("kind", "utility"),
            "damage": spell.get("damage"),
            "damage_type": spell.get("damage_type"),
            "heal": spell.get("heal"),
            "save_ability": spell.get("save_ability"),
            "save_result": spell.get("save_result"),
            "slot_scaling": spell.get("slot_scaling"),
            "confidence": "curated" if automatic else "manual",
            "reasons": [] if automatic else ["需要 DM 裁定"],
        })
    for actor in state.get("actors", {}).values():
        actor.setdefault("preset_id", None)
        actor.setdefault("base_ac", actor.get("ac", 10))
        actor.setdefault("resistances", [])
        actor.setdefault("vulnerabilities", [])
        actor.setdefault("immunities", [])
        actor.setdefault("spellcasting_ability", "INT")
        actor.setdefault("spells", [])
        actor.setdefault("spell_slots", {})
        # 空 class_levels 表示旧版手工施法模式，不猜测历史角色职业。
        actor.setdefault("class_levels", {})
        actor.setdefault("spell_repertoire", {})
        actor.setdefault("pact_slots", {"slot_level": 0, "max": 0, "used": 0})
        actor.setdefault("mystic_arcanum", {})
        actor.setdefault("resources", {})
        actor.setdefault("conditions", {})
        actor.setdefault("life_state", "conscious" if actor.get("hp", 0) > 0
                         else ("unconscious" if actor.get("kind") == "pc" else "dead"))
        actor.setdefault("death_saves", {"successes": 0, "failures": 0})
    for encounter in state["encounters"].values():
        encounter.setdefault("outcome", None)
        encounter.setdefault("budgets", {})
        encounter.setdefault("log", [])
    _migrate_legacy_currency(state)
    state.pop("shops", None)
    return state


def _migrate_gp_field(container: dict, gp_key: str, cp_key: str) -> None:
    """将旧 CP 字段原值迁移为整数 GP；新字段存在时保持其权威性。"""
    container[gp_key] = int(container.get(gp_key, container.get(cp_key, 0)))
    container.pop(cp_key, None)


def _migrate_legacy_currency(state: dict) -> None:
    """Move legacy wallet balances into one idempotent party inventory stack."""
    currency = _ensure_currency_item(state)
    party_inventory = state["party_inventory"]
    total = int(state.pop("party_wallet_gp", state.pop("party_wallet_cp", 0)) or 0)
    for actor in state.get("actors", {}).values():
        total += int(actor.pop("wallet_gp", actor.pop("wallet_cp", 0)) or 0)
        for stack_id, stack in list(actor.get("inventory", {}).items()):
            if stack.get("item_id") == currency["id"]:
                total += int(stack.get("quantity", 0))
                del actor["inventory"][stack_id]
    if total < 0:
        raise RuleError("璐у竵涓嶈兘涓鸿礋")

    currency_stacks = [
        (stack_id, stack) for stack_id, stack in party_inventory.items()
        if stack.get("item_id") == currency["id"]
    ]
    if currency_stacks:
        _, target = currency_stacks[0]
        quantity = int(target.get("quantity", 0))
        if quantity < 0:
            raise RuleError("金币数量不能为负")
        for duplicate_id, duplicate in currency_stacks[1:]:
            duplicate_quantity = int(duplicate.get("quantity", 0))
            if duplicate_quantity < 0:
                raise RuleError("金币数量不能为负")
            quantity += duplicate_quantity
            party_inventory.pop(duplicate_id, None)
        target["quantity"] = quantity + total
    elif total:
        stack_id = new_id()
        party_inventory[stack_id] = {
            "id": stack_id, "item_id": currency["id"], "quantity": total,
            "container_id": None, "equipped_slot": None, "notes": "",
        }


def _ensure_currency_item(state: dict) -> dict:
    items = state["items"]
    by_id = items.get(CURRENCY_ITEM_ID)
    by_slug = next(
        (item for item in items.values()
         if item.get("slug") == CURRENCY_ITEM_SLUG),
        None,
    )
    if (by_id is not None and by_id != CURRENCY_ITEM) or (
            by_slug is not None and by_slug != CURRENCY_ITEM):
        raise RuleError("系统金币物品标识冲突")
    if by_id is None:
        items[CURRENCY_ITEM_ID] = dict(CURRENCY_ITEM)
    return items[CURRENCY_ITEM_ID]


def new_actor(name: str, *, kind: str = "pc", level: int = 1,
              max_hp: int = 10, ac: int = 10,
              abilities: dict[str, int] | None = None) -> dict:
    """创建具备完整默认字段的角色，避免后续流程猜测缺失字段。"""
    actor_id = new_id()
    stats = {key: 10 for key in ABILITIES}
    if abilities:
        stats.update({str(k).upper(): int(v) for k, v in abilities.items()})
    return {
        "id": actor_id,
        "preset_id": None,
        "name": name,
        "aliases": [],
        "kind": kind,
        "level": level,
        "xp": 0,
        "abilities": stats,
        "proficiency_bonus": 2,
        "skill_proficiencies": [],
        "saving_throw_proficiencies": [],
        "max_hp": max_hp,
        "hp": max_hp,
        "temp_hp": 0,
        "ac": ac,
        "base_ac": ac,
        "speed": 30,
        "resistances": [],
        "vulnerabilities": [],
        "immunities": [],
        "conditions": {},
        "life_state": "conscious",
        "death_saves": {"successes": 0, "failures": 0},
        "spell_slots": {},
        "spellcasting_ability": "INT",
        "spells": [],
        "class_levels": {},
        "spell_repertoire": {},
        "pact_slots": {"slot_level": 0, "max": 0, "used": 0},
        "mystic_arcanum": {},
        "resources": {},
        "inventory": {},
    }


def ability_mod(actor: dict, ability: str) -> int:
    return (int(actor["abilities"][ability.upper()]) - 10) // 2


def carrying_capacity_lb(actor: dict) -> float:
    return int(actor["abilities"]["STR"]) * 15.0
