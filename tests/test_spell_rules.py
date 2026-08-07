from dm_workshop.spell_rules import (
    effective_caster_level, max_spell_level, multiclass_requirement_failures,
    mystic_arcanum, normalize_class_levels, pact_slots, shared_slots,
    spell_capacity,
)
from dm_workshop.state import new_actor


def test_class_aliases_and_multiclass_slots():
    levels = normalize_class_levels({"法师": 3, "paladin": 2, "邪术师": 1})
    assert levels == {"wizard": 3, "paladin": 2, "warlock": 1}
    assert effective_caster_level(levels) == 4
    assert shared_slots(levels) == {
        "1": {"max": 4, "used": 0}, "2": {"max": 3, "used": 0},
    }
    assert pact_slots(levels) == {"slot_level": 1, "max": 1, "used": 0}


def test_multiclass_prerequisites_cover_both_classes():
    actor = new_actor("多职角色", abilities={"INT": 13, "STR": 12, "CHA": 13})
    failures = multiclass_requirement_failures(
        actor, {"wizard": 1, "paladin": 1}
    )
    assert failures == ["圣武士需要STR 13"]


def test_warlock_pact_and_mystic_arcanum_progression():
    assert pact_slots({"warlock": 11}) == {
        "slot_level": 5, "max": 3, "used": 0,
    }
    assert max_spell_level("warlock", 11) == 6
    assert mystic_arcanum({"warlock": 17}) == {
        "6": {"spell_id": None, "used": False},
        "7": {"spell_id": None, "used": False},
        "8": {"spell_id": None, "used": False},
        "9": {"spell_id": None, "used": False},
    }


def test_known_and_prepared_capacities_use_source_class_ability():
    actor = new_actor("施法者", level=5, abilities={"INT": 16, "CHA": 14})
    actor["class_levels"] = {"wizard": 5}
    wizard = spell_capacity(actor, "wizard")
    assert wizard["cantrips"] == 4
    assert wizard["prepared"] == 8
    assert wizard["max_spell_level"] == 3
