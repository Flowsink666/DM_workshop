"""D&D 5e 2014 职业等级、法术位和已知/准备规则表。"""

from __future__ import annotations

from copy import deepcopy

from dm_workshop.errors import RuleError

CLASS_NAMES_ZH = {
    "barbarian": "野蛮人", "bard": "吟游诗人", "cleric": "牧师",
    "druid": "德鲁伊", "fighter": "战士", "monk": "武僧",
    "paladin": "圣武士", "ranger": "游侠", "rogue": "游荡者",
    "sorcerer": "术士", "warlock": "邪术师", "wizard": "法师",
}
CLASS_ALIASES = {**{value: key for key, value in CLASS_NAMES_ZH.items()},
                 **{key: key for key in CLASS_NAMES_ZH}}
CASTING_ABILITIES = {
    "bard": "CHA", "cleric": "WIS", "druid": "WIS", "paladin": "CHA",
    "ranger": "WIS", "sorcerer": "CHA", "warlock": "CHA", "wizard": "INT",
}
FULL_CASTERS = {"bard", "cleric", "druid", "sorcerer", "wizard"}
HALF_CASTERS = {"paladin", "ranger"}
KNOWN_CASTERS = {"bard", "ranger", "sorcerer", "warlock"}
PREPARED_CASTERS = {"cleric", "druid", "paladin", "wizard"}
RITUAL_CASTERS = {"bard", "cleric", "druid", "wizard"}

MULTICLASS_REQUIREMENTS = {
    "barbarian": {"STR": 13}, "bard": {"CHA": 13},
    "cleric": {"WIS": 13}, "druid": {"WIS": 13},
    "fighter": {"STR_OR_DEX": 13}, "monk": {"DEX": 13, "WIS": 13},
    "paladin": {"STR": 13, "CHA": 13}, "ranger": {"DEX": 13, "WIS": 13},
    "rogue": {"DEX": 13}, "sorcerer": {"CHA": 13},
    "warlock": {"CHA": 13}, "wizard": {"INT": 13},
}

SHARED_SLOT_TABLE = {
    1: (2,), 2: (3,), 3: (4, 2), 4: (4, 3), 5: (4, 3, 2),
    6: (4, 3, 3), 7: (4, 3, 3, 1), 8: (4, 3, 3, 2),
    9: (4, 3, 3, 3, 1), 10: (4, 3, 3, 3, 2),
    11: (4, 3, 3, 3, 2, 1), 12: (4, 3, 3, 3, 2, 1),
    13: (4, 3, 3, 3, 2, 1, 1), 14: (4, 3, 3, 3, 2, 1, 1),
    15: (4, 3, 3, 3, 2, 1, 1, 1), 16: (4, 3, 3, 3, 2, 1, 1, 1),
    17: (4, 3, 3, 3, 2, 1, 1, 1, 1),
    18: (4, 3, 3, 3, 3, 1, 1, 1, 1),
    19: (4, 3, 3, 3, 3, 2, 1, 1, 1),
    20: (4, 3, 3, 3, 3, 2, 2, 1, 1),
}

KNOWN_SPELLS = {
    "bard": (4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 15, 16, 18, 19, 19, 20, 22, 22, 22),
    "ranger": (0, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11),
    "sorcerer": (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 12, 13, 13, 14, 14, 15, 15, 15, 15),
    "warlock": (2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 11, 11, 12, 12, 13, 13, 14, 14, 15, 15),
}
CANTRIPS_KNOWN = {
    "bard": (2, 2, 2, 3, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4),
    "cleric": (3, 3, 3, 4, 4, 4, 4, 4, 4, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5),
    "druid": (2, 2, 2, 3, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4),
    "sorcerer": (4, 4, 4, 5, 5, 5, 5, 5, 5, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6),
    "warlock": (2, 2, 2, 3, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4),
    "wizard": (3, 3, 3, 4, 4, 4, 4, 4, 4, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5),
}
WARLOCK_PACT = {
    1: (1, 1), 2: (1, 2), 3: (2, 2), 4: (2, 2), 5: (3, 2),
    6: (3, 2), 7: (4, 2), 8: (4, 2), 9: (5, 2), 10: (5, 2),
    **{level: (5, 3) for level in range(11, 17)},
    **{level: (5, 4) for level in range(17, 21)},
}
MYSTIC_ARCANUM_LEVELS = {6: 11, 7: 13, 8: 15, 9: 17}


def normalize_class_name(value: str) -> str:
    try:
        return CLASS_ALIASES[str(value).strip().casefold()]
    except KeyError as exc:
        raise RuleError(f"未知职业: {value}") from exc


def normalize_class_levels(values: dict[str, int]) -> dict[str, int]:
    result: dict[str, int] = {}
    for name, raw_level in values.items():
        class_id = normalize_class_name(name)
        level = int(raw_level)
        if not 1 <= level <= 20:
            raise RuleError(f"职业等级必须在 1 到 20 之间: {name}")
        result[class_id] = result.get(class_id, 0) + level
    total = sum(result.values())
    if not 1 <= total <= 20:
        raise RuleError("角色总等级必须在 1 到 20 之间")
    return result


def proficiency_bonus(total_level: int) -> int:
    return 2 + (max(1, int(total_level)) - 1) // 4


