"""可再分发的 SRD 入门目录。

目录数据与规则代码刻意分离，后续可以从 CC BY 4.0 来源生成完整数据集，
而不必让规则服务依赖原始文档格式。
"""

SRD_ATTRIBUTION = {
    "title": "Systems Reference Document 5.1",
    "publisher": "Wizards of the Coast LLC",
    "license": "Creative Commons Attribution 4.0 International",
    "url": "https://creativecommons.org/licenses/by/4.0/",
}

STARTER_ITEMS = [
    {"slug": "club", "name": "短棒", "name_en": "Club", "kind": "weapon",
     "weight_lb": 2.0, "price_cp": 10, "stackable": False,
     "weapon": {"to_hit_ability": "STR", "damage": "1d4",
                "damage_type": "bludgeoning"}},
    {"slug": "dagger", "name": "匕首", "name_en": "Dagger", "kind": "weapon",
     "weight_lb": 1.0, "price_cp": 200, "stackable": False,
     "weapon": {"to_hit_ability": "DEX", "damage": "1d4",
                "damage_type": "piercing"}},
    {"slug": "longsword", "name": "长剑", "name_en": "Longsword", "kind": "weapon",
     "weight_lb": 3.0, "price_cp": 1500, "stackable": False,
     "weapon": {"to_hit_ability": "STR", "damage": "1d8",
                "damage_type": "slashing"}},
    {"slug": "shield", "name": "盾牌", "name_en": "Shield", "kind": "armor",
     "weight_lb": 6.0, "price_cp": 1000, "stackable": False,
     "armor": {"ac_bonus": 2, "slot": "shield"}},
    {"slug": "leather-armor", "name": "皮甲", "name_en": "Leather Armor",
     "kind": "armor", "weight_lb": 10.0, "price_cp": 1000,
     "stackable": False, "armor": {"base_ac": 11, "dex_cap": None,
                                     "slot": "armor"}},
    {"slug": "healing-potion", "name": "治疗药水", "name_en": "Potion of Healing",
     "kind": "consumable", "weight_lb": 0.5, "price_cp": 5000,
     "stackable": True, "effect": {"heal": "2d4+2"}},
    {"slug": "rations", "name": "口粮（1天）", "name_en": "Rations (1 day)",
     "kind": "gear", "weight_lb": 2.0, "price_cp": 50, "stackable": True},
    {"slug": "rope-hempen", "name": "麻绳（50尺）", "name_en": "Hempen Rope (50 feet)",
     "kind": "gear", "weight_lb": 10.0, "price_cp": 100, "stackable": True},
]

STARTER_SPELLS = [
    {"slug": "fire-bolt", "name": "火焰箭", "name_en": "Fire Bolt",
     "level": 0, "school": "塑能", "ritual": False,
     "classes": ["sorcerer", "wizard"], "kind": "attack",
     "damage": "1d10", "damage_type": "fire",
     "description": "进行一次远程法术攻击。"},
    {"slug": "cure-wounds", "name": "疗伤术", "name_en": "Cure Wounds",
     "level": 1, "school": "塑能", "ritual": False,
     "classes": ["bard", "cleric", "druid", "paladin", "ranger"],
     "kind": "heal", "heal": "1d8", "slot_scaling": "1d8",
     "description": "触碰一个生物并恢复生命值。施法属性调整值由程序加入。"},
    {"slug": "magic-missile", "name": "魔法飞弹", "name_en": "Magic Missile",
     "level": 1, "school": "塑能", "ritual": False,
     "classes": ["sorcerer", "wizard"], "kind": "damage",
     "damage": "3d4+3", "damage_type": "force",
     "slot_scaling": "1d4+1", "description": "首版按单一目标结算全部飞弹。"},
    {"slug": "fireball", "name": "火球术", "name_en": "Fireball",
     "level": 3, "school": "塑能", "ritual": False,
     "classes": ["sorcerer", "wizard"], "kind": "save",
     "save_ability": "DEX", "save_result": "half",
     "damage": "8d6", "damage_type": "fire", "slot_scaling": "1d6",
     "description": "目标进行敏捷豁免，成功时伤害减半。首版逐目标调用。"},
]
