from pathlib import Path
import pytest

from dm_workshop.errors import RuleError
from dm_workshop.service import WorkshopService
from dm_workshop.state import CURRENCY_ITEM_ID, passive_perception, proficiency_bonus
from dm_workshop.store import CampaignStore


@pytest.fixture
def service(tmp_path: Path) -> WorkshopService:
    return WorkshopService(CampaignStore(tmp_path / "test.db"))


@pytest.fixture
def campaign(service: WorkshopService):
    return service.create_campaign("测试战役")


def get_actor(service: WorkshopService, campaign_id: str, actor_id: str) -> dict:
    state = service.get_campaign(campaign_id)
    return state["actors"].get(actor_id)


def test_proficiency_and_passive_perception_calculations():
    assert proficiency_bonus(1) == 2
    assert proficiency_bonus(4) == 2
    assert proficiency_bonus(5) == 3
    assert proficiency_bonus(9) == 4
    assert proficiency_bonus(13) == 5
    assert proficiency_bonus(17) == 6
    assert proficiency_bonus(20) == 6

    # 10 + WIS mod (+2) + prof (+2 if proficient in perception)
    actor_no_prof = {
        "abilities": {"WIS": 14},
        "skill_proficiencies": [],
        "proficiency_bonus": 2,
    }
    assert passive_perception(actor_no_prof) == 12

    actor_with_prof = {
        "abilities": {"WIS": 14},
        "skill_proficiencies": ["perception"],
        "proficiency_bonus": 2,
    }
    assert passive_perception(actor_with_prof) == 14


def test_level_up_updates_proficiency_bonus(service: WorkshopService, campaign):
    actor_id = service.create_actor(
        campaign["id"], "冒险者", level=1, abilities={"STR": 16}
    )["result"]["actor"]["id"]

    actor = get_actor(service, campaign["id"], actor_id)
    assert actor["level"] == 1
    assert actor["proficiency_bonus"] == 2

    # 升到 5 级：战士 5
    service.set_actor_classes(campaign["id"], actor_id, {"fighter": 5})
    actor = get_actor(service, campaign["id"], actor_id)
    assert actor["level"] == 5
    assert actor["proficiency_bonus"] == 3


def test_massive_damage_instant_death(service: WorkshopService, campaign):
    # 最大生命值为 10，当前生命值为 10
    actor_id = service.create_actor(
        campaign["id"], "脆皮法师", max_hp=10, abilities={"CON": 10}
    )["result"]["actor"]["id"]

    # 受到 15 点伤害：hp 降为 0，溢出 5 点（小于 max_hp 10），应为昏迷（dying），未直接死亡
    res = service.apply_damage(campaign["id"], actor_id, 15)["result"]
    actor = get_actor(service, campaign["id"], actor_id)
    assert actor["hp"] == 0
    assert actor["death_saves"]["failures"] == 0
    assert res["instant_death"] is False
    assert res["life_state"] == "unconscious"

    # 治愈到 5 点生命值
    service.heal(campaign["id"], actor_id, 5)
    actor = get_actor(service, campaign["id"], actor_id)
    assert actor["hp"] == 5

    # 受到 15 点伤害：降到 0 且溢出 10 点（>= max_hp 10），触发即死
    res = service.apply_damage(campaign["id"], actor_id, 15)["result"]
    actor = get_actor(service, campaign["id"], actor_id)
    assert actor["hp"] == 0
    assert actor["death_saves"]["failures"] == 3
    assert res["instant_death"] is True
    assert res["life_state"] == "dead"


def test_check_ability_engine(service: WorkshopService, campaign):
    actor_id = service.create_actor(
        campaign["id"], "游侠", level=1,
        abilities={"DEX": 16, "WIS": 14, "STR": 10}
    )["result"]["actor"]["id"]
    service.update_actor(campaign["id"], actor_id, {"skill_proficiencies": ["stealth"]})

    # 1. 敏捷属性检定 (DEX mod = +3)
    res_ability = service.check_ability(
        campaign["id"], actor_id, ability="DEX", dc=10
    )["result"]
    assert res_ability["ability"] == "DEX"
    assert res_ability["ability_modifier"] == 3
    assert res_ability["total"] == res_ability["d20"]["kept"] + 3
    assert "DC 10" in res_ability["summary"]

    # 2. 隐匿技能检定 (熟练：DEX +3 + prof +2 = +5)
    res_skill = service.check_ability(
        campaign["id"], actor_id, skill="stealth"
    )["result"]
    assert res_skill["proficient"] is True
    assert res_skill["total_bonus"] == 5
    assert res_skill["total"] == res_skill["d20"]["kept"] + 5

    # 3. 中文别名映射技能检定（如 "隐匿" 映射到 stealth）
    res_skill_cn = service.check_ability(
        campaign["id"], actor_id, skill="隐匿"
    )["result"]
    assert res_skill_cn["skill"] == "stealth"
    assert res_skill_cn["proficient"] is True

    # 4. 豁免检定（非豁免熟练，WIS mod = +2）
    res_save = service.check_ability(
        campaign["id"], actor_id, ability="WIS", is_saving_throw=True, dc=12
    )["result"]
    assert res_save["is_saving_throw"] is True
    assert res_save["total_bonus"] == 2
    assert res_save["total"] == res_save["d20"]["kept"] + 2

    # 5. 优势检定（掷两颗骰子并取较大者）
    res_adv = service.check_ability(
        campaign["id"], actor_id, ability="DEX", advantage=True
    )["result"]
    assert len(res_adv["d20"]["rolls"]) == 2
    assert res_adv["d20"]["kept"] == max(res_adv["d20"]["rolls"])


