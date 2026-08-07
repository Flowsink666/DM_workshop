"""用户提供的只读法术目录加载、清洗与保守机制解析。"""

from __future__ import annotations

import re
import sqlite3
import os
from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid5

from dm_workshop.errors import NotFoundError, RuleError

SPELL_NAMESPACE = UUID("8ef95f40-01d7-4d64-9147-90ed0e926c50")
REQUIRED_COLUMNS = {
    "id", "level", "name", "school", "classes", "casting_time", "range",
    "components", "duration", "description", "higher_levels",
}

CLASS_LABELS = {
    "吟游诗人": "bard",
    "牧师": "cleric",
    "德鲁伊": "druid",
    "圣武士": "paladin",
    "游侠": "ranger",
    "术士": "sorcerer",
    "邪术师": "warlock",
    "法师": "wizard",
}
CLASS_NAMES_ZH = {value: key for key, value in CLASS_LABELS.items()}
SCHOOLS = {"塑能", "变化", "咒法", "附魔", "预言", "防护", "死灵", "幻术"}
LEVEL_WORDS = {"戏法": 0, **{str(level): level for level in range(1, 10)}}

ABILITY_LABELS = {
    "力量": "STR", "敏捷": "DEX", "体质": "CON",
    "智力": "INT", "感知": "WIS", "魅力": "CHA",
}
DAMAGE_LABELS = {
    "强酸": "acid", "钝击": "bludgeoning", "寒冷": "cold",
    "火焰": "fire", "力场": "force", "闪电": "lightning",
    "黯蚀": "necrotic", "暗蚀": "necrotic", "穿刺": "piercing",
    "毒素": "poison", "毒性": "poison", "心灵": "psychic",
    "光耀": "radiant", "挥砍": "slashing", "雷鸣": "thunder",
    "雷电": "thunder",
}

_DICE = r"\d+d\d+(?:\s*[+-]\s*\d+)?"
_SAVE_RE = re.compile(r"(力量|敏捷|体质|智力|感知|魅力)豁免")
_DAMAGE_RE = re.compile(
    rf"(?P<dice>{_DICE})\s*点?\s*(?P<type>"
    + "|".join(sorted(DAMAGE_LABELS, key=len, reverse=True))
    + r")?\s*伤害"
)
_HEAL_RE = re.compile(rf"(?:恢复|回复)\s*(?P<dice>{_DICE})\s*点?(?:生命值)?")
_SCALING_RE = re.compile(
    rf"每(?:使用比.+?高|提升|升高|高于).{{0,12}}?[一1]环.{{0,20}}?"
    rf"(?:增加|额外造成|额外恢复)\s*(?P<dice>{_DICE})"
)


def normalize_spell_name(value: str) -> str:
    """生成用于去重和稳定 ID 的名称，不改变对外展示文本。"""
    return "".join(str(value).strip().casefold().split())


def stable_spell_id(name: str) -> str:
    return str(uuid5(SPELL_NAMESPACE, f"user-spells-db:{normalize_spell_name(name)}"))


def parse_class_metadata(value: str) -> dict:
    """从质量不稳定的 classes 列中提取环位、学派、仪式和职业。"""
    tokens = str(value or "").replace("（仪式）", " 仪式 ").split()
    result = {"level": None, "school": "", "ritual": False, "classes": []}
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in LEVEL_WORDS:
            result["level"] = LEVEL_WORDS[token]
            if token != "戏法" and index + 1 < len(tokens) and tokens[index + 1] == "环":
                index += 2
                continue
        elif token in SCHOOLS:
            result["school"] = token
        elif token == "仪式":
            result["ritual"] = True
        elif token in CLASS_LABELS:
            result["classes"].append(CLASS_LABELS[token])
        index += 1
    return result


