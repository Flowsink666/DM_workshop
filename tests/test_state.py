from dm_workshop.state import CURRENCY_ITEM_ID, normalize_campaign


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
    assert normalized["schema_version"] == 4
    assert "party_wallet_gp" not in normalized
    assert "wallet_gp" not in normalized["actors"]["pc-1"]
    assert normalized["items"]["item-1"]["price_gp"] == 50
    assert "shops" not in normalized
    assert "party_wallet_cp" not in normalized
    assert "wallet_cp" not in normalized["actors"]["pc-1"]
    assert "price_cp" not in normalized["items"]["item-1"]
    assert normalized["actors"]["pc-1"]["class_levels"] == {}
    assert normalized["actors"]["pc-1"]["spell_repertoire"] == {}
    assert normalized["encounters"] == {}
    assert normalized["actors"]["pc-1"]["base_ac"] == 12
    assert normalized["actors"]["pc-1"]["life_state"] == "unconscious"
    assert normalized["actors"]["pc-1"]["death_saves"] == {
        "successes": 0,
        "failures": 0,
    }
    currency = normalized["items"][CURRENCY_ITEM_ID]
    assert currency["kind"] == "currency"
    assert currency["weight_lb"] == 0.02
    stacks = [s for s in normalized["party_inventory"].values()
              if s["item_id"] == CURRENCY_ITEM_ID]
    assert [s["quantity"] for s in stacks] == [1800]


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

    assert "party_wallet_gp" not in normalized
    assert "wallet_gp" not in normalized["actors"]["pc-1"]
    assert normalized["items"]["item-1"]["price_gp"] == 30
    assert "shops" not in normalized
    stacks = [s for s in normalized["party_inventory"].values()
              if s["item_id"] == CURRENCY_ITEM_ID]
    assert [s["quantity"] for s in stacks] == [30]


def test_currency_migration_is_idempotent_and_merges_existing_stacks():
    state = {
        "id": "campaign-1", "name": "mixed",
        "party_wallet_gp": 10,
        "actors": {"pc-1": {
            "id": "pc-1", "kind": "pc", "hp": 1, "ac": 10,
            "wallet_gp": 20,
        }},
        "items": {},
        "party_inventory": {
            "a": {"id": "a", "item_id": CURRENCY_ITEM_ID, "quantity": 3},
            "b": {"id": "b", "item_id": CURRENCY_ITEM_ID, "quantity": 4},
        },
    }
    normalize_campaign(state)
    normalize_campaign(state)
    stacks = [s for s in state["party_inventory"].values()
              if s["item_id"] == CURRENCY_ITEM_ID]
    assert len(stacks) == 1
    assert stacks[0]["quantity"] == 37
