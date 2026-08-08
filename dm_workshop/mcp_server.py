"""标准 stdio MCP 适配层；只描述工具并转发到统一应用服务。"""

from __future__ import annotations

from functools import wraps
from inspect import signature
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context

from dm_workshop.dice import roll
from dm_workshop.mcp_groups import (
    CAPABILITY_GROUPS,
    actions_for_group,
    get_group,
    resolve_action,
    validate_registry,
)
from dm_workshop.mcp_compact import (
    actor_spellcasting as compact_actor_spellcasting,
    campaign_summary as compact_campaign_summary,
    campaign_view, compact_catalog_page, mutation_receipt,
    search_items as compact_search_items,
    search_spells as compact_search_spells,
    spell_details as compact_spell_details,
)
from dm_workshop.runtime import get_service

mcp = MCPServer(
    "DM Workshop",
    instructions=(
        "D&D 5e 2014 状态工具。缓存稳定 ID，使用分页和分区查询，避免重复读取。"
        "法术正文仅在裁定需要时读取。写入先进入内存草稿，仅在用户明确要求时"
        "调用 save_campaign；manual_resolution_required 交由 DM 裁定。"
    ),
)


@mcp.tool()
def list_campaigns() -> list[dict]:
    """列出全部战役及当前修订号。"""
    return get_service().list_campaigns()


@mcp.tool()
def create_campaign(name: str, preset_characters: list[dict]) -> dict:
    """创建独立战役，并导入 SRD 入门物品目录。"""
    state = get_service().create_campaign(name, preset_characters=preset_characters)
    return {
        "dirty": True,
        "result": {
            "entity_id": state["id"],
            "changed": {"name": state["name"]},
        },
    }


@mcp.tool()
def get_campaign_summary(campaign_id: str) -> dict:
    """查询角色、负重、商店和活动遭遇的紧凑摘要。"""
    return compact_campaign_summary(get_service(), campaign_id)


@mcp.tool()
def get_campaign_state(campaign_id: str, view: str = "actors",
                       entity_id: str | None = None,
                       limit: int = 10, offset: int = 0) -> dict:
    """按 view 分区分页查询；actor、shop、encounter 视图必须提供 entity_id。"""
    return campaign_view(
        get_service(), campaign_id, view, entity_id=entity_id,
        limit=limit, offset=offset,
    )


@mcp.tool()
def list_actor_presets() -> list[dict]:
    """列出新战役可选的 12 个一级职业预设及其摘要。"""
    return get_service().list_actor_presets()


@mcp.tool()
def update_actor(campaign_id: str, actor_id: str, changes: dict[str, Any]) -> dict:
    """更新角色卡允许直接编辑的字段；生命状态由规则服务维护。"""
    return get_service().update_actor(campaign_id, actor_id, changes)


@mcp.tool()
def search_items(campaign_id: str, query: str = "", limit: int = 10,
                 offset: int = 0) -> dict:
    """按中文名、英文名或别名搜索物品定义并返回 item ID。"""
    return compact_search_items(
        get_service(), campaign_id, query, limit=limit, offset=offset,
    )


@mcp.tool()
def search_spells(campaign_id: str, query: str = "", limit: int = 10,
                  offset: int = 0) -> dict:
    """兼容查询已写入战役的法术；完整目录请使用 search_spell_catalog。"""
    return compact_search_spells(
        get_service(), campaign_id, query, limit=limit, offset=offset,
    )


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
                         limit: int = 10, offset: int = 0) -> dict:
    """分页搜索完整法术目录；可按环位、学派、职业和仪式筛选，仅返回摘要。"""
    page = get_service().search_spell_catalog(
        campaign_id, query, level=level, school=school,
        caster_class=caster_class, ritual=ritual, limit=limit, offset=offset,
    )
    return compact_catalog_page(page)