def parse_resolution(description: str, higher_levels: str = "") -> dict:
    """只提取能够无歧义单目标结算的机制，其他效果安全降级。"""
    text = str(description or "")
    saves = set(_SAVE_RE.findall(text))
    damage_matches = list(_DAMAGE_RE.finditer(text))
    heal_matches = list(_HEAL_RE.finditer(text))
    attack = "法术攻击" in text
    reasons: list[str] = []
    complex_patterns = {
        r"(?:持续时间内|后续回合|每个回合|每轮|再次使用|附赠动作)":
            "效果会在后续回合持续或重复触发",
        r"(?:每个生物|所有生物|至多.{0,8}(?:生物|目标)|多个目标|分别进行)":
            "效果涉及多个目标",
        r"(?:召唤|创造一个生物|变形为|控制一个生物)":
            "效果会创建或长期控制实体",
    }
    for pattern, reason in complex_patterns.items():
        if re.search(pattern, text):
            reasons.append(reason)

    damage_values = {
        (match.group("dice").replace(" ", ""), match.group("type") or "")
        for match in damage_matches
    }
    heal_values = {match.group("dice").replace(" ", "") for match in heal_matches}
    if len(saves) > 1:
        reasons.append("描述包含多个豁免属性")
    if len(damage_values) > 1:
        reasons.append("描述包含多个不同伤害表达式")
    if len(heal_values) > 1:
        reasons.append("描述包含多个不同治疗表达式")
    if damage_values and heal_values:
        reasons.append("描述同时包含伤害与治疗")
    if attack and saves:
        reasons.append("描述同时包含法术攻击与豁免")

    save_result = None
    if saves:
        if re.search(r"(?:豁免)?成功.{0,18}(?:一半|减半)", text):
            save_result = "half"
        elif re.search(r"(?:豁免)?成功.{0,18}(?:不受|不会受到|免受).{0,10}伤害", text):
            save_result = "none"
        else:
            reasons.append("无法确认豁免成功后的伤害规则")

    result = {
        "mode": "manual",
        "kind": "utility",
        "damage": None,
        "damage_type": None,
        "heal": None,
        "save_ability": None,
        "save_result": None,
        "slot_scaling": None,
        "confidence": "manual",
        "reasons": reasons,
    }
    if len(damage_values) == 1:
        dice, damage_label = next(iter(damage_values))
        if not damage_label:
            reasons.append("无法确认伤害类型")
        else:
            result["damage"] = dice
            result["damage_type"] = DAMAGE_LABELS[damage_label]
    if len(heal_values) == 1:
        result["heal"] = next(iter(heal_values))
    if len(saves) == 1:
        result["save_ability"] = ABILITY_LABELS[next(iter(saves))]
        result["save_result"] = save_result

    scaling = _SCALING_RE.search(str(higher_levels or ""))
    if scaling:
        value = scaling.group("dice").replace(" ", "")
        result["slot_scaling"] = value if value.startswith(("+", "-")) else "+" + value

    if not reasons and result["damage"] and attack:
        result.update(mode="automatic", kind="attack", confidence="high")
    elif (not reasons and result["damage"] and result["save_ability"]
          and result["save_result"]):
        result.update(mode="automatic", kind="save", confidence="high")
    elif not reasons and result["heal"] and not damage_values:
        result.update(mode="automatic", kind="heal", confidence="high")
    elif not damage_values and not heal_values:
        result["reasons"].append("没有可自动结算的单一骰子效果")

    return result


