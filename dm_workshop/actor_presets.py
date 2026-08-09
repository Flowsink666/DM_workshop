"""Deterministic level-one 2014 SRD class presets."""

from copy import deepcopy

CLASS_NAMES = {
    "barbarian": "野蛮人", "bard": "吟游诗人", "cleric": "牧师",
    "druid": "德鲁伊", "fighter": "战士", "monk": "武僧",
    "paladin": "圣武士", "ranger": "游侠", "rogue": "游荡者",
    "sorcerer": "术士", "warlock": "邪术师", "wizard": "法师",
}

_BASE = {
    "barbarian": ((15, 13, 14, 8, 12, 10), 12, ("STR", "CON"), ("Athletics", "Survival"),
                   [("greataxe", 1), ("handaxe", 2), ("javelin", 4), ("explorer-pack", 1)]),
    "bard": ((8, 14, 13, 10, 12, 15), 8, ("DEX", "CHA"), ("Acrobatics", "Performance", "Persuasion"),
             [("rapier", 1), ("dagger", 1), ("leather-armor", 1), ("lute", 1), ("diplomat-pack", 1)]),
    "cleric": ((13, 12, 14, 8, 15, 10), 8, ("WIS", "CHA"), ("Insight", "Religion"),
               [("mace", 1), ("scale-mail", 1), ("shield", 1), ("light-crossbow", 1), ("bolt", 20), ("priest-pack", 1), ("holy-symbol", 1)]),
    "druid": ((8, 14, 13, 12, 15, 10), 8, ("INT", "WIS"), ("Nature", "Perception"),
              [("scimitar", 1), ("leather-armor", 1), ("shield", 1), ("explorer-pack", 1), ("druidic-focus", 1)]),
    "fighter": ((15, 13, 14, 8, 12, 10), 10, ("STR", "CON"), ("Athletics", "Intimidation"),
                 [("longsword", 1), ("chain-mail", 1), ("shield", 1), ("light-crossbow", 1), ("bolt", 20), ("dungeoneer-pack", 1)]),
    "monk": ((12, 15, 13, 8, 14, 10), 8, ("STR", "DEX"), ("Acrobatics", "Stealth"),
             [("shortsword", 1), ("dungeoneer-pack", 1)]),
    "paladin": ((15, 10, 13, 8, 12, 14), 10, ("WIS", "CHA"), ("Athletics", "Persuasion"),
                [("longsword", 1), ("chain-mail", 1), ("shield", 1), ("javelin", 5), ("priest-pack", 1)]),
    "ranger": ((12, 15, 13, 10, 14, 8), 10, ("STR", "DEX"), ("Perception", "Survival"),
               [("shortsword", 2), ("scale-mail", 1), ("longbow", 1), ("arrow", 20), ("dungeoneer-pack", 1)]),
    "rogue": ((8, 15, 14, 13, 12, 10), 8, ("DEX", "INT"), ("Investigation", "Stealth"),
              [("rapier", 1), ("shortbow", 1), ("arrow", 20), ("leather-armor", 1), ("dagger", 2), ("burglar-pack", 1), ("thieves-tools", 1)]),
    "sorcerer": ((8, 14, 13, 10, 12, 15), 6, ("CON", "CHA"), ("Arcana", "Deception"),
                 [("light-crossbow", 1), ("bolt", 20), ("component-pouch", 1), ("explorer-pack", 1)]),
    "warlock": ((8, 14, 13, 10, 12, 15), 8, ("WIS", "CHA"), ("Arcana", "Deception"),
                [("light-crossbow", 1), ("bolt", 20), ("leather-armor", 1), ("component-pouch", 1), ("scholar-pack", 1)]),
    "wizard": ((8, 14, 13, 15, 12, 10), 6, ("INT", "WIS"), ("Arcana", "Investigation"),
               [("quarterstaff", 1), ("component-pouch", 1), ("scholar-pack", 1), ("spellbook", 1)]),
}

SPELLS = {
    "bard": {"cantrips": ("vicious-mockery", "mage-hand"), "known": ("healing-word", "dissonant-whispers", "faerie-fire", "thunderwave")},
    "cleric": {"cantrips": ("guidance", "sacred-flame", "spare-the-dying"), "prepared": ("bless", "cure-wounds", "guiding-bolt")},
    "druid": {"cantrips": ("druidcraft", "produce-flame"), "prepared": ("cure-wounds", "entangle", "faerie-fire")},
    "sorcerer": {"cantrips": ("fire-bolt", "light", "mage-hand", "prestidigitation"), "known": ("magic-missile", "shield")},
    "warlock": {"cantrips": ("eldritch-blast", "mage-hand"), "known": ("armor-of-agathys", "hex")},
    "wizard": {"cantrips": ("fire-bolt", "mage-hand", "light"), "spellbook": ("detect-magic", "find-familiar", "mage-armor", "magic-missile", "shield", "sleep"), "prepared": ("mage-armor", "magic-missile", "shield")},
}

def _make(preset_id: str) -> dict:
    abilities, hit_die, saves, skills, equipment = _BASE[preset_id]
    return {"preset_id": preset_id, "class": preset_id, "class_name": CLASS_NAMES[preset_id],
            "name": "", "level": 1, "speed": 30,
            "abilities": dict(zip(("STR", "DEX", "CON", "INT", "WIS", "CHA"), abilities)),
            "hit_die": hit_die, "saving_throw_proficiencies": list(saves),
            "skill_proficiencies": list(skills), "equipment": list(equipment),
            "spells": deepcopy(SPELLS.get(preset_id, {}))}

ACTOR_PRESETS = {key: _make(key) for key in _BASE}

def list_presets() -> list[dict]:
    return [deepcopy(value) for value in ACTOR_PRESETS.values()]

def get_preset(preset_id: str) -> dict:
    try:
        return deepcopy(ACTOR_PRESETS[preset_id])
    except KeyError as exc:
        raise KeyError(preset_id) from exc
