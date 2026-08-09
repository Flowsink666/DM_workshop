from pathlib import Path

import pytest

from dm_workshop.errors import ConflictError, RuleError
from dm_workshop.service import WorkshopService
from dm_workshop.store import CampaignStore
from dm_workshop.state import CURRENCY_ITEM_ID


class FixedRng:
    def __init__(self, values):
        self.values = iter(values)

    def randint(self, _a, _b):
        return next(self.values)


@pytest.fixture()
def service(tmp_path: Path):
    return WorkshopService(CampaignStore(tmp_path / "test.db"))


@pytest.fixture()
def campaign(service):
    return service.create_campaign("测试战役")


def result_actor(service, campaign_id, operation):
    actor_id = operation["result"]["actor"]["id"]
    return service.get_campaign(campaign_id)["actors"][actor_id]


def test_new_campaign_seeds_common_equipment(service):
    campaign = service.create_campaign("常见装备目录")
    items = service.get_campaign(campaign["id"])["items"].values()
    by_slug = {item["slug"]: item for item in items}

    assert {"handaxe", "mace", "quarterstaff", "spear", "shortbow"} <= set(by_slug)
    assert {"chain-shirt", "chain-mail", "backpack", "bedroll", "torch",
            "waterskin", "tinderbox"} <= set(by_slug)
    assert by_slug["shortbow"]["weapon"] == {
        "to_hit_ability": "DEX", "damage": "1d6", "damage_type": "piercing"
    }
    assert by_slug["chain-shirt"]["armor"]["base_ac"] == 13


def test_duplicate_names_receive_distinct_ids(service, campaign):
    first = service.create_actor(campaign["id"], "哥布林", kind="monster")
    second = service.create_actor(campaign["id"], "哥布林", kind="monster")
    assert first["result"]["actor"]["id"] != second["result"]["actor"]["id"]
    assert len(service.get_campaign(campaign["id"])["actors"]) == 2


def test_partial_ability_update_preserves_other_stats(service, campaign):
    actor_id = service.create_actor(campaign["id"], "A")["result"]["actor"]["id"]
    service.update_actor(campaign["id"], actor_id, {"abilities": {"STR": 18}})
    actor = service.get_campaign(campaign["id"])["actors"][actor_id]
    assert actor["abilities"]["STR"] == 18
    assert actor["abilities"]["DEX"] == 10
    assert len(actor["abilities"]) == 6


def test_manual_zero_hp_synchronizes_life_state(service, campaign):
    pc = service.create_actor(campaign["id"], "PC")["result"]["actor"]["id"]
    service.update_actor(campaign["id"], pc, {"hp": 0})
    actor = service.get_campaign(campaign["id"])["actors"][pc]
    assert actor["life_state"] == "unconscious"
    assert "unconscious" in actor["conditions"]


def test_unconscious_cannot_be_manually_set_as_regular_condition(service, campaign):
    pc = service.create_actor(campaign["id"], "PC")["result"]["actor"]["id"]
    with pytest.raises(RuleError, match="生命状态机"):
        service.set_condition(campaign["id"], pc, "unconscious")


def test_condition_instances_do_not_share_state(service, campaign):
    a = service.create_actor(campaign["id"], "A")["result"]["actor"]["id"]
    b = service.create_actor(campaign["id"], "B")["result"]["actor"]["id"]
    service.set_condition(campaign["id"], a, "poisoned", duration=2)
    service.set_condition(campaign["id"], b, "poisoned", duration=5)
    state = service.get_campaign(campaign["id"])
    assert state["actors"][a]["conditions"]["poisoned"]["duration"] == 2
    assert state["actors"][b]["conditions"]["poisoned"]["duration"] == 5


def test_damage_at_zero_adds_failures_and_healing_wakes(service, campaign):
    actor_id = service.create_actor(
        campaign["id"], "战士", max_hp=10
    )["result"]["actor"]["id"]
    service.apply_damage(campaign["id"], actor_id, 10, "slashing")
    actor = service.get_campaign(campaign["id"])["actors"][actor_id]
    assert actor["life_state"] == "unconscious"
    service.apply_damage(campaign["id"], actor_id, 1, "slashing")
    actor = service.get_campaign(campaign["id"])["actors"][actor_id]
    assert actor["death_saves"]["failures"] == 1
    service.heal(campaign["id"], actor_id, 3)
    actor = service.get_campaign(campaign["id"])["actors"][actor_id]
    assert actor["life_state"] == "conscious"
    assert "unconscious" not in actor["conditions"]
    assert actor["death_saves"] == {"successes": 0, "failures": 0}


