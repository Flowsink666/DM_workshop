"""Deterministic 2014 SRD monster presets for quick combat encounters."""

from __future__ import annotations

from copy import deepcopy

MONSTER_PRESETS: dict[str, dict] = {
    "goblin": {
        "preset_id": "goblin",
        "name": "哥布林",
        "name_en": "Goblin",
        "kind": "monster",
        "cr": "1/4",
        "level": 1,
        "max_hp": 7,
        "ac": 15,
        "speed": 30,
        "abilities": {"STR": 8, "DEX": 14, "CON": 10, "INT": 10, "WIS": 8, "CHA": 8},
        "skill_proficiencies": ["stealth"],
        "saving_throw_proficiencies": [],
        "resistances": [],
        "vulnerabilities": [],
        "immunities": [],
        "equipment": [("scimitar", 1), ("shortbow", 1)],
    },
    "bandit": {
        "preset_id": "bandit",
        "name": "强盗",
        "name_en": "Bandit",
        "kind": "monster",
        "cr": "1/8",
        "level": 1,
        "max_hp": 11,
        "ac": 12,
        "speed": 30,
        "abilities": {"STR": 11, "DEX": 12, "CON": 12, "INT": 10, "WIS": 10, "CHA": 10},
        "skill_proficiencies": [],
        "saving_throw_proficiencies": [],
        "resistances": [],
        "vulnerabilities": [],
        "immunities": [],
        "equipment": [("scimitar", 1), ("light-crossbow", 1)],
    },
    "skeleton": {
        "preset_id": "skeleton",
        "name": "骷髅",
        "name_en": "Skeleton",
        "kind": "monster",
        "cr": "1/4",
        "level": 1,
        "max_hp": 13,
        "ac": 13,
        "speed": 30,
        "abilities": {"STR": 10, "DEX": 14, "CON": 15, "INT": 6, "WIS": 8, "CHA": 5},
        "skill_proficiencies": [],
        "saving_throw_proficiencies": [],
        "resistances": [],
        "vulnerabilities": ["bludgeoning"],
        "immunities": ["poison"],
        "equipment": [("shortsword", 1), ("shortbow", 1)],
    },
    "zombie": {
        "preset_id": "zombie",
        "name": "僵尸",
        "name_en": "Zombie",
        "kind": "monster",
        "cr": "1/4",
        "level": 1,
        "max_hp": 22,
        "ac": 8,
        "speed": 20,
        "abilities": {"STR": 13, "DEX": 6, "CON": 16, "INT": 3, "WIS": 6, "CHA": 5},
        "skill_proficiencies": [],
        "saving_throw_proficiencies": ["WIS"],
        "resistances": [],
        "vulnerabilities": [],
        "immunities": ["poison"],
        "equipment": [("club", 1)],
    },
    "orc": {
        "preset_id": "orc",
        "name": "兽人",
        "name_en": "Orc",
        "kind": "monster",
        "cr": "1/2",
        "level": 2,
        "max_hp": 15,
        "ac": 13,
        "speed": 30,
        "abilities": {"STR": 16, "DEX": 12, "CON": 16, "INT": 7, "WIS": 11, "CHA": 10},
        "skill_proficiencies": ["intimidation"],
        "saving_throw_proficiencies": [],
        "resistances": [],
        "vulnerabilities": [],
        "immunities": [],
        "equipment": [("greataxe", 1), ("javelin", 2)],
    },
    "wolf": {
        "preset_id": "wolf",
        "name": "野狼",
        "name_en": "Wolf",
        "kind": "monster",
        "cr": "1/4",
        "level": 1,
        "max_hp": 11,
        "ac": 13,
        "speed": 40,
        "abilities": {"STR": 12, "DEX": 15, "CON": 12, "INT": 3, "WIS": 12, "CHA": 6},
        "skill_proficiencies": ["perception", "stealth"],
        "saving_throw_proficiencies": [],
        "resistances": [],
        "vulnerabilities": [],
        "immunities": [],
        "equipment": [("dagger", 1)],  # 作为 bite 武器模拟
    },
}


def list_monster_presets() -> list[dict]:
    return [deepcopy(p) for p in MONSTER_PRESETS.values()]


def get_monster_preset(preset_id: str) -> dict:
    key = str(preset_id).strip().casefold()
    if key not in MONSTER_PRESETS:
        available = ", ".join(MONSTER_PRESETS)
        raise KeyError(f"未知怪物预设: {preset_id}；可用预设: {available}")
    return deepcopy(MONSTER_PRESETS[key])