class ExternalSpellCatalog:
    """延迟加载外部 SQLite；连接只读且在每次加载后立即关闭。"""

    def __init__(self, path: str | Path | None = None) -> None:
        default = Path(__file__).resolve().parents[1] / "spells.db"
        configured = path or os.getenv("DM_WORKSHOP_SPELLS_DB")
        self.path = Path(configured) if configured else default
        self._stamp: tuple[int, int] | None = None
        self._spells: dict[str, dict] = {}
        self._status: dict = {}

    def status(self) -> dict:
        self._ensure_loaded()
        return deepcopy(self._status)

    def get(self, spell_id: str) -> dict:
        self._ensure_loaded()
        try:
            return deepcopy(self._spells[spell_id])
        except KeyError as exc:
            raise NotFoundError(f"外部目录中找不到法术: {spell_id}") from exc

    def search(self, query: str = "", *, level: int | None = None,
               school: str | None = None, caster_class: str | None = None,
               ritual: bool | None = None) -> list[dict]:
        self._ensure_loaded()
        needle = normalize_spell_name(query)
        class_id = CLASS_LABELS.get(str(caster_class), str(caster_class or "").casefold())
        result = []
        for spell in self._spells.values():
            if needle and needle not in normalize_spell_name(spell["name"]):
                continue
            if level is not None and spell["level"] != int(level):
                continue
            if school and spell["school"] != school:
                continue
            if class_id and class_id not in spell["classes"]:
                continue
            if ritual is not None and spell["ritual"] is not bool(ritual):
                continue
            result.append(deepcopy(spell))
        return sorted(result, key=lambda value: (value["level"], value["name"]))

    def _ensure_loaded(self) -> None:
        try:
            stat = self.path.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
        except OSError as exc:
            self._spells = {}
            self._stamp = None
            self._status = {
                "available": False, "path": str(self.path), "raw_rows": 0,
                "unique_spells": 0, "warnings": [f"无法读取外部法术库: {exc}"],
            }
            return
        if stamp == self._stamp and self._status.get("available"):
            return
        try:
            spells, raw_rows, warnings = self._load()
        except (OSError, sqlite3.Error, RuleError) as exc:
            self._spells = {}
            self._stamp = stamp
            self._status = {
                "available": False, "path": str(self.path), "raw_rows": 0,
                "unique_spells": 0, "warnings": [f"外部法术库无效: {exc}"],
            }
            return
        self._spells = {spell["id"]: spell for spell in spells}
        self._stamp = stamp
        self._status = {
            "available": True, "path": str(self.path), "raw_rows": raw_rows,
            "unique_spells": len(spells), "warnings": warnings,
        }

    def _load(self) -> tuple[list[dict], int, list[str]]:
        connection = sqlite3.connect(f"file:{self.path.resolve()}?mode=ro", uri=True)
        try:
            columns = {
                row[1] for row in connection.execute('PRAGMA table_info("spells")')
            }
            missing = REQUIRED_COLUMNS - columns
            if missing:
                raise RuleError(f"spells 表缺少字段: {sorted(missing)}")
            rows = connection.execute(
                'SELECT id, level, name, school, classes, casting_time, "range", '
                'components, duration, description, higher_levels '
                'FROM spells ORDER BY id'
            ).fetchall()
        finally:
            connection.close()

        spells: list[dict] = []
        seen: set[str] = set()
        title_rows = 0
        duplicate_rows = 0
        invalid_rows = 0
        for row in rows:
            (row_id, raw_level, name, raw_school, raw_classes, casting_time,
             range_value, components, duration, description, higher_levels) = row
            name = str(name or "").strip()
            if not name or name.startswith("#"):
                title_rows += 1
                continue
            key = normalize_spell_name(name)
            if key in seen:
                duplicate_rows += 1
                continue
            seen.add(key)
            metadata = parse_class_metadata(raw_classes or "")
            level = metadata["level"] if metadata["level"] is not None else int(raw_level or 0)
            school = metadata["school"] or str(raw_school or "").strip()
            if not 0 <= level <= 9 or school not in SCHOOLS or not metadata["classes"]:
                invalid_rows += 1
                continue
            description = str(description or "").replace("\\n", "\n").strip()
            higher_levels = str(higher_levels or "").replace("\\n", "\n").strip()
            resolution = parse_resolution(description, higher_levels)
            spell = {
                "id": stable_spell_id(name), "slug": None, "name": name,
                "name_en": "", "aliases": [], "level": level,
                "school": school, "ritual": metadata["ritual"],
                "classes": metadata["classes"],
                "class_labels": [CLASS_NAMES_ZH[value] for value in metadata["classes"]],
                "casting_time": str(casting_time or "").strip(),
                "range": str(range_value or "").strip(),
                "components": str(components or "").strip(),
                "duration": str(duration or "").strip(),
                "concentration": "专注" in str(duration or ""),
                "description": description, "higher_levels": higher_levels,
                "source": "user-provided spells.db (license unverified)",
                "source_row_id": int(row_id), "resolution": resolution,
                "kind": resolution["kind"], "damage": resolution["damage"],
                "damage_type": resolution["damage_type"],
                "heal": resolution["heal"],
                "save_ability": resolution["save_ability"],
                "save_result": resolution["save_result"],
                "slot_scaling": resolution["slot_scaling"],
                "manual_resolution_required": resolution["mode"] != "automatic",
            }
            if spell["concentration"] and resolution["mode"] == "automatic":
                resolution["mode"] = "manual"
                resolution["kind"] = "utility"
                resolution["confidence"] = "manual"
                resolution["reasons"].append("专注法术可能包含持续或重复效果")
                spell["kind"] = "utility"
                spell["manual_resolution_required"] = True
            spells.append(spell)
        warnings = [
            f"过滤标题行 {title_rows} 条",
            f"按名称去除重复行 {duplicate_rows} 条",
        ]
        if invalid_rows:
            warnings.append(f"跳过无法解析的行 {invalid_rows} 条")
        return spells, len(rows), warnings