def test_critical_damage_at_zero_counts_two_failures(service, campaign):
    actor_id = service.create_actor(campaign["id"], "战士")["result"]["actor"]["id"]
    service.apply_damage(campaign["id"], actor_id, 10)
    service.apply_damage(campaign["id"], actor_id, 1, critical=True)
    actor = service.get_campaign(campaign["id"])["actors"][actor_id]
    assert actor["death_saves"]["failures"] == 2


def test_damage_resistance_and_immunity(service, campaign):
    actor_id = service.create_actor(
        campaign["id"], "元素裔", max_hp=20
    )["result"]["actor"]["id"]
    service.update_actor(campaign["id"], actor_id, {
        "resistances": ["fire"], "immunities": ["poison"]
    })
    fire = service.apply_damage(campaign["id"], actor_id, 7, "fire")["result"]
    poison = service.apply_damage(campaign["id"], actor_id, 9, "poison")["result"]
    assert fire["damage"] == 3
    assert poison["damage"] == 0
    assert service.get_campaign(campaign["id"])["actors"][actor_id]["hp"] == 17


def test_zero_effective_damage_does_not_fail_death_save(service, campaign):
    actor_id = service.create_actor(
        campaign["id"], "倒地角色", max_hp=10
    )["result"]["actor"]["id"]
    service.apply_damage(campaign["id"], actor_id, 10)
    service.apply_damage(campaign["id"], actor_id, 0)
    actor = service.get_campaign(campaign["id"])["actors"][actor_id]
    assert actor["death_saves"] == {"successes": 0, "failures": 0}


def test_short_rest_rejects_negative_healing(service, campaign):
    actor_id = service.create_actor(
        campaign["id"], "休息者", max_hp=10
    )["result"]["actor"]["id"]
    with pytest.raises(RuleError, match="不能为负"):
        service.rest(campaign["id"], actor_id, "short", hit_dice_healing=-1)


def test_overweight_add_is_rolled_back(service, campaign):
    actor_id = service.create_actor(
        campaign["id"], "弱者", abilities={"STR": 1}
    )["result"]["actor"]["id"]
    rope = next(i for i in service.search_items(campaign["id"], "麻绳"))
    with pytest.raises(RuleError, match="负重超限"):
        service.add_item(campaign["id"], actor_id, rope["id"], 2)
    assert service.get_campaign(campaign["id"])["actors"][actor_id]["inventory"] == {}


def test_regular_gear_cannot_be_equipped_as_weapon(service, campaign):
    actor_id = service.create_actor(campaign["id"], "A")["result"]["actor"]["id"]
    ration = next(i for i in service.search_items(campaign["id"], "口粮"))
    stack = service.add_item(campaign["id"], actor_id, ration["id"])["result"]["stack"]
    with pytest.raises(RuleError, match="不能装备"):
        service.equip_item(campaign["id"], actor_id, stack["id"], "main_hand")


def test_item_extension_cannot_override_stable_id(service, campaign):
    with pytest.raises(RuleError, match="核心字段"):
        service.define_item(campaign["id"], "伪造物品", data={"id": "fixed"})


@pytest.mark.parametrize("weapon", [
    {"to_hit_ability": "STR", "damage": "not-a-die", "damage_type": "slashing"},
    {"to_hit_ability": "STR", "damage": "1d6", "damage_type": "radiation"},
])
def test_custom_weapon_rejects_invalid_combat_fields(service, campaign, weapon):
    with pytest.raises(RuleError):
        service.define_item(
            campaign["id"], "非法武器", kind="weapon", data={"weapon": weapon}
        )


