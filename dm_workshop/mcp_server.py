"""标准 stdio MCP 适配层；只描述工具并转发到统一应用服务。"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from dm_workshop.dice import roll
from dm_workshop.currency import coins_to_cp, cp_to_coins
from dm_workshop.runtime import get_service

mcp = MCPServer(
    "DM Workshop",
    instructions=(
        "D&D 5e 2014 权威状态工具。写入前先查询战役摘要和实体 ID；"
        "不要猜测名称对应的 ID。法术先用 search_spell_catalog 查摘要，再按需"
        "调用 get_spell_details；角色应先配置职业再学习或准备法术。返回 "
        "manual_resolution_required 时交由 DM 裁定。所有写入都返回 "
        "operation_id，可用于撤销。"
    ),
)


@mcp.tool()
def list_campaigns() -> list[dict]:
    """列出全部战役及当前修订号。"""
    return get_service().list_campaigns()


@mcp.tool()
def create_campaign(name: str) -> dict:
    """创建独立战役，并导入 SRD 入门物品目录。"""
    return get_service().create_campaign(name)


@mcp.tool()
def get_campaign_summary(campaign_id: str) -> dict:
    """查询角色、负重、商店和活动遭遇的紧凑摘要。"""
    return get_service().campaign_summary(campaign_id)


@mcp.tool()
def get_campaign_state(campaign_id: str) -> dict:
    """查询一个战役的完整结构化权威状态。"""
    return get_service().get_campaign(campaign_id)


@mcp.tool()
def create_actor(campaign_id: str, name: str, kind: str = "pc",
                 level: int = 1, max_hp: int = 10, ac: int = 10,
                 abilities: dict[str, int] | None = None) -> dict:
    """创建 PC、NPC 或 monster；返回稳定 actor ID。"""
    return get_service().create_actor(campaign_id, name, kind=kind, level=level,
                                      max_hp=max_hp, ac=ac, abilities=abilities)


@mcp.tool()
def update_actor(campaign_id: str, actor_id: str, changes: dict[str, Any]) -> dict:
    """更新角色卡允许直接编辑的字段；生命状态由规则服务维护。"""
    return get_service().update_actor(campaign_id, actor_id, changes)


@mcp.tool()
def search_items(campaign_id: str, query: str = "") -> list[dict]:
    """按中文名、英文名或别名搜索物品定义并返回 item ID。"""
    return get_service().search_items(campaign_id, query)


@mcp.tool()
def search_spells(campaign_id: str, query: str = "") -> list[dict]:
    """兼容查询已写入战役的法术；完整目录请使用 search_spell_catalog。"""
    return get_service().search_spells(campaign_id, query)


@mcp.tool()
def get_spell_catalog_status() -> dict:
    """检查本地 spells.db 是否可用，并报告原始行数、唯一法术数和清洗警告。"""
    return get_service().get_spell_catalog_status()


@mcp.tool()
def search_spell_catalog(campaign_id: str, query: str = "",
                         level: int | None = None,
                         school: str | None = None,
                         caster_class: str | None = None,
                         ritual: bool | None = None,
                         limit: int = 20, offset: int = 0) -> dict:
    """分页搜索完整法术目录；可按环位、学派、职业和仪式筛选，仅返回摘要。"""
    return get_service().search_spell_catalog(
        campaign_id, query, level=level, school=school,
        caster_class=caster_class, ritual=ritual, limit=limit, offset=offset,
    )


@mcp.tool()
def get_spell_details(campaign_id: str, spell_id: str) -> dict:
    """按稳定 spell ID 读取法术正文、职业、施法信息和自动结算能力。"""
    return get_service().get_spell_details(campaign_id, spell_id)


@mcp.tool()
def set_actor_classes(campaign_id: str, actor_id: str,
                      class_levels: dict[str, int],
                      spell_sources: dict[str, str] | None = None,
                      override_reason: str | None = None) -> dict:
    """设置十二核心职业等级并重算多职业法术位；DM 特批必须说明原因。"""
    return get_service().set_actor_classes(
        campaign_id, actor_id, class_levels,
        spell_sources=spell_sources, override_reason=override_reason,
    )


@mcp.tool()
def get_actor_spellcasting(campaign_id: str, actor_id: str) -> dict:
    """查询角色职业施法属性、DC、攻击加值、法术容量和剩余资源。"""
    return get_service().get_actor_spellcasting(campaign_id, actor_id)


@mcp.tool()
def learn_spell(campaign_id: str, actor_id: str, spell_id: str,
                remove: bool = False, source_class: str | None = None,
                prepared: bool = False,
                override_reason: str | None = None) -> dict:
    """学习戏法、已知法术或写入法师法术书；职业模型启用后须给来源职业。"""
    return get_service().learn_spell(campaign_id, actor_id, spell_id,
                                     source_class=source_class,
                                     prepared=prepared, remove=remove,
                                     override_reason=override_reason)


@mcp.tool()
def prepare_spell(campaign_id: str, actor_id: str, spell_id: str,
                  source_class: str, prepared: bool = True,
                  override_reason: str | None = None) -> dict:
    """为牧师、德鲁伊、圣武士或法师准备/取消准备一个有环法术。"""
    return get_service().prepare_spell(
        campaign_id, actor_id, spell_id, source_class,
        prepared=prepared, override_reason=override_reason,
    )


@mcp.tool()
def define_spell(campaign_id: str, name: str, level: int, kind: str,
                 name_en: str = "", damage: str | None = None,
                 damage_type: str | None = None, heal: str | None = None,
                 save_ability: str | None = None,
                 save_result: str | None = None,
                 slot_scaling: str | None = None,
                 description: str = "") -> dict:
    """创建具备明确机器可读效果的自定义法术。"""
    return get_service().define_spell(
        campaign_id, name, level, kind, name_en=name_en, damage=damage,
        damage_type=damage_type, heal=heal, save_ability=save_ability,
        save_result=save_result, slot_scaling=slot_scaling,
        description=description,
    )


@mcp.tool()
def define_item(campaign_id: str, name: str, kind: str = "gear",
                weight_lb: float = 0, price_cp: int = 0,
                stackable: bool = True, aliases: list[str] | None = None,
                data: dict[str, Any] | None = None) -> dict:
    """创建自定义物品定义。金额单位固定为铜币，重量单位为磅。"""
    return get_service().define_item(
        campaign_id, name, kind=kind, weight_lb=weight_lb, price_cp=price_cp,
        stackable=stackable, aliases=aliases, data=data,
    )


@mcp.tool()
def add_item(campaign_id: str, owner_id: str, item_id: str,
             quantity: int = 1, container_id: str | None = None,
             notes: str = "") -> dict:
    """向角色或 party 共享仓库添加物品；超出标准负重时原子失败。"""
    return get_service().add_item(campaign_id, owner_id, item_id, quantity,
                                  container_id=container_id, notes=notes)


@mcp.tool()
def remove_item(campaign_id: str, owner_id: str, stack_id: str,
                quantity: int = 1) -> dict:
    """按物品栈 ID 移除指定数量。"""
    return get_service().remove_item(campaign_id, owner_id, stack_id, quantity)


@mcp.tool()
def transfer_item(campaign_id: str, from_owner_id: str, to_owner_id: str,
                  stack_id: str, quantity: int = 1) -> dict:
    """在角色和 party 仓库间原子转移物品。"""
    return get_service().transfer_item(campaign_id, from_owner_id, to_owner_id,
                                       stack_id, quantity)


@mcp.tool()
def equip_item(campaign_id: str, actor_id: str, stack_id: str,
               slot: str) -> dict:
    """装备单件物品并重新计算 AC。"""
    return get_service().equip_item(campaign_id, actor_id, stack_id, slot)


@mcp.tool()
def unequip_item(campaign_id: str, actor_id: str, stack_id: str) -> dict:
    """卸下物品并重新计算 AC。"""
    return get_service().unequip_item(campaign_id, actor_id, stack_id)


@mcp.tool()
def create_shop(campaign_id: str, name: str, buy_multiplier: float = 1.0,
                sell_multiplier: float = 0.5,
                wallet_cp: int = 100000) -> dict:
    """创建商店；buy_multiplier 是角色购买价倍率。"""
    return get_service().create_shop(
        campaign_id, name, buy_multiplier=buy_multiplier,
        sell_multiplier=sell_multiplier, wallet_cp=wallet_cp,
    )


@mcp.tool()
def stock_shop(campaign_id: str, shop_id: str, item_id: str,
               quantity: int | None) -> dict:
    """设置商店库存；quantity 为 null 表示无限库存。"""
    return get_service().stock_shop(campaign_id, shop_id, item_id, quantity)


@mcp.tool()
def buy_item(campaign_id: str, shop_id: str, actor_id: str,
             item_id: str, quantity: int = 1) -> dict:
    """原子完成扣款、减库存、加背包和负重校验。"""
    return get_service().buy_item(campaign_id, shop_id, actor_id, item_id,
                                  quantity)


@mcp.tool()
def sell_item(campaign_id: str, shop_id: str, actor_id: str,
              stack_id: str, quantity: int = 1) -> dict:
    """原子完成出售、商店付款和库存增加。"""
    return get_service().sell_item(campaign_id, shop_id, actor_id, stack_id,
                                   quantity)


@mcp.tool()
def create_encounter(campaign_id: str, name: str,
                     sides: dict[str, list[str]]) -> dict:
    """用 actor ID 建立至少两个阵营的无地图遭遇。"""
    return get_service().create_encounter(campaign_id, name, sides)


@mcp.tool()
def start_encounter(campaign_id: str, encounter_id: str) -> dict:
    """服务端投先攻并启动遭遇。"""
    return get_service().start_encounter(campaign_id, encounter_id)


@mcp.tool()
def combat_attack(campaign_id: str, encounter_id: str, actor_id: str,
                  target_id: str, stack_id: str | None = None,
                  to_hit: int | None = None, damage: str | None = None,
                  damage_type: str | None = None,
                  advantage: bool | None = None) -> dict:
    """当前行动者执行攻击；优先使用已装备武器 stack ID。"""
    return get_service().combat_attack(
        campaign_id, encounter_id, actor_id, target_id, stack_id=stack_id,
        to_hit=to_hit, damage=damage, damage_type=damage_type,
        advantage=advantage,
    )


@mcp.tool()
def combat_death_save(campaign_id: str, encounter_id: str,
                      actor_id: str) -> dict:
    """为当前回合的昏迷 PC 执行死亡豁免，包括自然 1/20。"""
    return get_service().combat_death_save(campaign_id, encounter_id, actor_id)


@mcp.tool()
def combat_cast(campaign_id: str, encounter_id: str, actor_id: str,
                spell_id: str, target_id: str, slot_level: int | None = None,
                advantage: bool | None = None,
                source_class: str | None = None,
                slot_pool: str | None = None,
                override_reason: str | None = None) -> dict:
    """施放已学习的结构化法术；程序推导 DC/攻击加值并校验环位。"""
    return get_service().combat_cast(
        campaign_id, encounter_id, actor_id, spell_id, target_id,
        slot_level=slot_level, advantage=advantage,
        source_class=source_class, slot_pool=slot_pool,
        override_reason=override_reason,
    )


@mcp.tool()
def cast_spell(campaign_id: str, actor_id: str, spell_id: str,
               target_id: str | None = None,
               slot_level: int | None = None,
               source_class: str | None = None,
               slot_pool: str | None = None,
               as_ritual: bool = False,
               advantage: bool | None = None,
               override_reason: str | None = None) -> dict:
    """在遭遇外普通或仪式施法；复杂法术保留资源消耗并返回手动裁定标记。"""
    return get_service().cast_spell(
        campaign_id, actor_id, spell_id, target_id=target_id,
        slot_level=slot_level, source_class=source_class,
        slot_pool=slot_pool, as_ritual=as_ritual, advantage=advantage,
        override_reason=override_reason,
    )


@mcp.tool()
def combat_end_turn(campaign_id: str, encounter_id: str,
                    actor_id: str) -> dict:
    """结束当前行动者回合、推进状态持续时间和轮次。"""
    return get_service().combat_end_turn(campaign_id, encounter_id, actor_id)


@mcp.tool()
def apply_damage(campaign_id: str, actor_id: str, amount: int,
                 damage_type: str = "", critical: bool = False) -> dict:
    """应用已确定的伤害；0 HP 角色会累计死亡豁免失败。"""
    return get_service().apply_damage(campaign_id, actor_id, amount,
                                      damage_type, critical=critical)


@mcp.tool()
def heal(campaign_id: str, actor_id: str, amount: int) -> dict:
    """治疗非死亡角色；从 0 HP 恢复时自动清除昏迷和死亡豁免。"""
    return get_service().heal(campaign_id, actor_id, amount)


@mcp.tool()
def set_condition(campaign_id: str, actor_id: str, name: str,
                  duration: int | None = None, condition_source: str = "",
                  remove: bool = False) -> dict:
    """添加或移除独立状态实例，不共享可变预设。"""
    return get_service().set_condition(
        campaign_id, actor_id, name, duration=duration,
        condition_source=condition_source, remove=remove,
    )


@mcp.tool()
def rest(campaign_id: str, actor_id: str, rest_type: str,
         hit_dice_healing: int = 0) -> dict:
    """执行 short 或 long 休息；短休治疗量由已结算生命骰提供。"""
    return get_service().rest(campaign_id, actor_id, rest_type,
                              hit_dice_healing=hit_dice_healing)


@mcp.tool()
def roll_dice(expression: str, critical: bool = False) -> dict:
    """投掷可审计骰子；critical 只翻倍骰子数量，不翻倍固定修正。"""
    return roll(expression, critical=critical).to_dict()


@mcp.tool()
def convert_coins_to_cp(pp: int = 0, gp: int = 0, ep: int = 0,
                        sp: int = 0, cp: int = 0) -> dict:
    """把五种 5e 货币精确换算为程序使用的铜币总值。"""
    total = coins_to_cp(pp=pp, gp=gp, ep=ep, sp=sp, cp=cp)
    return {"total_cp": total}


@mcp.tool()
def format_cp_as_coins(total_cp: int) -> dict:
    """把铜币总值格式化为规范 PP/GP/SP/CP 组合。"""
    return cp_to_coins(total_cp)


@mcp.tool()
def list_operations(campaign_id: str, limit: int = 50) -> list[dict]:
    """查询最近写操作及可撤销 operation ID。"""
    return get_service().store.list_operations(campaign_id, limit)


@mcp.tool()
def undo_operation(campaign_id: str, operation_id: str) -> dict:
    """撤销最后一次未被后续修改覆盖的操作。"""
    return get_service().store.undo(campaign_id, operation_id, source="mcp")


def run() -> None:
    mcp.run(transport="stdio")
