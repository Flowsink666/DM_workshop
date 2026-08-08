from dm_workshop.state import normalize_campaign


def test_normalize_campaign_fills_fields_in_legacy_snapshot():
    legacy = {
        "id": "campaign-1",
        "name": "旧战役",
        "party_wallet_cp": 1550,
        "actors": {
            "pc-1": {
                "id": "pc-1", "kind": "pc", "hp": 0, "ac": 12,
                "wallet_cp": 250,
            },
        },
        "items": {"item-1": {"id": "item-1", "price_cp": 50}},
        "shops": {"shop-1": {"id": "shop-1", "wallet_cp": 5000}},
    }

    normalized = normalize_campaign(legacy)

    assert normalized is legacy
    assert normalized["schema_version"] == 3
    assert normalized["party_wallet_gp"] == 1550
    assert normalized["actors"]["pc-1"]["wallet_gp"] == 250
    assert normalized["items"]["item-1"]["price_gp"] == 50
    assert normalized["shops"]["shop-1"]["wallet_gp"] == 5000
    assert "party_wallet_cp" not in normalized
    assert "wallet_cp" not in normalized["actors"]["pc-1"]
    assert "price_cp" not in normalized["items"]["item-1"]
    assert "wallet_cp" not in normalized["shops"]["shop-1"]
    assert normalized["actors"]["pc-1"]["class_levels"] == {}
    assert normalized["actors"]["pc-1"]["spell_repertoire"] == {}
    assert set(normalized["shops"]) == {"shop-1"}
    assert normalized["encounters"] == {}
    assert normalized["actors"]["pc-1"]["base_ac"] == 12
    assert normalized["actors"]["pc-1"]["life_state"] == "unconscious"
    assert normalized["actors"]["pc-1"]["death_saves"] == {
        "successes": 0,
        "failures": 0,
    }


def test_normalize_campaign_prefers_existing_gp_values():
    state = {
        "id": "campaign-1", "name": "混合字段",
        "party_wallet_gp": 10, "party_wallet_cp": 100,
        "actors": {
            "pc-1": {
                "id": "pc-1", "kind": "pc", "hp": 1, "ac": 10,
                "wallet_gp": 20, "wallet_cp": 200,
            },
        },
        "items": {
            "item-1": {"id": "item-1", "price_gp": 30, "price_cp": 300},
        },
        "shops": {
            "shop-1": {"id": "shop-1", "wallet_gp": 40, "wallet_cp": 400},
        },
    }

    normalized = normalize_campaign(state)

    assert normalized["party_wallet_gp"] == 10
    assert normalized["actors"]["pc-1"]["wallet_gp"] == 20
    assert normalized["items"]["item-1"]["price_gp"] == 30
    assert normalized["shops"]["shop-1"]["wallet_gp"] == 40