@pytest.mark.skip(reason="商店系统已下线")
def test_nonempty_container_cannot_be_transferred_or_sold(service, campaign):
    source = service.create_actor(campaign["id"], "来源")["result"]["actor"]["id"]
    target = service.create_actor(campaign["id"], "目标")["result"]["actor"]["id"]
    container = service.define_item(
        campaign["id"], "背包", stackable=False,
        data={"container": {"capacity_lb": 30}},
    )["result"]["item"]
    bag_stack = service.add_item(
        campaign["id"], source, container["id"]
    )["result"]["stack"]
    ration = next(i for i in service.search_items(campaign["id"], "口粮"))
    service.add_item(
        campaign["id"], source, ration["id"], container_id=bag_stack["id"]
    )
    shop = service.create_shop(campaign["id"], "杂货店")["result"]["shop"]

    with pytest.raises(RuleError, match="非空容器不能直接转移"):
        service.transfer_item(campaign["id"], source, target, bag_stack["id"])
    with pytest.raises(RuleError, match="非空容器不能出售"):
        service.sell_item(campaign["id"], shop["id"], source, bag_stack["id"])

    state = service.get_campaign(campaign["id"])
    assert bag_stack["id"] in state["actors"][source]["inventory"]
    assert state["actors"][target]["inventory"] == {}


@pytest.mark.skip(reason="商店系统已下线")
def test_shop_rejects_invalid_money_configuration(service, campaign):
    with pytest.raises(RuleError):
        service.create_shop(campaign["id"], "负资产商店", wallet_gp=-1)
    with pytest.raises(RuleError):
        service.create_shop(campaign["id"], "非法倍率商店", buy_multiplier=float("nan"))


@pytest.mark.skip(reason="商店系统已下线")
def test_buy_is_atomic_when_actor_cannot_carry(service, campaign):
    actor_id = service.create_actor(
        campaign["id"], "弱者", abilities={"STR": 1}
    )["result"]["actor"]["id"]
    service.update_actor(campaign["id"], actor_id, {"wallet_gp": 10000})
    shop = service.create_shop(campaign["id"], "杂货店")["result"]["shop"]
    rope = next(i for i in service.search_items(campaign["id"], "麻绳"))
    service.stock_shop(campaign["id"], shop["id"], rope["id"], 5)
    with pytest.raises(RuleError, match="负重超限"):
        service.buy_item(campaign["id"], shop["id"], actor_id, rope["id"], 2)
    state = service.get_campaign(campaign["id"])
    assert state["actors"][actor_id]["wallet_gp"] == 10000
    assert state["shops"][shop["id"]]["stock"][rope["id"]] == 5


def test_currency_is_party_only_inventory(service, campaign):
    actor_id = service.create_actor(campaign["id"], "角色")["result"]["actor"]["id"]
    with pytest.raises(RuleError, match="队伍共享仓库"):
        service.add_item(campaign["id"], actor_id, CURRENCY_ITEM_ID, 5)
    added = service.add_item(campaign["id"], "party", CURRENCY_ITEM_ID, 25)
    assert added["result"]["stack"]["quantity"] == 25
    with pytest.raises(RuleError, match="队伍共享仓库"):
        service.transfer_item(
            campaign["id"], "party", actor_id,
            added["result"]["stack"]["id"], 1,
        )


def test_discard_restores_last_saved_campaign(service, campaign):
    service.store.save_campaign(campaign["id"], "baseline")
    actor_id = service.create_actor(
        campaign["id"], "A"
    )["result"]["actor"]["id"]
    assert actor_id in service.get_campaign(campaign["id"])["actors"]
    service.store.discard_campaign_changes(campaign["id"])
    assert actor_id not in service.get_campaign(campaign["id"])["actors"]


def test_named_save_slots_can_restore_an_older_state(service, campaign):
    actor_a = service.create_actor(
        campaign["id"], "A"
    )["result"]["actor"]["id"]
    first = service.store.save_campaign(campaign["id"], "A only")
    actor_b = service.create_actor(
        campaign["id"], "B"
    )["result"]["actor"]["id"]
    service.store.save_campaign(campaign["id"], "A and B")
    service.store.load_save_slot(
        campaign["id"], first["result"]["save_id"]
    )
    actors = service.get_campaign(campaign["id"])["actors"]
    assert actor_a in actors
    assert actor_b not in actors