def test_monster_presets_and_spawn(service: WorkshopService, campaign):
    presets = service.list_monster_presets()
    assert len(presets) >= 6
    preset_ids = [p["preset_id"] for p in presets]
    assert "goblin" in preset_ids
    assert "bandit" in preset_ids

    # 生成一只哥布林
    spawn_res = service.spawn_monster(campaign["id"], "goblin", name="哥布林斥候")["result"]
    assert spawn_res["count"] == 1
    goblin_id = spawn_res["monsters"][0]["id"]
    monster = get_actor(service, campaign["id"], goblin_id)
    assert monster["name"] == "哥布林斥候"
    assert monster["kind"] == "monster"
    assert monster["preset_id"] == "goblin"
    assert monster["abilities"]["DEX"] == 14
    # 自动装备了武器
    assert len(monster["inventory"]) > 0
    equipped = [item for item in monster["inventory"].values() if item.get("equipped_slot")]
    assert len(equipped) > 0


def test_encounter_workflow_with_spawned_monster(service: WorkshopService, campaign):
    pc_id = service.create_actor(campaign["id"], "战士", kind="pc", max_hp=20)["result"]["actor"]["id"]
    mon_res = service.spawn_monster(campaign["id"], "goblin", name="地精A")["result"]
    goblin_id = mon_res["monsters"][0]["id"]

    # 创建遭遇战
    enc_res = service.create_encounter(
        campaign["id"],
        name="哥布林伏击战",
        sides={"party": [pc_id], "monsters": [goblin_id]}
    )["result"]
    enc_id = enc_res["encounter"]["id"]

    # 启动遭遇战
    service.start_encounter(campaign["id"], enc_id)

    # 验证活跃遭遇中的战斗员受保护，不可被删除
    with pytest.raises(RuleError, match="进行中的遭遇战内"):
        service.delete_actor(campaign["id"], goblin_id)

    # 结束遭遇战
    end_res = service.end_encounter(campaign["id"], enc_id, outcome="victory")["result"]
    assert end_res["status"] == "completed"
    assert end_res["outcome"] == "victory"

    # 战斗结束后可安全删除怪物角色
    del_res = service.delete_actor(campaign["id"], goblin_id)["result"]
    assert del_res["actor_id"] == goblin_id
    assert get_actor(service, campaign["id"], goblin_id) is None


def test_currency_and_rest(service: WorkshopService, campaign):
    actor_id = service.create_actor(
        campaign["id"], "富商盗贼",
        max_hp=20,
        abilities={"CON": 14}  # CON mod = +2
    )["result"]["actor"]["id"]
    service.apply_damage(campaign["id"], actor_id, 15)  # hp 变 5

    # 调整货币：存入 50 GP
    cur_res = service.adjust_currency(campaign["id"], 50, owner_id=actor_id)["result"]
    assert cur_res["total_gp"] == 50
    actor = get_actor(service, campaign["id"], actor_id)
    currency_stack = next(
        (s for s in actor["inventory"].values() if s.get("item_id") == CURRENCY_ITEM_ID),
        None
    )
    assert currency_stack is not None
    assert currency_stack["quantity"] == 50

    # 短休消耗 1 颗生命骰
    short_rest_res = service.rest(campaign["id"], actor_id, rest_type="short", hit_dice_spent=1)["result"]
    actor = get_actor(service, campaign["id"], actor_id)
    assert actor["hit_dice"]["used"] == 1  # 消耗 1 颗
    # 恢复量至少是 1(骰子最低1) + CON(+2) = 3 -> hp >= 8
    assert actor["hp"] >= 8
    assert short_rest_res["healed"] >= 3

    # 长休恢复生命值和生命骰
    long_rest_res = service.rest(campaign["id"], actor_id, rest_type="long")["result"]
    actor = get_actor(service, campaign["id"], actor_id)
    assert actor["hp"] == actor["max_hp"]
    assert actor["hit_dice"]["used"] == 0  # 恢复全部已消耗生命骰
    assert long_rest_res["hp"] == actor["max_hp"]
