from dm_workshop.state import normalize_campaign


def test_normalize_campaign_fills_fields_in_legacy_snapshot():
    legacy = {
        "id": "campaign-1",
        "name": "旧战役",
        "actors": {
            "pc-1": {"id": "pc-1", "kind": "pc", "hp": 0, "ac": 12},
        },
    }

    normalized = normalize_campaign(legacy)

    assert normalized is legacy
    assert normalized["schema_version"] == 2
    assert normalized["actors"]["pc-1"]["class_levels"] == {}
    assert normalized["actors"]["pc-1"]["spell_repertoire"] == {}
    assert normalized["shops"] == {}
    assert normalized["encounters"] == {}
    assert normalized["actors"]["pc-1"]["base_ac"] == 12
    assert normalized["actors"]["pc-1"]["life_state"] == "unconscious"
    assert normalized["actors"]["pc-1"]["death_saves"] == {
        "successes": 0,
        "failures": 0,
    }