@mcp.tool()
def get_spell_details(campaign_id: str, spell_id: str,
                      include_text: bool = False) -> dict:
    """读取法术规则详情；仅在裁定需要正文时设置 include_text=true。"""
    return compact_spell_details(
        get_service(), campaign_id, spell_id, include_text=include_text,
    )


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
def get_actor_spellcasting(campaign_id: str, actor_id: str,
                           include_repertoire: bool = False,
                           limit: int = 10, offset: int = 0) -> dict:
    """查询角色职业施法属性、DC、攻击加值、法术容量和剩余资源。"""
    return compact_actor_spellcasting(
        get_service(), campaign_id, actor_id,
        include_repertoire=include_repertoire, limit=limit, offset=offset,
    )


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
                weight_lb: float = 0, price_gp: int = 0,
                stackable: bool = True, aliases: list[str] | None = None,
                data: dict[str, Any] | None = None) -> dict:
    """创建自定义物品定义。金额单位固定为整数 GP，重量单位为磅。"""
    return get_service().define_item(
        campaign_id, name, kind=kind, weight_lb=weight_lb, price_gp=price_gp,
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
                wallet_gp: int = 100000) -> dict:
    """创建商店；buy_multiplier 是角色购买价倍率。"""
    return get_service().create_shop(
        campaign_id, name, buy_multiplier=buy_multiplier,
        sell_multiplier=sell_multiplier, wallet_gp=wallet_gp,
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
def save_campaign(campaign_id: str, slot_name: str | None = None,
                  note: str = "", overwrite: bool = False) -> dict:
    """按用户明确指示把内存草稿保存到命名存档。"""
    return get_service().store.save_campaign(
        campaign_id, slot_name, note=note, overwrite=overwrite,
    )


@mcp.tool()
def discard_campaign_changes(campaign_id: str) -> dict:
    """整体放弃该战役自上次保存后的全部草稿。"""
    return get_service().store.discard_campaign_changes(campaign_id)


@mcp.tool()
def list_save_slots(campaign_id: str, limit: int = 10,
                    offset: int = 0) -> dict:
    """分页列出命名存档及当前活动存档。"""
    return get_service().store.list_save_slots(
        campaign_id, limit=limit, offset=offset,
    )


@mcp.tool()
def load_save_slot(campaign_id: str, save_id: str) -> dict:
    """加载命名存档；存在未保存草稿时拒绝。"""
    return get_service().store.load_save_slot(campaign_id, save_id)


_MUTATION_TOOLS = {
    "update_actor", "set_actor_classes", "learn_spell",
    "prepare_spell", "define_spell", "define_item", "add_item",
    "remove_item", "transfer_item", "equip_item", "unequip_item",
    "create_shop", "stock_shop", "buy_item", "sell_item",
    "create_encounter", "start_encounter", "combat_attack",
    "combat_death_save", "combat_cast", "cast_spell", "combat_end_turn",
    "apply_damage", "heal", "set_condition", "rest",
}


def _install_compact_receipts() -> None:
    """保留原工具 Schema，只替换执行函数的输出投影。"""
    for tool_name in _MUTATION_TOOLS:
        tool = _implementation_mcp._tool_manager._tools[tool_name]
        original = tool.fn
        original_signature = signature(original)

        @wraps(original)
        def compacted(*args, __name=tool_name, __fn=original,
                      __signature=original_signature, **kwargs):
            bound = __signature.bind_partial(*args, **kwargs)
            bound.apply_defaults()
            return mutation_receipt(
                __name, __fn(*args, **kwargs), dict(bound.arguments)
            )

        tool.fn = compacted
        globals()[tool_name] = compacted


_implementation_mcp = mcp
_install_compact_receipts()
validate_registry(set(_implementation_mcp._tool_manager._tools))


mcp = MCPServer(
    "DM Workshop",
    instructions=(
        "D&D 5e 2014 状态工具。先调用 list_capability_groups 查看功能大类，"
        "再调用 list_group_actions 读取目标大类的动作，最后使用 call_capability。"
        "缓存稳定 ID，使用分页和分区查询；写入先进入内存草稿，仅在用户明确要求时"
        "通过 campaign 大类的 save_campaign 保存。"
    ),
)


@mcp.tool()
def list_capability_groups() -> list[dict[str, Any]]:
    """列出可按需读取的 MCP 功能大类。"""
    return [
        {
            "id": group_id,
            "name": definition["name"],
            "description": definition["description"],
            "action_count": len(definition["actions"]),
        }
        for group_id, definition in CAPABILITY_GROUPS.items()
    ]


@mcp.tool()
def list_group_actions(group: str) -> dict[str, Any]:
    """读取指定 MCP 大类的动作名称、说明和读写属性。"""
    definition = get_group(group)
    return {
        "id": group,
        "name": definition["name"],
        "description": definition["description"],
        "actions": actions_for_group(
            group, _implementation_mcp._tool_manager._tools
        ),
    }


@mcp.tool()
async def call_capability(
        group: str, action: str,
        arguments: dict[str, Any] | None = None) -> Any:
    """按大类和原动作名调用一个内部 MCP 功能。"""
    tool = resolve_action(
        group, action, _implementation_mcp._tool_manager._tools
    )
    context = Context(
        mcp_server=_implementation_mcp,
        subscriptions=_implementation_mcp._subscriptions,
    )
    return await tool.run(arguments or {}, context, convert_result=False)


def run() -> None:
    mcp.run(transport="stdio")