def test_encounter_enforces_turn_and_action_budget(service, campaign):
    # 持久化后的阵营键按规范顺序排列：enemy 取 1，party 取 20。
    service.rng = FixedRng([1, 20, 10, 4])
    pc = service.create_actor(campaign["id"], "PC")["result"]["actor"]["id"]
    mob = service.create_actor(campaign["id"], "Mob", kind="monster")["result"]["actor"]["id"]
    dagger = next(i for i in service.search_items(campaign["id"], "匕首"))
    added = service.add_item(campaign["id"], pc, dagger["id"])["result"]["stack"]
    service.equip_item(campaign["id"], pc, added["id"], "main_hand")
    enc = service.create_encounter(
        campaign["id"], "测试", {"party": [pc], "enemy": [mob]}
    )["result"]["encounter"]
    service.start_encounter(campaign["id"], enc["id"])
    with pytest.raises(RuleError, match="当前行动者"):
        service.combat_attack(campaign["id"], enc["id"], mob, pc,
                              to_hit=2, damage="1d4", damage_type="slashing")
    service.combat_attack(campaign["id"], enc["id"], pc, mob,
                          stack_id=added["id"])
    with pytest.raises(RuleError, match="已用完"):
        service.combat_attack(campaign["id"], enc["id"], pc, mob,
                              stack_id=added["id"])


def test_natural_one_death_save_counts_two_failures(service, campaign):
    pc = service.create_actor(campaign["id"], "PC")["result"]["actor"]["id"]
    mob = service.create_actor(campaign["id"], "Mob", kind="monster")["result"]["actor"]["id"]
    enc = service.create_encounter(
        campaign["id"], "测试", {"party": [pc], "enemy": [mob]}
    )["result"]["encounter"]
    service.rng = FixedRng([1, 20, 1])
    service.start_encounter(campaign["id"], enc["id"])
    service.apply_damage(campaign["id"], pc, 10)
    result = service.combat_death_save(campaign["id"], enc["id"], pc)
    assert result["result"]["death_saves"]["failures"] == 2


def test_last_pc_can_finish_death_saves_after_outcome_is_decided(service, campaign):
    pc = service.create_actor(
        campaign["id"], "PC", max_hp=5
    )["result"]["actor"]["id"]
    mob = service.create_actor(
        campaign["id"], "Mob", kind="monster"
    )["result"]["actor"]["id"]
    enc = service.create_encounter(
        campaign["id"], "收尾测试", {"party": [pc], "enemy": [mob]}
    )["result"]["encounter"]
    # enemy 先攻 20，party 先攻 1；攻击 10 命中，伤害骰为 6，死亡豁免为 10。
    service.rng = FixedRng([20, 1, 10, 6, 10])
    service.start_encounter(campaign["id"], enc["id"])
    service.combat_attack(
        campaign["id"], enc["id"], mob, pc,
        to_hit=99, damage="1d6", damage_type="slashing",
    )
    active = service.get_campaign(campaign["id"])["encounters"][enc["id"]]
    assert active["status"] == "active"
    assert active["outcome"] == "decided"
    service.combat_end_turn(campaign["id"], enc["id"], mob)
    result = service.combat_death_save(campaign["id"], enc["id"], pc)
    assert result["result"]["death_saves"]["successes"] == 1


def test_structured_spell_rejects_lower_slot_and_derives_save_dc(service, campaign):
    pc = service.create_actor(
        campaign["id"], "法师", abilities={"INT": 16}
    )["result"]["actor"]["id"]
    mob = service.create_actor(
        campaign["id"], "目标", kind="monster", max_hp=50
    )["result"]["actor"]["id"]
    fireball = next(s for s in service.search_spells(campaign["id"], "火球术"))
    service.learn_spell(campaign["id"], pc, fireball["id"])
    service.update_actor(campaign["id"], pc, {
        "spell_slots": {"1": {"max": 1, "used": 0},
                        "3": {"max": 1, "used": 0}}
    })
    enc = service.create_encounter(
        campaign["id"], "法术测试", {"party": [pc], "enemy": [mob]}
    )["result"]["encounter"]
    # enemy initiative 1, party initiative 20, failed DEX save 5, then 8d6.
    service.rng = FixedRng([1, 20, 5, 3, 3, 3, 3, 3, 3, 3, 3])
    service.start_encounter(campaign["id"], enc["id"])
    with pytest.raises(RuleError, match="低于法术环位"):
        service.combat_cast(campaign["id"], enc["id"], pc, fireball["id"],
                            mob, slot_level=1)
    result = service.combat_cast(
        campaign["id"], enc["id"], pc, fireball["id"], mob, slot_level=3
    )["result"]
    assert result["save"]["dc"] == 13  # 8 + PB 2 + INT 3
    assert result["applied"]["damage"] == 24
    state = service.get_campaign(campaign["id"])
    assert state["actors"][pc]["spell_slots"]["1"]["used"] == 0
    assert state["actors"][pc]["spell_slots"]["3"]["used"] == 1


