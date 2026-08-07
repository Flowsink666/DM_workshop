import inspect

from dm_workshop.mcp_server import learn_spell, mcp


def test_expected_mcp_tools_are_registered():
    names = set(mcp._tool_manager._tools)
    assert len(names) == 42
    assert {
        "get_campaign_state", "create_actor", "add_item", "buy_item",
        "combat_attack", "combat_cast", "combat_death_save", "undo_operation",
        "get_spell_catalog_status", "search_spell_catalog",
        "get_spell_details", "set_actor_classes", "get_actor_spellcasting",
        "prepare_spell", "cast_spell",
    } <= names


def test_learn_spell_preserves_legacy_remove_parameter_position():
    parameters = list(inspect.signature(learn_spell).parameters)
    assert parameters[:4] == [
        "campaign_id", "actor_id", "spell_id", "remove",
    ]