def multiclass_requirement_failures(actor: dict, class_levels: dict[str, int]) -> list[str]:
    if len(class_levels) <= 1:
        return []
    abilities = actor["abilities"]
    failures = []
    for class_id in class_levels:
        for ability, minimum in MULTICLASS_REQUIREMENTS[class_id].items():
            if ability == "STR_OR_DEX":
                if max(int(abilities["STR"]), int(abilities["DEX"])) < minimum:
                    failures.append(f"{CLASS_NAMES_ZH[class_id]}需要力量或敏捷 {minimum}")
            elif int(abilities[ability]) < minimum:
                failures.append(f"{CLASS_NAMES_ZH[class_id]}需要{ability} {minimum}")
    return failures


def effective_caster_level(class_levels: dict[str, int]) -> int:
    full = sum(class_levels.get(name, 0) for name in FULL_CASTERS)
    half = sum(class_levels.get(name, 0) // 2 for name in HALF_CASTERS)
    return min(20, full + half)


def _preserve_used(previous: dict, level: int, maximum: int) -> dict:
    old = previous.get(str(level), previous.get(level, {})) if previous else {}
    return {"max": maximum, "used": min(maximum, int(old.get("used", 0)))}


def shared_slots(class_levels: dict[str, int], previous: dict | None = None) -> dict:
    effective = effective_caster_level(class_levels)
    maximums = SHARED_SLOT_TABLE.get(effective, ())
    return {
        str(level): _preserve_used(previous or {}, level, maximum)
        for level, maximum in enumerate(maximums, start=1)
    }


def pact_slots(class_levels: dict[str, int], previous: dict | None = None) -> dict:
    warlock_level = class_levels.get("warlock", 0)
    if not warlock_level:
        return {"slot_level": 0, "max": 0, "used": 0}
    slot_level, maximum = WARLOCK_PACT[warlock_level]
    return {
        "slot_level": slot_level, "max": maximum,
        "used": min(maximum, int((previous or {}).get("used", 0))),
    }


def mystic_arcanum(class_levels: dict[str, int], previous: dict | None = None) -> dict:
    warlock_level = class_levels.get("warlock", 0)
    previous = previous or {}
    return {
        str(level): {"spell_id": previous.get(str(level), {}).get("spell_id"),
                     "used": bool(previous.get(str(level), {}).get("used", False))}
        for level, minimum in MYSTIC_ARCANUM_LEVELS.items()
        if warlock_level >= minimum
    }


def max_spell_level(class_id: str, class_level: int) -> int:
    """返回该职业自身能够学习或准备的最高法术环位。"""
    if class_id in FULL_CASTERS:
        return min(9, (int(class_level) + 1) // 2)
    if class_id in HALF_CASTERS:
        if class_level < 2:
            return 0
        return min(5, (int(class_level) + 3) // 4)
    if class_id == "warlock":
        if class_level >= 17:
            return 9
        if class_level >= 15:
            return 8
        if class_level >= 13:
            return 7
        if class_level >= 11:
            return 6
        return WARLOCK_PACT[int(class_level)][0]
    return 0


def spell_capacity(actor: dict, class_id: str) -> dict:
    class_level = int(actor.get("class_levels", {}).get(class_id, 0))
    if class_id not in CASTING_ABILITIES or class_level <= 0:
        return {"class": class_id, "class_level": class_level,
                "max_spell_level": 0, "cantrips": 0,
                "known": 0, "prepared": 0}
    ability = CASTING_ABILITIES[class_id]
    modifier = (int(actor["abilities"][ability]) - 10) // 2
    prepared = 0
    if class_id in {"cleric", "druid", "wizard"}:
        prepared = max(1, class_level + modifier)
    elif class_id == "paladin" and class_level >= 2:
        prepared = max(1, class_level // 2 + modifier)
    return {
        "class": class_id, "class_name": CLASS_NAMES_ZH[class_id],
        "class_level": class_level, "ability": ability,
        "max_spell_level": max_spell_level(class_id, class_level),
        "cantrips": CANTRIPS_KNOWN.get(class_id, (0,) * 20)[class_level - 1],
        "known": KNOWN_SPELLS.get(class_id, (0,) * 20)[class_level - 1],
        "prepared": prepared,
    }


def rebuild_spellcasting(actor: dict) -> None:
    """按职业等级重算资源上限，并保留不超过新上限的已使用次数。"""
    class_levels = actor.get("class_levels", {})
    actor["level"] = sum(class_levels.values())
    actor["proficiency_bonus"] = proficiency_bonus(actor["level"])
    actor["spell_slots"] = shared_slots(class_levels, actor.get("spell_slots"))
    actor["pact_slots"] = pact_slots(class_levels, actor.get("pact_slots"))
    actor["mystic_arcanum"] = mystic_arcanum(
        class_levels, actor.get("mystic_arcanum")
    )


def spellcasting_summary(actor: dict) -> dict:
    class_levels = deepcopy(actor.get("class_levels", {}))
    capacities = {
        class_id: spell_capacity(actor, class_id)
        for class_id in class_levels if class_id in CASTING_ABILITIES
    }
    return {
        "class_levels": class_levels,
        "effective_caster_level": effective_caster_level(class_levels),
        "shared_slots": deepcopy(actor.get("spell_slots", {})),
        "pact_slots": deepcopy(actor.get("pact_slots", {})),
        "mystic_arcanum": deepcopy(actor.get("mystic_arcanum", {})),
        "capacities": capacities,
        "repertoire": deepcopy(actor.get("spell_repertoire", {})),
    }