def test_external_spell_catalog_search_and_snapshot_learning(service, campaign):
    actor_id = service.create_actor(
        campaign["id"], "法师", level=1, abilities={"INT": 16}
    )["result"]["actor"]["id"]
    service.set_actor_classes(campaign["id"], actor_id, {"wizard": 1})
    page = service.search_spell_catalog(
        campaign["id"], "舞光术", level=0, caster_class="wizard"
    )
    assert page["total"] == 1
    assert "description" not in page["items"][0]

    spell_id = page["items"][0]["id"]
    service.learn_spell(
        campaign["id"], actor_id, spell_id, source_class="wizard"
    )
    service.spell_catalog = type(service.spell_catalog)("missing-spells.db")
    details = service.get_spell_details(campaign["id"], spell_id)
    assert details["name"] == "舞光术"
    assert details["source"].startswith("user-provided")


def test_multiclass_requires_override_and_records_reason(service, campaign):
    actor_id = service.create_actor(
        campaign["id"], "低力量圣法师", level=2,
        abilities={"INT": 13, "CHA": 13, "STR": 10},
    )["result"]["actor"]["id"]
    with pytest.raises(RuleError, match="圣武士需要STR"):
        service.set_actor_classes(
            campaign["id"], actor_id, {"wizard": 1, "paladin": 1}
        )
    result = service.set_actor_classes(
        campaign["id"], actor_id, {"wizard": 1, "paladin": 1},
        override_reason="剧情赐福",
    )["result"]
    assert result["warnings"]


def test_wizard_spellbook_preparation_and_source_ability(service, campaign):
    actor_id = service.create_actor(
        campaign["id"], "法师", level=5, abilities={"INT": 16}
    )["result"]["actor"]["id"]
    service.set_actor_classes(campaign["id"], actor_id, {"wizard": 5})
    fireball = next(
        spell for spell in service.search_spells(campaign["id"], "火球术")
    )
    service.learn_spell(
        campaign["id"], actor_id, fireball["id"], source_class="wizard"
    )
    assert fireball["id"] not in service.get_campaign(campaign["id"])["actors"][actor_id]["spells"]
    service.prepare_spell(
        campaign["id"], actor_id, fireball["id"], "wizard"
    )
    casting = service.get_actor_spellcasting(campaign["id"], actor_id)
    assert casting["capacities"]["wizard"]["save_dc"] == 14
    assert casting["capacities"]["wizard"]["prepared_selected"] == 1


def test_multiclass_dual_slot_pool_requires_explicit_choice(service, campaign):
    actor_id = service.create_actor(
        campaign["id"], "双源施法者", level=2,
        abilities={"INT": 13, "CHA": 13},
    )["result"]["actor"]["id"]
    service.set_actor_classes(
        campaign["id"], actor_id, {"wizard": 1, "warlock": 1}
    )
    spell = service.define_spell(
        campaign["id"], "双源法术", 1, "utility"
    )["result"]["spell"]
    service.learn_spell(
        campaign["id"], actor_id, spell["id"], source_class="wizard",
        prepared=True,
    )
    service.learn_spell(
        campaign["id"], actor_id, spell["id"], source_class="warlock"
    )
    with pytest.raises(RuleError, match="明确指定 slot_pool"):
        service.cast_spell(
            campaign["id"], actor_id, spell["id"], source_class="wizard"
        )
    shared = service.cast_spell(
        campaign["id"], actor_id, spell["id"], source_class="wizard",
        slot_pool="shared",
    )["result"]
    pact = service.cast_spell(
        campaign["id"], actor_id, spell["id"], source_class="warlock",
        slot_pool="pact",
    )["result"]
    assert shared["slot_pool"] == "shared"
    assert pact["slot_pool"] == "pact"
    service.rest(campaign["id"], actor_id, "short")
    actor = service.get_campaign(campaign["id"])["actors"][actor_id]
    assert actor["pact_slots"]["used"] == 0
    assert actor["spell_slots"]["1"]["used"] == 1


def test_noncombat_cast_rejects_actor_in_active_encounter(service, campaign):
    caster_id = service.create_actor(
        campaign["id"], "Caster"
    )["result"]["actor"]["id"]
    enemy_id = service.create_actor(
        campaign["id"], "Enemy", kind="monster"
    )["result"]["actor"]["id"]
    spell = service.define_spell(
        campaign["id"], "Encounter cantrip", 0, "utility"
    )["result"]["spell"]
    service.learn_spell(campaign["id"], caster_id, spell["id"])
    encounter = service.create_encounter(
        campaign["id"], "Active encounter",
        {"party": [caster_id], "enemy": [enemy_id]},
    )["result"]["encounter"]
    service.rng = FixedRng([20, 1])
    service.start_encounter(campaign["id"], encounter["id"])

    with pytest.raises(RuleError, match="combat_cast"):
        service.cast_spell(campaign["id"], caster_id, spell["id"])

    result = service.cast_spell(
        campaign["id"], caster_id, spell["id"],
        override_reason="Scripted noncombat effect",
    )["result"]
    assert result["warnings"]


def test_class_downgrade_revalidates_existing_spells(service, campaign):
    actor_id = service.create_actor(
        campaign["id"], "降级法师", level=5, abilities={"INT": 16}
    )["result"]["actor"]["id"]
    service.set_actor_classes(campaign["id"], actor_id, {"wizard": 5})
    fireball = next(
        spell for spell in service.search_spells(campaign["id"], "火球术")
    )
    service.learn_spell(
        campaign["id"], actor_id, fireball["id"], source_class="wizard"
    )
    with pytest.raises(RuleError, match="无法保留 3 环法术"):
        service.set_actor_classes(campaign["id"], actor_id, {"wizard": 1})
    assert service.get_campaign(campaign["id"])["actors"][actor_id]["level"] == 5


def test_wizard_can_ritual_cast_unprepared_spellbook_spell(service, campaign):
    actor_id = service.create_actor(
        campaign["id"], "仪式法师", level=3, abilities={"INT": 16}
    )["result"]["actor"]["id"]
    service.set_actor_classes(campaign["id"], actor_id, {"wizard": 3})
    page = service.search_spell_catalog(
        campaign["id"], level=1, caster_class="wizard", ritual=True,
        limit=100,
    )
    spell_id = page["items"][0]["id"]
    service.learn_spell(
        campaign["id"], actor_id, spell_id, source_class="wizard"
    )
    before = service.get_campaign(campaign["id"])["actors"][actor_id]["spell_slots"]
    result = service.cast_spell(
        campaign["id"], actor_id, spell_id,
        source_class="wizard", as_ritual=True,
    )["result"]
    after = service.get_campaign(campaign["id"])["actors"][actor_id]["spell_slots"]
    assert result["slot_pool"] == "ritual"
    assert result["manual_resolution_required"] is True
    assert result["casting_time"].endswith("+ 10 分钟")
    assert after == before


def test_warlock_mystic_arcanum_is_once_per_long_rest(service, campaign):
    actor_id = service.create_actor(
        campaign["id"], "高阶邪术师", level=11, abilities={"CHA": 16}
    )["result"]["actor"]["id"]
    service.set_actor_classes(campaign["id"], actor_id, {"warlock": 11})
    page = service.search_spell_catalog(
        campaign["id"], level=6, caster_class="warlock", limit=100,
    )
    spell = next(
        service.get_spell_details(campaign["id"], item["id"])
        for item in page["items"]
        if service.get_spell_details(campaign["id"], item["id"])[
            "manual_resolution_required"
        ]
    )
    service.learn_spell(
        campaign["id"], actor_id, spell["id"], source_class="warlock"
    )
    first = service.cast_spell(
        campaign["id"], actor_id, spell["id"], source_class="warlock"
    )["result"]
    assert first["slot_pool"] == "arcanum"
    with pytest.raises(RuleError, match="已经使用"):
        service.cast_spell(
            campaign["id"], actor_id, spell["id"], source_class="warlock"
        )
    service.rest(campaign["id"], actor_id, "long")
    again = service.cast_spell(
        campaign["id"], actor_id, spell["id"], source_class="warlock"
    )["result"]
    assert again["slot_pool"] == "arcanum"
