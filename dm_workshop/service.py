"""MCP 与 Web 共用的应用服务层。

所有战役修改都通过 ``CampaignStore.mutate`` 原子更新内存草稿；只有显式保存
才会把完整快照写入 SQLite。
"""

from __future__ import annotations

import random
import math
from copy import deepcopy
from typing import Any

from dm_workshop.catalog import STARTER_ITEMS, STARTER_SPELLS
from dm_workshop.actor_presets import get_preset, list_presets
from dm_workshop.dice import roll, roll_d20
from dm_workshop.errors import NotFoundError, RuleError, UnsupportedFeatureError
from dm_workshop.spell_catalog import ExternalSpellCatalog, normalize_spell_name
from dm_workshop.spell_rules import (
    CASTING_ABILITIES, CLASS_NAMES_ZH, KNOWN_CASTERS,
    PREPARED_CASTERS, RITUAL_CASTERS, max_spell_level,
    multiclass_requirement_failures, normalize_class_levels,
    normalize_class_name, rebuild_spellcasting, spell_capacity,
    spellcasting_summary,
)
from dm_workshop.state import (
    CONDITIONS, EQUIPMENT_SLOTS, ability_mod, carrying_capacity_lb, new_actor,
    CURRENCY_ITEM_ID, new_id,
)
from dm_workshop.store import CampaignStore

DAMAGE_TYPES = {
    "acid", "bludgeoning", "cold", "fire", "force", "lightning",
    "necrotic", "piercing", "poison", "psychic", "radiant", "slashing",
    "thunder",
}


class WorkshopService:
    """集中实现角色、背包、交易和战斗规则，适配层只负责参数转发。"""

    def __init__(self, store: CampaignStore, *,
                 rng: random.Random | None = None,
                 spell_catalog: ExternalSpellCatalog | None = None) -> None:
        self.store = store
        self.rng = rng or random.SystemRandom()
        self.spell_catalog = spell_catalog or ExternalSpellCatalog()

    def create_campaign(self, name: str, *, seed_srd: bool = True,
                        preset_characters: list[dict] | None = None) -> dict:
        if preset_characters is not None:
            if not isinstance(preset_characters, list) or not preset_characters:
                raise RuleError("至少选择一个预设角色")
            validated = []
            for entry in preset_characters:
                if not isinstance(entry, dict):
                    raise RuleError("preset_characters 必须是对象列表")
                preset_id = str(entry.get("preset_id", "")).strip()
                name_value = str(entry.get("name", "")).strip()
                try:
                    get_preset(preset_id)
                except KeyError as exc:
                    raise RuleError(f"未知角色预设: {preset_id}") from exc
                if not name_value:
                    raise RuleError("预设角色名称不能为空")
                validated.append({"preset_id": preset_id, "name": name_value})
        state = self.store.create_campaign(name)
        if seed_srd:
            self.seed_catalog(state["id"])
            state = self.store.get(state["id"])
        if preset_characters is not None:
            try:
                self._initialize_preset_characters(state["id"], validated)
                state = self.store.get(state["id"])
            except Exception:
                try:
                    self.store.discard_campaign_changes(state["id"])
                except Exception:
                    pass
                raise
        return state

    def list_actor_presets(self) -> list[dict]:
        result = []
        for preset in list_presets():
            con_mod = (preset["abilities"]["CON"] - 10) // 2
            hp = preset["hit_die"] + con_mod
            if preset["preset_id"] == "barbarian":
                ac = 10 + (preset["abilities"]["DEX"] - 10) // 2 + con_mod
            elif preset["preset_id"] == "monk":
                ac = 10 + (preset["abilities"]["DEX"] - 10) // 2 + (preset["abilities"]["WIS"] - 10) // 2
            else:
                dex = (preset["abilities"]["DEX"] - 10) // 2
                slugs = {slug for slug, _ in preset["equipment"]}
                if "chain-mail" in slugs:
                    ac = 16
                elif "scale-mail" in slugs:
                    ac = 14 + min(2, dex)
                elif "leather-armor" in slugs:
                    ac = 11 + dex
                else:
                    ac = 10 + dex
                if "shield" in slugs:
                    ac += 2
            result.append({"preset_id": preset["preset_id"], "class": preset["class"],
                           "class_name": preset["class_name"], "name": "",
                           "abilities": preset["abilities"], "hp": hp, "ac": ac,
                           "equipment": preset["equipment"], "spells": preset["spells"]})
        return result

    def _initialize_preset_characters(self, campaign_id: str,
                                      selections: list[dict]) -> None:
        def change(state: dict) -> dict:
            item_by_slug = {item.get("slug"): item for item in state["items"].values()}
            spell_by_slug = {spell.get("slug"): spell for spell in state["spells"].values()}
            created = []
            for selection in selections:
                preset = get_preset(selection["preset_id"])
                missing_items = [slug for slug, _ in preset["equipment"] if slug not in item_by_slug]
                missing_spells = [slug for values in preset["spells"].values() for slug in values if slug not in spell_by_slug]
                if missing_items or missing_spells:
                    raise RuleError("预设目录缺少装备或法术: " + ", ".join(missing_items + missing_spells))
                abilities = preset["abilities"]
                con_mod = (abilities["CON"] - 10) // 2
                ac = 10 + (abilities["DEX"] - 10) // 2
                if preset["preset_id"] == "barbarian":
                    ac = 10 + (abilities["DEX"] - 10) // 2 + con_mod
                elif preset["preset_id"] == "monk":
                    ac = 10 + (abilities["DEX"] - 10) // 2 + (abilities["WIS"] - 10) // 2
                actor = new_actor(selection["name"], level=1,
                                  max_hp=preset["hit_die"] + con_mod, ac=ac,
                                  abilities=abilities)
                actor["preset_id"] = preset["preset_id"]
                actor["skill_proficiencies"] = list(preset["skill_proficiencies"])
                actor["saving_throw_proficiencies"] = list(preset["saving_throw_proficiencies"])
                actor["class_levels"] = {preset["class"]: 1}
                rebuild_spellcasting(actor)
                stacks_by_slug = {}
                for slug, quantity in preset["equipment"]:
                    item = item_by_slug[slug]
                    stack_quantities = [1] * quantity if not item.get("stackable") else [quantity]
                    for stack_quantity in stack_quantities:
                        stack = {"id": new_id(), "item_id": item["id"], "quantity": stack_quantity,
                                 "container_id": None, "equipped_slot": None, "notes": ""}
                        actor["inventory"][stack["id"]] = stack
                        stacks_by_slug.setdefault(slug, stack)
                for slug, slot in (("greataxe", "main_hand"), ("rapier", "main_hand"), ("longsword", "main_hand"),
                                   ("shortsword", "main_hand"), ("scimitar", "main_hand"), ("quarterstaff", "main_hand"),
                                   ("longbow", "main_hand"), ("shortbow", "main_hand"), ("mace", "main_hand"),
                                   ("shield", "shield"), ("leather-armor", "armor"), ("scale-mail", "armor"), ("chain-mail", "armor")):
                    if slug in stacks_by_slug:
                        stacks_by_slug[slug]["equipped_slot"] = slot
                self._recalculate_ac(state, actor)
                castable_slugs = []
                for key, values in preset["spells"].items():
                    if key != "spellbook":
                        castable_slugs.extend(values)
                actor["spells"] = list(dict.fromkeys(
                    spell_by_slug[slug]["id"] for slug in castable_slugs
                ))
                for key, values in preset["spells"].items():
                    mode = "spellbook" if key == "spellbook" else ("prepared" if key == "prepared" else "known")
                    for slug in values:
                        spell = spell_by_slug[slug]
                        repertoire_key = f"{spell['id']}:{preset['class']}"
                        existing = actor["spell_repertoire"].get(repertoire_key)
                        if existing is not None and key == "prepared":
                            existing["prepared"] = True
                            continue
                        actor["spell_repertoire"][repertoire_key] = {
                            "spell_id": spell["id"], "source_class": preset["class"],
                            "mode": mode, "prepared": mode == "prepared",
                            "spell_level": int(spell.get("level", 0)), "override_reason": None,
                        }
                state["actors"][actor["id"]] = actor
                created.append(actor["id"])
            return {"actor_ids": created}
        self.store.mutate(campaign_id, "initialize_preset_characters", {"count": len(selections)}, change, source="system")

    def list_campaigns(self) -> list[dict]:
        return self.store.list_campaigns()

    def get_campaign(self, campaign_id: str) -> dict:
        return self.store.get(campaign_id)

    def seed_catalog(self, campaign_id: str, *, source: str = "system") -> dict:
        def change(state: dict) -> dict:
            added = 0
            existing_slugs = {i.get("slug") for i in state["items"].values()}
            for definition in STARTER_ITEMS:
                if definition["slug"] in existing_slugs:
                    continue
                item = deepcopy(definition)
                item["id"] = new_id()
                item["aliases"] = [item["name_en"]]
                item["source"] = "SRD 5.1 / CC BY 4.0"
                state["items"][item["id"]] = item
                added += 1
            spells_added = 0
            existing_spell_slugs = {
                spell.get("slug") for spell in state["spells"].values()
            }
            for definition in STARTER_SPELLS:
                if definition["slug"] in existing_spell_slugs:
                    continue
                spell = deepcopy(definition)
                spell["id"] = new_id()
                spell["aliases"] = [spell["name_en"]]
                spell["source"] = "SRD 5.1 / CC BY 4.0"
                state["spells"][spell["id"]] = spell
                spells_added += 1
            return {"items_added": added, "spells_added": spells_added}
        return self.store.mutate(campaign_id, "seed_catalog", {}, change,
                                 source=source)

    def create_actor(self, campaign_id: str, name: str, *, kind: str = "pc",
                     level: int = 1, max_hp: int = 10, ac: int = 10,
                     abilities: dict[str, int] | None = None,
                     source: str = "mcp") -> dict:
        if kind not in {"pc", "npc", "monster"}:
            raise RuleError("kind 必须是 pc、npc 或 monster")
        actor = new_actor(name.strip(), kind=kind, level=int(level),
                          max_hp=int(max_hp), ac=int(ac), abilities=abilities)
        self._validate_actor(actor)

        def change(state: dict) -> dict:
            state["actors"][actor["id"]] = actor
            return {"actor": actor}
        return self.store.mutate(campaign_id, "create_actor", actor, change,
                                 source=source)

    def update_actor(self, campaign_id: str, actor_id: str, changes: dict,
                     *, source: str = "mcp") -> dict:
        allowed = {
            "name", "aliases", "level", "xp", "abilities", "max_hp", "hp",
            "temp_hp", "ac", "speed", "proficiency_bonus",
            "resistances", "vulnerabilities", "immunities",
            "skill_proficiencies", "saving_throw_proficiencies", "spell_slots",
            "spellcasting_ability", "spells", "resources",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise RuleError(f"不可直接修改字段: {sorted(unknown)}")

        def change(state: dict) -> dict:
            actor = self._actor(state, actor_id)
            protected = {
                "level", "proficiency_bonus", "spell_slots",
                "spellcasting_ability", "spells",
            }
            if actor.get("class_levels") and protected & set(changes):
                raise RuleError(
                    "启用职业模型后，等级、熟练加值和法术资源必须使用专用工具修改"
                )
            normalized = deepcopy(changes)
            # 属性更新采用合并语义，防止只修改 STR 时意外删除其余五项属性。
            if "abilities" in normalized:
                actor["abilities"].update({
                    str(key).upper(): int(value)
                    for key, value in normalized.pop("abilities").items()
                })
            actor.update(normalized)
            if "ac" in changes:
                actor["base_ac"] = actor["ac"]
            self._validate_actor(actor)
            failures = multiclass_requirement_failures(
                actor, actor.get("class_levels", {})
            )
            if failures:
                raise RuleError("属性修改不再满足多职业前提: " + "; ".join(failures))
            for spell_id in actor["spells"]:
                self._spell(state, spell_id)
            # 即使是管理台直接修正 HP，也必须同步生命状态，不能出现 0 HP 清醒者。
            if actor["hp"] == 0 and actor["life_state"] == "conscious":
                if actor["kind"] == "pc":
                    self._knock_unconscious(actor, source="manual_adjustment")
                else:
                    actor["life_state"] = "dead"
            elif actor["hp"] > 0 and actor["life_state"] in {"unconscious", "stable"}:
                self._wake(actor)
            return {"actor": actor}
        return self.store.mutate(campaign_id, "update_actor", changes, change,
                                 source=source)

    def define_item(self, campaign_id: str, name: str, *, kind: str = "gear",
                    weight_lb: float = 0, price_gp: int = 0,
                    stackable: bool = True, aliases: list[str] | None = None,
                    data: dict | None = None, source: str = "mcp") -> dict:
        item = {
            "id": new_id(), "slug": None, "name": name.strip(),
            "name_en": "", "aliases": aliases or [], "kind": kind,
            "weight_lb": float(weight_lb), "price_gp": int(price_gp),
            "stackable": bool(stackable), "source": "custom",
        }
        extension = deepcopy(data or {})
        protected = set(extension) & {
            "id", "slug", "name", "name_en", "aliases", "kind",
            "weight_lb", "price_gp", "stackable", "source",
        }
        if protected:
            raise RuleError(f"data 不能覆盖物品核心字段: {sorted(protected)}")
        item.update(extension)
        if (not item["name"] or not math.isfinite(item["weight_lb"])
                or item["weight_lb"] < 0 or item["price_gp"] < 0):
            raise RuleError("物品名称不能为空，重量和价格不能为负数")
        self._validate_item_definition(item)

        def change(state: dict) -> dict:
            state["items"][item["id"]] = item
            return {"item": item}
        return self.store.mutate(campaign_id, "define_item", item, change,
                                 source=source)

    def search_items(self, campaign_id: str, query: str = "") -> list[dict]:
        state = self.store.get(campaign_id)
        needle = query.casefold().strip()
        result = []
        for item in state["items"].values():
            haystack = [item.get("name", ""), item.get("name_en", ""),
                        *item.get("aliases", [])]
            if not needle or any(needle in str(value).casefold() for value in haystack):
                result.append(item)
        return sorted(result, key=lambda i: i["name"])

    def search_spells(self, campaign_id: str, query: str = "") -> list[dict]:
        state = self.store.get(campaign_id)
        needle = query.casefold().strip()
        result = []
        for spell in state["spells"].values():
            names = [spell.get("name", ""), spell.get("name_en", ""),
                     *spell.get("aliases", [])]
            if not needle or any(needle in str(value).casefold() for value in names):
                result.append(spell)
        return sorted(result, key=lambda s: (s["level"], s["name"]))

    def get_spell_catalog_status(self) -> dict:
        """报告外部目录状态；目录不可用时不影响已有战役法术。"""
        return self.spell_catalog.status()

    def search_spell_catalog(self, campaign_id: str, query: str = "", *,
                             level: int | None = None,
                             school: str | None = None,
                             caster_class: str | None = None,
                             ritual: bool | None = None,
                             limit: int = 20, offset: int = 0) -> dict:
        state = self.store.get(campaign_id)
        limit, offset = int(limit), int(offset)
        if not 1 <= limit <= 100 or offset < 0:
            raise RuleError("limit 必须为 1..100，offset 不能为负")
        class_id = normalize_class_name(caster_class) if caster_class else None
        needle = normalize_spell_name(query)
        merged: dict[str, dict] = {}
        # 已写入战役的结构化法术优先于同名外部文本条目。
        for spell in state["spells"].values():
            if not self._spell_matches(spell, needle, level, school,
                                       class_id, ritual):
                continue
            merged[normalize_spell_name(spell["name"])] = spell
        for spell in self.spell_catalog.search(
                query, level=level, school=school,
                caster_class=class_id, ritual=ritual):
            merged.setdefault(normalize_spell_name(spell["name"]), spell)
        ordered = sorted(merged.values(), key=lambda value: (
            int(value.get("level", 0)), value.get("name", "")
        ))
        page = ordered[offset:offset + limit]
        return {
            "total": len(ordered), "offset": offset, "limit": limit,
            "items": [self._spell_summary(spell) for spell in page],
            "catalog_status": self.spell_catalog.status(),
        }

    def get_spell_details(self, campaign_id: str, spell_id: str) -> dict:
        state = self.store.get(campaign_id)
        if spell_id in state["spells"]:
            return deepcopy(state["spells"][spell_id])
        return self.spell_catalog.get(spell_id)

    def set_actor_classes(self, campaign_id: str, actor_id: str,
                          class_levels: dict[str, int], *,
                          spell_sources: dict[str, str] | None = None,
                          override_reason: str | None = None,
                          source: str = "mcp") -> dict:
        normalized = normalize_class_levels(class_levels)
        assignments = {
            spell_id: normalize_class_name(class_name)
            for spell_id, class_name in (spell_sources or {}).items()
        }
        override_reason = str(override_reason or "").strip() or None

        def change(state: dict) -> dict:
            actor = self._actor(state, actor_id)
            warnings = []
            failures = multiclass_requirement_failures(actor, normalized)
            self._enforce(not failures, "; ".join(failures), override_reason,
                          warnings)
            if actor["spells"] and not actor.get("class_levels"):
                missing = set(actor["spells"]) - set(assignments)
                if missing:
                    raise RuleError(
                        "启用职业模型前必须通过 spell_sources 指定全部旧法术来源: "
                        f"{sorted(missing)}"
                    )
            actor["class_levels"] = deepcopy(normalized)
            for spell_id in actor["spells"]:
                class_id = assignments.get(spell_id)
                if class_id is None:
                    continue
                self._enforce(
                    class_id in normalized,
                    f"旧法术来源职业不属于角色: {class_id}",
                    override_reason, warnings,
                )
                spell = self._spell(state, spell_id)
                self._enforce_spell_class(spell, class_id, override_reason,
                                          warnings)
                actor["spell_repertoire"][self._repertoire_key(
                    spell_id, class_id
                )] = {
                    "spell_id": spell_id,
                    "source_class": class_id, "mode": "legacy_import",
                    "prepared": True, "override_reason": override_reason,
                    "spell_level": int(spell.get("level", 0)),
                }
            rebuild_spellcasting(actor)
            self._validate_repertoire_after_class_change(
                state, actor, override_reason, warnings
            )
            caster_classes = [name for name in normalized if name in CASTING_ABILITIES]
            if len(caster_classes) == 1:
                actor["spellcasting_ability"] = CASTING_ABILITIES[caster_classes[0]]
            self._sync_castable_spells(actor)
            self._validate_actor(actor)
            return {"actor_id": actor_id,
                    "spellcasting": self._actor_spellcasting(actor),
                    "warnings": warnings}

        request = locals_request(
            actor_id=actor_id, class_levels=normalized,
            spell_sources=assignments, override_reason=override_reason,
        )
        return self.store.mutate(campaign_id, "set_actor_classes", request,
                                 change, source=source)

    def get_actor_spellcasting(self, campaign_id: str, actor_id: str) -> dict:
        actor = self._actor(self.store.get(campaign_id), actor_id)
        return self._actor_spellcasting(actor)

    def define_spell(self, campaign_id: str, name: str, level: int, kind: str,
                     *, name_en: str = "", damage: str | None = None,
                     damage_type: str | None = None, heal: str | None = None,
                     save_ability: str | None = None,
                     save_result: str | None = None,
                     slot_scaling: str | None = None, description: str = "",
                     source: str = "mcp") -> dict:
        if kind not in {"attack", "save", "damage", "heal", "utility"}:
            raise RuleError("法术 kind 必须是 attack/save/damage/heal/utility")
        if not 0 <= int(level) <= 9:
            raise RuleError("法术环位必须在 0 到 9 之间")
        if damage_type and damage_type not in DAMAGE_TYPES:
            raise RuleError("未知伤害类型")
        if save_ability and save_ability not in {"STR", "DEX", "CON", "INT", "WIS", "CHA"}:
            raise RuleError("未知豁免属性")
        if save_result and save_result not in {"half", "none"}:
            raise RuleError("豁免成功结果必须是 half 或 none")
        if kind in {"attack", "damage", "save"} and not damage:
            raise RuleError("该类法术必须提供 damage 骰子表达式")
        if kind == "heal" and not heal:
            raise RuleError("治疗法术必须提供 heal 骰子表达式")
        for expression in (damage, heal, slot_scaling):
            if expression:
                roll(expression, rng=random.Random(0))
        spell = {"id": new_id(), "slug": None, "name": name.strip(),
                 "name_en": name_en.strip(), "aliases": [], "level": int(level),
                 "school": "", "ritual": False, "classes": [],
                 "casting_time": "", "range": "", "components": "",
                 "duration": "", "concentration": False,
                 "higher_levels": "",
                 "kind": kind, "damage": damage, "damage_type": damage_type,
                 "heal": heal, "save_ability": save_ability,
                 "save_result": save_result, "slot_scaling": slot_scaling,
                 "description": description, "source": "custom",
                 "manual_resolution_required": kind == "utility",
                 "resolution": {
                     "mode": "manual" if kind == "utility" else "automatic",
                     "kind": kind, "damage": damage,
                     "damage_type": damage_type, "heal": heal,
                     "save_ability": save_ability,
                     "save_result": save_result,
                     "slot_scaling": slot_scaling,
                     "confidence": "manual" if kind == "utility" else "curated",
                     "reasons": ["需要 DM 裁定"] if kind == "utility" else [],
                 }}
        if not spell["name"]:
            raise RuleError("法术名称不能为空")

        def change(state: dict) -> dict:
            state["spells"][spell["id"]] = spell
            return {"spell": spell}
        return self.store.mutate(campaign_id, "define_spell", spell, change,
                                 source=source)

    def learn_spell(self, campaign_id: str, actor_id: str, spell_id: str, *,
                    source_class: str | None = None, prepared: bool = False,
                    remove: bool = False,
                    override_reason: str | None = None,
                    source: str = "mcp") -> dict:
        class_id = normalize_class_name(source_class) if source_class else None
        override_reason = str(override_reason or "").strip() or None

        def change(state: dict) -> dict:
            actor = self._actor(state, actor_id)
            warnings = []
            if remove:
                actor["spells"] = [value for value in actor["spells"]
                                   if value != spell_id]
                for key, entry in list(actor["spell_repertoire"].items()):
                    if (entry.get("spell_id", key) == spell_id
                            and (class_id is None
                                 or entry.get("source_class") == class_id)):
                        del actor["spell_repertoire"][key]
                for arcanum in actor.get("mystic_arcanum", {}).values():
                    if (arcanum.get("spell_id") == spell_id
                            and class_id in {None, "warlock"}):
                        arcanum["spell_id"] = None
                        arcanum["used"] = False
                self._sync_castable_spells(actor)
                return {"actor_id": actor_id, "spells": actor["spells"],
                        "spell_repertoire": actor["spell_repertoire"]}
            spell = self._materialize_spell(state, spell_id)
            if not actor.get("class_levels"):
                if spell_id not in actor["spells"]:
                    actor["spells"].append(spell_id)
                return {"actor_id": actor_id, "spells": actor["spells"],
                        "legacy_mode": True}
            if class_id is None:
                raise RuleError("启用职业模型后必须提供 source_class")
            self._enforce(class_id in actor["class_levels"],
                          f"角色没有 {CLASS_NAMES_ZH[class_id]} 等级",
                          override_reason, warnings)
            self._enforce_spell_class(spell, class_id, override_reason, warnings)
            class_level = actor["class_levels"].get(class_id, 0)
            self._enforce(
                int(spell["level"]) <= max_spell_level(class_id, class_level),
                f"{CLASS_NAMES_ZH[class_id]}当前不能学习 {spell['level']} 环法术",
                override_reason, warnings,
            )
            try:
                mode = self._learning_mode(class_id, spell)
            except RuleError as exc:
                self._enforce(False, str(exc), override_reason, warnings)
                mode = "known"
            if mode == "prepare_only":
                raise RuleError("该职业不学习有环法术，请使用 prepare_spell")
            self._enforce_repertoire_capacity(actor, spell, class_id, mode,
                                               override_reason, warnings)
            entry = {
                "spell_id": spell_id,
                "source_class": class_id, "mode": mode,
                "prepared": bool(prepared), "override_reason": override_reason,
                "spell_level": int(spell["level"]),
            }
            if mode == "arcanum":
                slot = actor["mystic_arcanum"].get(str(spell["level"]))
                self._enforce(slot is not None,
                              "邪术师等级尚未获得该环位的玄奥秘法",
                              override_reason, warnings)
                if slot is not None:
                    self._enforce(
                        not slot.get("spell_id") or slot["spell_id"] == spell_id,
                        f"{spell['level']} 环玄奥秘法已经选择其他法术",
                        override_reason, warnings,
                    )
                    slot["spell_id"] = spell_id
            actor["spell_repertoire"][self._repertoire_key(
                spell_id, class_id
            )] = entry
            if prepared and class_id == "wizard" and int(spell["level"]) > 0:
                self._enforce_prepared_capacity(actor, class_id,
                                                override_reason, warnings)
            self._sync_castable_spells(actor)
            return {"actor_id": actor_id, "spells": actor["spells"],
                    "spell_repertoire": actor["spell_repertoire"],
                    "warnings": warnings}

        return self.store.mutate(campaign_id, "learn_spell", locals_request(
            actor_id=actor_id, spell_id=spell_id, source_class=class_id,
            prepared=prepared, remove=remove,
            override_reason=override_reason), change,
            source=source)

    def prepare_spell(self, campaign_id: str, actor_id: str, spell_id: str,
                      source_class: str, *, prepared: bool = True,
                      override_reason: str | None = None,
                      source: str = "mcp") -> dict:
        class_id = normalize_class_name(source_class)
        override_reason = str(override_reason or "").strip() or None

        def change(state: dict) -> dict:
            actor = self._actor(state, actor_id)
            warnings = []
            self._enforce(bool(actor.get("class_levels")),
                          "旧角色必须先配置职业等级", override_reason, warnings)
            self._enforce(class_id in PREPARED_CASTERS,
                          f"{CLASS_NAMES_ZH[class_id]}不使用准备法术规则",
                          override_reason, warnings)
            self._enforce(class_id in actor["class_levels"],
                          f"角色没有 {CLASS_NAMES_ZH[class_id]} 等级",
                          override_reason, warnings)
            spell = self._materialize_spell(state, spell_id)
            self._enforce(int(spell["level"]) > 0,
                          "戏法应通过 learn_spell 管理，不能每日准备",
                          override_reason, warnings)
            self._enforce_spell_class(spell, class_id, override_reason, warnings)
            self._enforce(
                int(spell["level"]) <= max_spell_level(
                    class_id, actor["class_levels"].get(class_id, 0)
                ),
                f"{CLASS_NAMES_ZH[class_id]}当前不能准备 {spell['level']} 环法术",
                override_reason, warnings,
            )
            repertoire_key = self._repertoire_key(spell_id, class_id)
            entry = actor["spell_repertoire"].get(repertoire_key)
            if class_id == "wizard" and entry is None:
                self._enforce(False, "法师只能准备已写入法术书的法术",
                              override_reason, warnings)
            if entry is None:
                entry = {"spell_id": spell_id,
                         "source_class": class_id, "mode": "prepared",
                         "prepared": False, "override_reason": override_reason,
                         "spell_level": int(spell["level"])}
                actor["spell_repertoire"][repertoire_key] = entry
            self._enforce(entry["source_class"] == class_id,
                          "法术来源职业与准备职业不一致",
                          override_reason, warnings)
            entry["prepared"] = bool(prepared)
            if prepared:
                self._enforce_prepared_capacity(actor, class_id,
                                                override_reason, warnings)
            self._sync_castable_spells(actor)
            return {"actor_id": actor_id, "spell_id": spell_id,
                    "prepared": bool(prepared), "spells": actor["spells"],
                    "warnings": warnings}

        request = locals_request(
            actor_id=actor_id, spell_id=spell_id, source_class=class_id,
            prepared=prepared, override_reason=override_reason,
        )
        return self.store.mutate(campaign_id, "prepare_spell", request,
                                 change, source=source)

    def add_item(self, campaign_id: str, owner_id: str, item_id: str,
                 quantity: int = 1, *, container_id: str | None = None,
                 notes: str = "", source: str = "mcp") -> dict:
        quantity = int(quantity)
        if quantity <= 0:
            raise RuleError("数量必须大于零")

        def change(state: dict) -> dict:
            item = self._item(state, item_id)
            if item_id == CURRENCY_ITEM_ID and owner_id != "party":
                raise RuleError("金币只能存放在队伍共享仓库")
            inventory = self._inventory(state, owner_id)
            if container_id and container_id not in inventory:
                raise NotFoundError(f"找不到容器物品栈: {container_id}")
            if container_id:
                container_stack = inventory[container_id]
                container_item = self._item(state, container_stack["item_id"])
                if "container" not in container_item:
                    raise RuleError("目标物品不是容器")
            if item.get("stackable"):
                for stack in inventory.values():
                    if (stack["item_id"] == item_id
                            and stack.get("container_id") == container_id
                            and stack.get("notes", "") == notes
                            and not stack.get("equipped_slot")):
                        stack["quantity"] += quantity
                        self._assert_capacity(state, owner_id)
                        return {"stack": stack}
            stack = {"id": new_id(), "item_id": item_id, "quantity": quantity,
                     "container_id": container_id, "equipped_slot": None,
                     "notes": notes}
            inventory[stack["id"]] = stack
            self._assert_capacity(state, owner_id)
            return {"stack": stack}
        return self.store.mutate(campaign_id, "add_item", locals_request(
            owner_id=owner_id, item_id=item_id, quantity=quantity,
            container_id=container_id), change, source=source)

    def remove_item(self, campaign_id: str, owner_id: str, stack_id: str,
                    quantity: int = 1, *, source: str = "mcp") -> dict:
        quantity = int(quantity)
        if quantity <= 0:
            raise RuleError("数量必须大于零")

        def change(state: dict) -> dict:
            inventory = self._inventory(state, owner_id)
            stack = self._stack(inventory, stack_id)
            if stack["quantity"] < quantity:
                raise RuleError("物品数量不足")
            stack["quantity"] -= quantity
            remaining = stack["quantity"]
            if remaining == 0:
                if any(s.get("container_id") == stack_id for s in inventory.values()):
                    raise RuleError("容器非空，不能移除")
                del inventory[stack_id]
            return {"stack_id": stack_id, "remaining": remaining}
        return self.store.mutate(campaign_id, "remove_item", locals_request(
            owner_id=owner_id, stack_id=stack_id, quantity=quantity), change,
            source=source)

    def transfer_item(self, campaign_id: str, from_owner_id: str,
                      to_owner_id: str, stack_id: str, quantity: int = 1, *,
                      source: str = "mcp") -> dict:
        quantity = int(quantity)
        if quantity <= 0 or from_owner_id == to_owner_id:
            raise RuleError("转移数量必须为正，来源和目标必须不同")

        def change(state: dict) -> dict:
            source_inv = self._inventory(state, from_owner_id)
            target_inv = self._inventory(state, to_owner_id)
            stack = self._stack(source_inv, stack_id)
            if stack["quantity"] < quantity:
                raise RuleError("物品数量不足")
            if stack.get("equipped_slot"):
                raise RuleError("请先卸下物品再转移")
            if any(child.get("container_id") == stack_id
                   for child in source_inv.values()):
                raise RuleError("非空容器不能直接转移，请先取出其中物品")
            item_id = stack["item_id"]
            if item_id == CURRENCY_ITEM_ID and to_owner_id != "party":
                raise RuleError("金币只能存放在队伍共享仓库")
            stack["quantity"] -= quantity
            if stack["quantity"] == 0:
                del source_inv[stack_id]
            new_stack = {"id": new_id(), "item_id": item_id,
                         "quantity": quantity, "container_id": None,
                         "equipped_slot": None, "notes": stack.get("notes", "")}
            target_inv[new_stack["id"]] = new_stack
            self._merge_stack(state, target_inv, new_stack)
            self._assert_capacity(state, to_owner_id)
            return {"from": from_owner_id, "to": to_owner_id,
                    "item_id": item_id, "quantity": quantity}
        request = locals_request(from_owner_id=from_owner_id,
                                 to_owner_id=to_owner_id, stack_id=stack_id,
                                 quantity=quantity)
        return self.store.mutate(campaign_id, "transfer_item", request, change,
                                 source=source)

    def equip_item(self, campaign_id: str, actor_id: str, stack_id: str,
                   slot: str, *, source: str = "mcp") -> dict:
        if slot not in EQUIPMENT_SLOTS:
            raise RuleError(f"未知装备栏: {slot}")

        def change(state: dict) -> dict:
            actor = self._actor(state, actor_id)
            stack = self._stack(actor["inventory"], stack_id)
            if stack["quantity"] != 1:
                raise RuleError("可装备物品必须是单件物品栈")
            item = self._item(state, stack["item_id"])
            if item.get("weapon"):
                if slot not in {"main_hand", "off_hand"}:
                    raise RuleError("武器只能装备到主手或副手")
            elif item.get("armor"):
                required_slot = item["armor"].get("slot")
                if slot != required_slot:
                    raise RuleError(f"该护甲只能装备到 {required_slot}")
            elif slot not in item.get("equipment_slots", []):
                raise RuleError("该物品不能装备到指定栏位")
            for other in actor["inventory"].values():
                if other.get("equipped_slot") == slot:
                    other["equipped_slot"] = None
            stack["equipped_slot"] = slot
            self._recalculate_ac(state, actor)
            return {"stack": stack, "ac": actor["ac"]}
        return self.store.mutate(campaign_id, "equip_item", locals_request(
            actor_id=actor_id, stack_id=stack_id, slot=slot), change,
            source=source)

    def unequip_item(self, campaign_id: str, actor_id: str, stack_id: str, *,
                     source: str = "mcp") -> dict:
        def change(state: dict) -> dict:
            actor = self._actor(state, actor_id)
            stack = self._stack(actor["inventory"], stack_id)
            stack["equipped_slot"] = None
            self._recalculate_ac(state, actor)
            return {"stack": stack, "ac": actor["ac"]}
        return self.store.mutate(campaign_id, "unequip_item", locals_request(
            actor_id=actor_id, stack_id=stack_id), change, source=source)

    def _legacy_create_shop(self, campaign_id: str, name: str, *,
                    buy_multiplier: float = 1.0, sell_multiplier: float = 0.5,
                    wallet_gp: int = 100_000, source: str = "mcp") -> dict:
        shop = {"id": new_id(), "name": name.strip(), "stock": {},
                "buy_multiplier": float(buy_multiplier),
                "sell_multiplier": float(sell_multiplier),
                "wallet_gp": int(wallet_gp)}
        if (not shop["name"] or not math.isfinite(float(buy_multiplier))
                or not math.isfinite(float(sell_multiplier))
                or min(buy_multiplier, sell_multiplier) < 0
                or int(wallet_gp) < 0):
            raise RuleError("商店名称不能为空，价格倍率不能为负")

        def change(state: dict) -> dict:
            state["shops"][shop["id"]] = shop
            return {"shop": shop}
        return self.store.mutate(campaign_id, "create_shop", shop, change,
                                 source=source)

    def _legacy_stock_shop(self, campaign_id: str, shop_id: str, item_id: str,
                   quantity: int | None, *, source: str = "mcp") -> dict:
        if quantity is not None and int(quantity) < 0:
            raise RuleError("库存不能为负；null 表示无限库存")

        def change(state: dict) -> dict:
            self._item(state, item_id)
            shop = self._shop(state, shop_id)
            shop["stock"][item_id] = None if quantity is None else int(quantity)
            return {"shop_id": shop_id, "item_id": item_id,
                    "quantity": shop["stock"][item_id]}
        return self.store.mutate(campaign_id, "stock_shop", locals_request(
            shop_id=shop_id, item_id=item_id, quantity=quantity), change,
            source=source)

    def _legacy_buy_item(self, campaign_id: str, shop_id: str, actor_id: str,
                 item_id: str, quantity: int = 1, *, source: str = "mcp") -> dict:
        quantity = int(quantity)
        if quantity <= 0:
            raise RuleError("数量必须大于零")

        def change(state: dict) -> dict:
            actor = self._actor(state, actor_id)
            shop = self._shop(state, shop_id)
            item = self._item(state, item_id)
            if item_id not in shop["stock"]:
                raise RuleError("商店没有该物品")
            stock = shop["stock"][item_id]
            if stock is not None and stock < quantity:
                raise RuleError("商店库存不足")
            price = round(item["price_gp"] * shop["buy_multiplier"]) * quantity
            if actor["wallet_gp"] < price:
                raise RuleError("角色货币不足")
            actor["wallet_gp"] -= price
            shop["wallet_gp"] += price
            if stock is not None:
                shop["stock"][item_id] -= quantity
            stack = {"id": new_id(), "item_id": item_id, "quantity": quantity,
                     "container_id": None, "equipped_slot": None, "notes": ""}
            actor["inventory"][stack["id"]] = stack
            self._merge_stack(state, actor["inventory"], stack)
            self._assert_capacity(state, actor_id)
            return {"item_id": item_id, "quantity": quantity,
                    "paid_gp": price, "wallet_gp": actor["wallet_gp"]}
        request = locals_request(shop_id=shop_id, actor_id=actor_id,
                                 item_id=item_id, quantity=quantity)
        return self.store.mutate(campaign_id, "buy_item", request, change,
                                 source=source)

    def _legacy_sell_item(self, campaign_id: str, shop_id: str, actor_id: str,
                  stack_id: str, quantity: int = 1, *, source: str = "mcp") -> dict:
        quantity = int(quantity)
        if quantity <= 0:
            raise RuleError("数量必须大于零")

        def change(state: dict) -> dict:
            actor = self._actor(state, actor_id)
            shop = self._shop(state, shop_id)
            stack = self._stack(actor["inventory"], stack_id)
            if stack.get("equipped_slot"):
                raise RuleError("请先卸下物品再出售")
            if any(child.get("container_id") == stack_id
                   for child in actor["inventory"].values()):
                raise RuleError("非空容器不能出售，请先取出其中物品")
            if stack["quantity"] < quantity:
                raise RuleError("物品数量不足")
            item = self._item(state, stack["item_id"])
            price = round(item["price_gp"] * shop["sell_multiplier"]) * quantity
            if shop["wallet_gp"] < price:
                raise RuleError("商店货币不足")
            stack["quantity"] -= quantity
            if stack["quantity"] == 0:
                del actor["inventory"][stack_id]
            actor["wallet_gp"] += price
            shop["wallet_gp"] -= price
            current = shop["stock"].get(item["id"], 0)
            if current is not None:
                shop["stock"][item["id"]] = current + quantity
            return {"item_id": item["id"], "quantity": quantity,
                    "received_gp": price, "wallet_gp": actor["wallet_gp"]}
        request = locals_request(shop_id=shop_id, actor_id=actor_id,
                                 stack_id=stack_id, quantity=quantity)
        return self.store.mutate(campaign_id, "sell_item", request, change,
                                 source=source)

    def apply_damage(self, campaign_id: str, actor_id: str, amount: int,
                     damage_type: str = "", *, critical: bool = False,
                     source: str = "mcp") -> dict:
        amount = int(amount)
        if amount < 0 or (damage_type and damage_type not in DAMAGE_TYPES):
            raise RuleError("伤害不能为负，且伤害类型必须是标准英文枚举")

        def change(state: dict) -> dict:
            actor = self._actor(state, actor_id)
            result = self._damage(actor, amount, damage_type, critical=critical)
            return {"actor_id": actor_id, **result}
        return self.store.mutate(campaign_id, "apply_damage", locals_request(
            actor_id=actor_id, amount=amount, damage_type=damage_type,
            critical=critical), change, source=source)

    def heal(self, campaign_id: str, actor_id: str, amount: int, *,
             source: str = "mcp") -> dict:
        amount = int(amount)
        if amount < 0:
            raise RuleError("治疗量不能为负")

        def change(state: dict) -> dict:
            actor = self._actor(state, actor_id)
            if actor["life_state"] == "dead":
                raise RuleError("普通治疗不能复活死亡角色")
            before = actor["hp"]
            actor["hp"] = min(actor["max_hp"], actor["hp"] + amount)
            if actor["hp"] > 0:
                self._wake(actor)
            return {"actor_id": actor_id, "healed": actor["hp"] - before,
                    "hp": actor["hp"], "life_state": actor["life_state"]}
        return self.store.mutate(campaign_id, "heal", locals_request(
            actor_id=actor_id, amount=amount), change, source=source)

    def set_condition(self, campaign_id: str, actor_id: str, name: str, *,
                      duration: int | None = None, condition_source: str = "",
                      remove: bool = False, source: str = "mcp") -> dict:
        key = name.casefold()
        if key not in CONDITIONS:
            raise RuleError(f"未知状态: {name}")
        if key == "unconscious":
            raise RuleError("昏迷由 HP 与生命状态机维护，不能作为普通状态手动修改")
        if duration is not None and int(duration) <= 0:
            raise RuleError("持续轮数必须大于零")

        def change(state: dict) -> dict:
            actor = self._actor(state, actor_id)
            if remove:
                existed = actor["conditions"].pop(key, None) is not None
                return {"removed": existed, "condition": key}
            actor["conditions"][key] = {
                "name": key, "duration": duration, "source": condition_source,
            }
            return {"condition": actor["conditions"][key]}
        request = locals_request(actor_id=actor_id, name=key, duration=duration,
                                 condition_source=condition_source, remove=remove)
        return self.store.mutate(campaign_id, "set_condition", request, change,
                                 source=source)

    def create_encounter(self, campaign_id: str, name: str,
                         sides: dict[str, list[str]], *,
                         source: str = "mcp") -> dict:
        encounter = {"id": new_id(), "name": name.strip(), "status": "setup",
                     "sides": deepcopy(sides), "turn_order": [],
                     "initiatives": {}, "round": 0, "current_index": 0,
                     "budgets": {}, "outcome": None, "log": []}

        def change(state: dict) -> dict:
            if not encounter["name"]:
                raise RuleError("遭遇名称不能为空")
            actor_ids = [actor for members in sides.values() for actor in members]
            if len(actor_ids) != len(set(actor_ids)):
                raise RuleError("同一角色不能重复加入遭遇")
            for actor_id in actor_ids:
                actor = self._actor(state, actor_id)
                if actor["life_state"] == "dead":
                    raise RuleError(f"死亡角色不能加入遭遇: {actor_id}")
            if len([members for members in sides.values() if members]) < 2:
                raise RuleError("遭遇至少需要两个非空阵营")
            state["encounters"][encounter["id"]] = encounter
            return {"encounter": encounter}
        return self.store.mutate(campaign_id, "create_encounter", encounter,
                                 change, source=source)

    def start_encounter(self, campaign_id: str, encounter_id: str, *,
                        source: str = "mcp") -> dict:
        def change(state: dict) -> dict:
            enc = self._encounter(state, encounter_id)
            if enc["status"] != "setup":
                raise RuleError("只有准备中的遭遇可以开始")
            # 阵营顺序固定，避免内存草稿与 JSON 重载后的先攻随机数分配不同。
            all_ids = [
                actor_id for side in sorted(enc["sides"])
                for actor_id in enc["sides"][side]
            ]
            for actor_id in all_ids:
                actor = self._actor(state, actor_id)
                enc["initiatives"][actor_id] = (
                    self.rng.randint(1, 20) + ability_mod(actor, "DEX")
                )
            enc["turn_order"] = sorted(
                all_ids,
                key=lambda aid: (enc["initiatives"][aid],
                                 ability_mod(state["actors"][aid], "DEX")),
                reverse=True,
            )
            enc["round"] = 1
            enc["current_index"] = 0
            enc["status"] = "active"
            self._reset_budget(enc, enc["turn_order"][0])
            enc["log"].append({"event": "initiative",
                               "values": deepcopy(enc["initiatives"])})
            return {"encounter": enc,
                    "current_actor_id": enc["turn_order"][0]}
        return self.store.mutate(campaign_id, "start_encounter",
                                 {"encounter_id": encounter_id}, change,
                                 source=source)

    def combat_attack(self, campaign_id: str, encounter_id: str,
                      actor_id: str, target_id: str, *, stack_id: str | None = None,
                      to_hit: int | None = None, damage: str | None = None,
                      damage_type: str | None = None,
                      advantage: bool | None = None,
                      source: str = "mcp") -> dict:
        def change(state: dict) -> dict:
            enc = self._active_turn(state, encounter_id, actor_id)
            actor = self._actor(state, actor_id)
            target = self._actor(state, target_id)
            if target_id not in enc["turn_order"]:
                raise RuleError("攻击目标不属于该遭遇")
            self._consume_budget(enc, actor_id, "action")
            hit_bonus, damage_expr, dtype = self._attack_profile(
                state, actor, stack_id, to_hit, damage, damage_type
            )
            resolved_advantage = self._attack_advantage(
                actor, target, target_id, advantage
            )
            attack_die = roll_d20(rng=self.rng, advantage=resolved_advantage)
            natural = attack_die["kept"]
            total = natural + hit_bonus
            hit = natural != 1 and (natural == 20 or total >= target["ac"])
            critical = natural == 20
            damage_roll = None
            applied = None
            if hit:
                damage_roll = roll(damage_expr, rng=self.rng,
                                   critical=critical).to_dict()
                applied = self._damage(target, max(0, damage_roll["total"]), dtype,
                                       critical=critical)
            event = {"event": "attack", "actor_id": actor_id,
                     "target_id": target_id, "attack": attack_die,
                     "attack_bonus": hit_bonus, "total": total, "hit": hit,
                     "critical": critical, "damage_roll": damage_roll,
                     "damage_type": dtype, "applied": applied}
            enc["log"].append(event)
            self._finish_if_over(state, enc)
            return event
        request = locals_request(encounter_id=encounter_id, actor_id=actor_id,
                                 target_id=target_id, stack_id=stack_id,
                                 to_hit=to_hit, damage=damage,
                                 damage_type=damage_type, advantage=advantage)
        return self.store.mutate(campaign_id, "combat_attack", request, change,
                                 source=source)

    def combat_death_save(self, campaign_id: str, encounter_id: str,
                          actor_id: str, *, source: str = "mcp") -> dict:
        def change(state: dict) -> dict:
            enc = self._active_turn(state, encounter_id, actor_id,
                                    allow_unconscious=True)
            actor = self._actor(state, actor_id)
            if actor["life_state"] != "unconscious":
                raise RuleError("只有未稳定的昏迷角色需要死亡豁免")
            self._consume_budget(enc, actor_id, "action")
            die = self.rng.randint(1, 20)
            saves = actor["death_saves"]
            if die == 20:
                actor["hp"] = 1
                self._wake(actor)
            elif die == 1:
                saves["failures"] += 2
            elif die >= 10:
                saves["successes"] += 1
            else:
                saves["failures"] += 1
            if saves["failures"] >= 3:
                actor["life_state"] = "dead"
                actor["conditions"].pop("unconscious", None)
            elif saves["successes"] >= 3:
                actor["life_state"] = "stable"
                actor["death_saves"] = {"successes": 0, "failures": 0}
            event = {"event": "death_save", "actor_id": actor_id, "roll": die,
                     "life_state": actor["life_state"],
                     "death_saves": deepcopy(actor["death_saves"])}
            enc["log"].append(event)
            self._finish_if_over(state, enc)
            return event
        return self.store.mutate(campaign_id, "combat_death_save",
                                 {"encounter_id": encounter_id,
                                  "actor_id": actor_id}, change, source=source)

    def combat_cast(self, campaign_id: str, encounter_id: str, actor_id: str,
                    spell_id: str, target_id: str, *, slot_level: int | None = None,
                    advantage: bool | None = None,
                    source_class: str | None = None,
                    slot_pool: str | None = None,
                    override_reason: str | None = None,
                    source: str = "mcp") -> dict:
        requested_class = (
            normalize_class_name(source_class) if source_class else None
        )
        override_reason = str(override_reason or "").strip() or None

        def change(state: dict) -> dict:
            enc = self._active_turn(state, encounter_id, actor_id)
            caster = self._actor(state, actor_id)
            target = self._actor(state, target_id)
            if target_id not in enc["turn_order"]:
                raise RuleError("法术目标不属于该遭遇")
            spell = self._spell(state, spell_id)
            warnings: list[str] = []
            class_id, repertoire = self._resolve_cast_source(
                caster, spell_id, requested_class, override_reason, warnings
            )
            self._consume_budget(enc, actor_id, "action")
            cast_level, consumed_pool = self._consume_spell_resource(
                caster, spell, slot_level, slot_pool, repertoire,
                override_reason, warnings,
            )
            casting_ability = CASTING_ABILITIES.get(
                class_id, caster.get("spellcasting_ability", "INT")
            )
            event = {"event": "cast", "actor_id": actor_id,
                      "target_id": target_id, "spell_id": spell_id,
                     "slot_level": cast_level, "slot_pool": consumed_pool,
                     "source_class": class_id, "kind": spell["kind"],
                     "warnings": warnings}
            event.update(self._apply_spell_effect(
                caster, target, spell, cast_level, casting_ability,
                advantage=advantage,
            ))
            if spell.get("concentration"):
                self._start_concentration(caster, spell)
                event["concentration_started"] = True
            enc["log"].append(event)
            self._finish_if_over(state, enc)
            return event
        request = locals_request(encounter_id=encounter_id, actor_id=actor_id,
                                 spell_id=spell_id, target_id=target_id,
                                 slot_level=slot_level, advantage=advantage,
                                 source_class=requested_class,
                                 slot_pool=slot_pool,
                                 override_reason=override_reason)
        return self.store.mutate(campaign_id, "combat_cast", request, change,
                                 source=source)

    def cast_spell(self, campaign_id: str, actor_id: str, spell_id: str, *,
                   target_id: str | None = None,
                   slot_level: int | None = None,
                   source_class: str | None = None,
                   slot_pool: str | None = None,
                   as_ritual: bool = False,
                   advantage: bool | None = None,
                   override_reason: str | None = None,
                   source: str = "mcp") -> dict:
        """在遭遇外施法；复杂效果记录资源消耗并交由 DM 结算。"""
        requested_class = (
            normalize_class_name(source_class) if source_class else None
        )
        override_reason = str(override_reason or "").strip() or None

        def change(state: dict) -> dict:
            caster = self._actor(state, actor_id)
            if caster["life_state"] == "dead":
                raise RuleError("死亡角色不能施法")
            target = self._actor(state, target_id) if target_id else None
            spell = self._spell(state, spell_id)
            warnings: list[str] = []
            active_encounters = [
                encounter for encounter in state["encounters"].values()
                if encounter.get("status") == "active"
                and actor_id in encounter.get("turn_order", [])
            ]
            self._enforce(
                not active_encounters,
                "角色正在活动遭遇中，必须使用 combat_cast",
                override_reason, warnings,
            )
            class_id, repertoire = self._resolve_cast_source(
                caster, spell_id, requested_class, override_reason, warnings,
                ritual=bool(as_ritual),
            )
            if as_ritual:
                self._enforce(bool(spell.get("ritual")),
                              "该法术没有仪式标记", override_reason, warnings)
                self._enforce(class_id in RITUAL_CASTERS if class_id else False,
                              "该来源职业不能进行仪式施法",
                              override_reason, warnings)
                cast_level, consumed_pool = int(spell["level"]), "ritual"
            else:
                cast_level, consumed_pool = self._consume_spell_resource(
                    caster, spell, slot_level, slot_pool, repertoire,
                    override_reason, warnings,
                )
            automatic = spell.get("kind") in {"attack", "save", "damage", "heal"}
            self._enforce(
                target is not None or not automatic,
                "可自动结算的法术必须提供 target_id",
                override_reason, warnings,
            )
            casting_ability = CASTING_ABILITIES.get(
                class_id, caster.get("spellcasting_ability", "INT")
            )
            event = {
                "event": "cast", "actor_id": actor_id,
                "target_id": target_id, "spell_id": spell_id,
                "slot_level": cast_level, "slot_pool": consumed_pool,
                "source_class": class_id, "kind": spell["kind"],
                "ritual": bool(as_ritual), "warnings": warnings,
                "casting_time": (
                    f"{spell.get('casting_time', '')} + 10 分钟"
                    if as_ritual else spell.get("casting_time", "")
                ),
            }
            if target is not None:
                event.update(self._apply_spell_effect(
                    caster, target, spell, cast_level, casting_ability,
                    advantage=advantage,
                ))
            else:
                event["manual_resolution_required"] = True
            if spell.get("concentration"):
                self._start_concentration(caster, spell)
                event["concentration_started"] = True
            return event

        request = locals_request(
            actor_id=actor_id, spell_id=spell_id, target_id=target_id,
            slot_level=slot_level, source_class=requested_class,
            slot_pool=slot_pool, as_ritual=as_ritual,
            advantage=advantage, override_reason=override_reason,
        )
        return self.store.mutate(campaign_id, "cast_spell", request, change,
                                 source=source)

    def combat_end_turn(self, campaign_id: str, encounter_id: str,
                        actor_id: str, *, source: str = "mcp") -> dict:
        def change(state: dict) -> dict:
            enc = self._active_turn(state, encounter_id, actor_id,
                                    allow_unconscious=True, allow_dead=True)
            actor = self._actor(state, actor_id)
            expired = []
            for key, condition in actor["conditions"].items():
                if condition["duration"] is not None:
                    condition["duration"] -= 1
                    if condition["duration"] <= 0:
                        expired.append(key)
            for key in expired:
                del actor["conditions"][key]
            # 战败实体保留在日志和先攻表中，但后续轮次自动跳过，避免回合卡死。
            for _ in enc["turn_order"]:
                enc["current_index"] = (
                    enc["current_index"] + 1
                ) % len(enc["turn_order"])
                if enc["current_index"] == 0:
                    enc["round"] += 1
                next_id = enc["turn_order"][enc["current_index"]]
                if state["actors"][next_id]["life_state"] != "dead":
                    break
            else:
                raise RuleError("遭遇中已经没有可推进回合的参与者")
            self._reset_budget(enc, next_id)
            event = {"event": "end_turn", "actor_id": actor_id,
                     "expired_conditions": expired, "next_actor_id": next_id,
                     "round": enc["round"]}
            enc["log"].append(event)
            return event
        return self.store.mutate(campaign_id, "combat_end_turn",
                                 {"encounter_id": encounter_id,
                                  "actor_id": actor_id}, change, source=source)

    def rest(self, campaign_id: str, actor_id: str, rest_type: str, *,
             hit_dice_healing: int = 0, source: str = "mcp") -> dict:
        if rest_type not in {"short", "long"}:
            raise RuleError("休息类型必须是 short 或 long")
        hit_dice_healing = int(hit_dice_healing)
        if hit_dice_healing < 0:
            raise RuleError("短休生命骰治疗量不能为负")

        def change(state: dict) -> dict:
            actor = self._actor(state, actor_id)
            if actor["life_state"] == "dead":
                raise RuleError("死亡角色不能休息")
            if rest_type == "short":
                before = actor["hp"]
                actor["hp"] = min(actor["max_hp"], actor["hp"] + hit_dice_healing)
                healed = actor["hp"] - before
                # 契约魔法位短休恢复，普通法术位与玄奥秘法不恢复。
                actor.get("pact_slots", {})["used"] = 0
            else:
                healed = actor["max_hp"] - actor["hp"]
                actor["hp"] = actor["max_hp"]
                actor["temp_hp"] = 0
                for slot in actor["spell_slots"].values():
                    slot["used"] = 0
                actor.get("pact_slots", {})["used"] = 0
                for arcanum in actor.get("mystic_arcanum", {}).values():
                    arcanum["used"] = False
                for resource in actor["resources"].values():
                    if resource.get("recharge") == "long_rest":
                        resource["current"] = resource["max"]
            if actor["hp"] > 0:
                self._wake(actor)
            return {"actor_id": actor_id, "rest_type": rest_type,
                    "healed": healed, "hp": actor["hp"],
                    "spell_slots": deepcopy(actor["spell_slots"]),
                    "pact_slots": deepcopy(actor.get("pact_slots", {})),
                    "mystic_arcanum": deepcopy(actor.get("mystic_arcanum", {}))}
        request = locals_request(actor_id=actor_id, rest_type=rest_type,
                                 hit_dice_healing=hit_dice_healing)
        return self.store.mutate(campaign_id, "rest", request, change,
                                 source=source)

    def campaign_summary(self, campaign_id: str) -> dict:
        state = self.store.get(campaign_id)
        actors = []
        for actor in state["actors"].values():
            copy = {k: actor[k] for k in (
                "id", "name", "kind", "level", "hp", "max_hp", "ac",
                "life_state")}
            copy["inventory_weight_lb"] = self._inventory_weight(state,
                                                                  actor["inventory"])
            copy["capacity_lb"] = carrying_capacity_lb(actor)
            actors.append(copy)
        active = [e for e in state["encounters"].values()
                  if e["status"] == "active"]
        return {"id": state["id"], "name": state["name"],
                "revision": state["revision"], "actors": actors,
                "active_encounters": active}

    @staticmethod
    def _spell_matches(spell: dict, needle: str, level: int | None,
                       school: str | None, class_id: str | None,
                       ritual: bool | None) -> bool:
        names = [spell.get("name", ""), spell.get("name_en", ""),
                 *spell.get("aliases", [])]
        if needle and not any(
                needle in normalize_spell_name(value) for value in names):
            return False
        if level is not None and int(spell.get("level", 0)) != int(level):
            return False
        if school and spell.get("school") != school:
            return False
        if class_id and class_id not in spell.get("classes", []):
            return False
        if ritual is not None and bool(spell.get("ritual", False)) is not bool(ritual):
            return False
        return True

    @staticmethod
    def _spell_summary(spell: dict) -> dict:
        resolution = spell.get("resolution", {})
        return {
            "id": spell["id"], "name": spell["name"],
            "name_en": spell.get("name_en", ""),
            "level": int(spell.get("level", 0)),
            "school": spell.get("school", ""),
            "ritual": bool(spell.get("ritual", False)),
            "classes": deepcopy(spell.get("classes", [])),
            "casting_time": spell.get("casting_time", ""),
            "range": spell.get("range", ""),
            "concentration": bool(spell.get("concentration", False)),
            "automatic_resolution": (
                resolution.get("mode") == "automatic"
                or not spell.get("manual_resolution_required", False)
                and spell.get("kind") != "utility"
            ),
            "source": spell.get("source", ""),
        }

    def _materialize_spell(self, state: dict, spell_id: str) -> dict:
        if spell_id not in state["spells"]:
            # 只在学习或准备时复制正文，避免战役状态依赖外部目录。
            state["spells"][spell_id] = self.spell_catalog.get(spell_id)
        return state["spells"][spell_id]

    @staticmethod
    def _enforce(condition: bool, message: str,
                 override_reason: str | None, warnings: list[str]) -> None:
        if condition:
            return
        if override_reason:
            warnings.append(f"DM 覆写: {message}；原因: {override_reason}")
            return
        raise RuleError(message)

    def _enforce_spell_class(self, spell: dict, class_id: str,
                             override_reason: str | None,
                             warnings: list[str]) -> None:
        classes = spell.get("classes", [])
        # 自定义法术没有职业列表时视为通用，外部及 SRD 法术严格使用目录列表。
        if classes:
            self._enforce(
                class_id in classes,
                f"{spell['name']} 不在 {CLASS_NAMES_ZH[class_id]} 法术列表中",
                override_reason, warnings,
            )

    @staticmethod
    def _learning_mode(class_id: str, spell: dict) -> str:
        level = int(spell.get("level", 0))
        if level == 0:
            return "cantrip"
        if class_id == "warlock" and level >= 6:
            return "arcanum"
        if class_id == "wizard":
            return "spellbook"
        if class_id in KNOWN_CASTERS:
            return "known"
        if class_id in PREPARED_CASTERS:
            return "prepare_only"
        raise RuleError(f"{CLASS_NAMES_ZH[class_id]}没有法术学习规则")

    def _enforce_repertoire_capacity(self, actor: dict, spell: dict,
                                     class_id: str, mode: str,
                                     override_reason: str | None,
                                     warnings: list[str]) -> None:
        capacity = spell_capacity(actor, class_id)
        spell_id = spell["id"]
        entries = [entry for entry in actor["spell_repertoire"].values()
                   if entry.get("source_class") == class_id
                   and entry.get("spell_id") != spell_id]
        if mode == "cantrip":
            used = sum(int(entry.get("spell_level", -1)) == 0
                       for entry in entries)
            self._enforce(
                used < capacity["cantrips"],
                f"{CLASS_NAMES_ZH[class_id]}已达到戏法数量上限 {capacity['cantrips']}",
                override_reason, warnings,
            )
        elif mode == "known":
            used = sum(entry.get("mode") == "known" for entry in entries)
            self._enforce(
                used < capacity["known"],
                f"{CLASS_NAMES_ZH[class_id]}已达到已知法术上限 {capacity['known']}",
                override_reason, warnings,
            )

    def _enforce_prepared_capacity(self, actor: dict, class_id: str,
                                   override_reason: str | None,
                                   warnings: list[str]) -> None:
        maximum = spell_capacity(actor, class_id)["prepared"]
        prepared_count = sum(
            entry.get("source_class") == class_id
            and bool(entry.get("prepared"))
            and int(entry.get("spell_level", 0)) > 0
            for entry in actor["spell_repertoire"].values()
        )
        self._enforce(
            prepared_count <= maximum,
            f"{CLASS_NAMES_ZH[class_id]}已超过准备法术上限 {maximum}",
            override_reason, warnings,
        )

    def _validate_repertoire_after_class_change(
            self, state: dict, actor: dict, override_reason: str | None,
            warnings: list[str]) -> None:
        """职业调整后重验来源和容量，防止降级后继续合法施放高环法术。"""
        levels = actor["class_levels"]
        for entry in actor.get("spell_repertoire", {}).values():
            class_id = entry.get("source_class")
            spell = self._spell(state, entry.get("spell_id"))
            self._enforce(class_id in levels,
                          f"法术 {spell['name']} 的来源职业已被移除",
                          override_reason, warnings)
            self._enforce_spell_class(spell, class_id, override_reason, warnings)
            self._enforce(
                int(spell["level"]) <= max_spell_level(
                    class_id, levels.get(class_id, 0)
                ),
                f"职业调整后无法保留 {spell['level']} 环法术 {spell['name']}",
                override_reason, warnings,
            )
        for class_id in levels:
            if class_id not in CASTING_ABILITIES:
                continue
            capacity = spell_capacity(actor, class_id)
            entries = [
                entry for entry in actor.get("spell_repertoire", {}).values()
                if entry.get("source_class") == class_id
            ]
            selected_cantrips = sum(
                int(entry.get("spell_level", -1)) == 0 for entry in entries
            )
            selected_known = sum(
                entry.get("mode") == "known" for entry in entries
            )
            selected_prepared = sum(
                bool(entry.get("prepared"))
                and int(entry.get("spell_level", 0)) > 0 for entry in entries
            )
            self._enforce(
                selected_cantrips <= capacity["cantrips"],
                f"{CLASS_NAMES_ZH[class_id]}戏法数量超过新上限",
                override_reason, warnings,
            )
            self._enforce(
                selected_known <= capacity["known"],
                f"{CLASS_NAMES_ZH[class_id]}已知法术数量超过新上限",
                override_reason, warnings,
            )
            if class_id in PREPARED_CASTERS:
                self._enforce(
                    selected_prepared <= capacity["prepared"],
                    f"{CLASS_NAMES_ZH[class_id]}准备法术数量超过新上限",
                    override_reason, warnings,
                )

    @staticmethod
    def _sync_castable_spells(actor: dict) -> None:
        castable = []
        for key, entry in actor.get("spell_repertoire", {}).items():
            mode = entry.get("mode")
            if (mode in {"known", "cantrip", "arcanum", "legacy_import"}
                    or bool(entry.get("prepared"))):
                castable.append(entry.get("spell_id", key))
        actor["spells"] = sorted(set(castable))

    @staticmethod
    def _repertoire_key(spell_id: str, class_id: str) -> str:
        return f"{spell_id}|{class_id}"

    @staticmethod
    def _actor_spellcasting(actor: dict) -> dict:
        summary = spellcasting_summary(actor)
        for class_id, capacity in summary["capacities"].items():
            ability = CASTING_ABILITIES[class_id]
            modifier = ability_mod(actor, ability)
            entries = [
                entry for entry in actor.get("spell_repertoire", {}).values()
                if entry.get("source_class") == class_id
            ]
            capacity.update({
                "attack_bonus": int(actor["proficiency_bonus"]) + modifier,
                "save_dc": 8 + int(actor["proficiency_bonus"]) + modifier,
                "cantrips_selected": sum(
                    int(entry.get("spell_level", -1)) == 0 for entry in entries
                ),
                "known_selected": sum(
                    entry.get("mode") == "known" for entry in entries
                ),
                "prepared_selected": sum(
                    bool(entry.get("prepared"))
                    and int(entry.get("spell_level", 0)) > 0
                    for entry in entries
                ),
            })
        return summary

    def _damage(self, actor: dict, amount: int, damage_type: str,
                *, critical: bool = False) -> dict:
        if actor["life_state"] == "dead":
            raise RuleError("目标已经死亡")
        effective = amount
        if damage_type:
            if damage_type in actor.get("immunities", []):
                effective = 0
            else:
                resistant = damage_type in actor.get("resistances", [])
                vulnerable = damage_type in actor.get("vulnerabilities", [])
                if resistant and not vulnerable:
                    effective //= 2
                elif vulnerable and not resistant:
                    effective *= 2
        original_hp = actor["hp"]
        temp_absorbed = min(actor["temp_hp"], effective)
        actor["temp_hp"] -= temp_absorbed
        remaining = effective - temp_absorbed
        # 只有穿透临时 HP 的实际伤害才会让 0 HP 角色死亡豁免失败。
        if (remaining > 0 and original_hp == 0
                and actor["life_state"] in {"unconscious", "stable"}):
            actor["life_state"] = "unconscious"
            actor["death_saves"]["failures"] += 2 if critical else 1
            if actor["death_saves"]["failures"] >= 3:
                actor["life_state"] = "dead"
                actor["conditions"].pop("unconscious", None)
        else:
            actor["hp"] = max(0, actor["hp"] - remaining)
            if actor["hp"] == 0:
                if actor["kind"] == "pc":
                    self._knock_unconscious(actor, source="damage")
                else:
                    actor["life_state"] = "dead"
        return {"requested_damage": amount, "damage": effective,
                "temp_hp_absorbed": temp_absorbed,
                "hp": actor["hp"], "life_state": actor["life_state"],
                "death_saves": deepcopy(actor["death_saves"]),
                "damage_type": damage_type}

    @staticmethod
    def _wake(actor: dict) -> None:
        """从 0 HP 恢复时统一清理昏迷和死亡豁免进度。"""
        actor["life_state"] = "conscious"
        actor["conditions"].pop("unconscious", None)
        actor["death_saves"] = {"successes": 0, "failures": 0}

    @staticmethod
    def _knock_unconscious(actor: dict, *, source: str) -> None:
        """让 PC 进入未稳定昏迷；仅在首次降到 0 HP 时重置死亡豁免。"""
        actor["life_state"] = "unconscious"
        actor["conditions"]["unconscious"] = {
            "name": "unconscious", "duration": None, "source": source,
        }
        actor["death_saves"] = {"successes": 0, "failures": 0}

    def _attack_profile(self, state: dict, actor: dict, stack_id: str | None,
                        to_hit: int | None, damage: str | None,
                        damage_type: str | None) -> tuple[int, str, str]:
        if stack_id:
            stack = self._stack(actor["inventory"], stack_id)
            if stack.get("equipped_slot") not in {"main_hand", "off_hand"}:
                raise RuleError("攻击武器必须先装备到手中")
            item = self._item(state, stack["item_id"])
            weapon = item.get("weapon")
            if not weapon:
                raise RuleError("该物品不是武器")
            ability = weapon["to_hit_ability"]
            return (ability_mod(actor, ability) + actor["proficiency_bonus"],
                    weapon["damage"], weapon["damage_type"])
        if to_hit is None or not damage or not damage_type:
            raise RuleError("未使用装备武器时必须提供 to_hit、damage 和 damage_type")
        if damage_type not in DAMAGE_TYPES:
            raise RuleError("未知伤害类型")
        return int(to_hit), damage, damage_type

    @staticmethod
    def _attack_advantage(actor: dict, target: dict, target_id: str,
                          requested: bool | None) -> bool | None:
        charmed_sources = {
            value.get("source") for name, value in actor["conditions"].items()
            if name == "charmed"
        }
        if target_id in charmed_sources:
            raise RuleError("被魅惑角色不能攻击魅惑来源")
        advantage = requested is True
        disadvantage = requested is False
        if "invisible" in actor["conditions"]:
            advantage = True
        if any(name in actor["conditions"] for name in (
            "blinded", "poisoned", "restrained"
        )):
            disadvantage = True
        if "blinded" in target["conditions"]:
            advantage = True
        if "invisible" in target["conditions"]:
            disadvantage = True
        if advantage and disadvantage:
            return None
        if advantage:
            return True
        if disadvantage:
            return False
        return None

    @staticmethod
    def _scaled_expression(base: str | None, scaling: str | None,
                           levels_up: int) -> str:
        if not base:
            raise RuleError("法术没有可自动结算的骰子效果")
        if not scaling or levels_up <= 0:
            return base
        pieces = []
        for _ in range(levels_up):
            pieces.append(scaling if scaling.startswith(("+", "-"))
                          else "+" + scaling)
        return base + "".join(pieces)

    def _resolve_cast_source(self, actor: dict, spell_id: str,
                             requested_class: str | None,
                             override_reason: str | None,
                             warnings: list[str], *,
                             ritual: bool = False) -> tuple[str | None, dict | None]:
        if not actor.get("class_levels"):
            self._enforce(spell_id in actor["spells"],
                          "角色没有学会或准备该法术",
                          override_reason, warnings)
            return None, None
        candidates = [
            entry for entry in actor.get("spell_repertoire", {}).values()
            if entry.get("spell_id") == spell_id
            and (requested_class is None
                 or entry.get("source_class") == requested_class)
        ]
        if not candidates:
            if requested_class is None:
                raise RuleError("角色没有该法术，覆写时也必须提供 source_class")
            self._enforce(False, "角色没有从该职业学会或准备法术",
                          override_reason, warnings)
            return requested_class, {
                "spell_id": spell_id, "source_class": requested_class,
                "mode": "override", "prepared": True,
            }
        if len(candidates) > 1 and requested_class is None:
            raise RuleError("该法术具有多个来源职业，请明确提供 source_class")
        entry = candidates[0]
        mode = entry.get("mode")
        castable = (
            mode in {"known", "cantrip", "arcanum", "legacy_import"}
            or bool(entry.get("prepared"))
        )
        if ritual and mode == "spellbook" and entry.get("source_class") == "wizard":
            castable = True
        self._enforce(castable, "该法术当前没有准备，不能施放",
                      override_reason, warnings)
        return entry.get("source_class"), entry

    def _consume_spell_resource(self, actor: dict, spell: dict,
                                requested_level: int | None,
                                requested_pool: str | None,
                                repertoire: dict | None,
                                override_reason: str | None,
                                warnings: list[str]) -> tuple[int, str]:
        base_level = int(spell["level"])
        if requested_pool not in {None, "auto", "shared", "pact", "arcanum"}:
            raise RuleError("slot_pool 必须是 shared、pact 或 arcanum")
        if base_level == 0:
            if requested_level not in {None, 0}:
                raise RuleError("戏法不能使用法术位升环")
            return 0, "cantrip"
        if requested_level is not None:
            requested_level = int(requested_level)
            if not base_level <= requested_level <= 9:
                raise RuleError("施法环位不能低于法术环位或高于 9 环")

        if not actor.get("class_levels"):
            cast_level = base_level if requested_level is None else requested_level
            slot = actor["spell_slots"].get(str(cast_level))
            self._enforce(
                slot is not None
                and int(slot.get("used", 0)) < int(slot.get("max", 0)),
                f"没有可用的 {cast_level} 环法术位",
                override_reason, warnings,
            )
            if slot is not None and int(slot.get("used", 0)) < int(slot.get("max", 0)):
                slot["used"] = int(slot.get("used", 0)) + 1
                return cast_level, "shared"
            return cast_level, "override"

        if repertoire and repertoire.get("mode") == "arcanum":
            self._enforce(requested_pool in {None, "auto", "arcanum"},
                          "玄奥秘法不能消耗普通或契约法术位",
                          override_reason, warnings)
            self._enforce(requested_level in {None, base_level},
                          "玄奥秘法必须按自身环位施放",
                          override_reason, warnings)
            arcanum = actor.get("mystic_arcanum", {}).get(str(base_level))
            available = (arcanum is not None
                         and arcanum.get("spell_id") == spell["id"]
                         and not arcanum.get("used", False))
            self._enforce(available, f"{base_level} 环玄奥秘法已经使用",
                          override_reason, warnings)
            if available:
                arcanum["used"] = True
                return base_level, "arcanum"
            return base_level, "override"

        shared_candidates = []
        for level, slot in actor.get("spell_slots", {}).items():
            numeric = int(level)
            if numeric < base_level or (requested_level is not None
                                        and numeric != requested_level):
                continue
            if int(slot.get("used", 0)) < int(slot.get("max", 0)):
                shared_candidates.append(numeric)
        pact = actor.get("pact_slots", {})
        pact_level = int(pact.get("slot_level", 0))
        pact_available = (
            pact_level >= base_level
            and (requested_level is None or requested_level == pact_level)
            and int(pact.get("used", 0)) < int(pact.get("max", 0))
        )
        shared_available = bool(shared_candidates)
        pool = None if requested_pool in {None, "auto"} else requested_pool
        if pool is None:
            if shared_available and pact_available:
                raise RuleError("共享与契约法术位都可用，请明确指定 slot_pool")
            pool = "shared" if shared_available else ("pact" if pact_available else None)
        if pool == "arcanum":
            self._enforce(False, "该法术不是玄奥秘法", override_reason, warnings)
            return requested_level or base_level, "override"
        if pool == "shared":
            self._enforce(shared_available, "没有符合环位的共享法术位",
                          override_reason, warnings)
            if shared_available:
                cast_level = min(shared_candidates)
                actor["spell_slots"][str(cast_level)]["used"] += 1
                return cast_level, "shared"
        elif pool == "pact":
            self._enforce(pact_available, "没有符合环位的契约法术位",
                          override_reason, warnings)
            if pact_available:
                pact["used"] = int(pact.get("used", 0)) + 1
                return pact_level, "pact"
        else:
            self._enforce(False, "没有可用的法术位", override_reason, warnings)
        return requested_level or base_level, "override"

    def _apply_spell_effect(self, caster: dict, target: dict, spell: dict,
                            cast_level: int, casting_ability: str, *,
                            advantage: bool | None = None) -> dict:
        kind = spell.get("kind", "utility")
        if spell.get("manual_resolution_required") or kind == "utility":
            return {"manual_resolution_required": True,
                    "resolution": deepcopy(spell.get("resolution", {}))}
        spell_mod = ability_mod(caster, casting_ability)
        levels_up = max(0, cast_level - int(spell["level"]))
        expression = self._scaled_expression(
            spell.get("damage") or spell.get("heal"),
            spell.get("slot_scaling"), levels_up,
        )
        result: dict = {}
        if kind == "attack":
            attack = roll_d20(rng=self.rng, advantage=advantage)
            total = attack["kept"] + spell_mod + caster["proficiency_bonus"]
            hit = attack["kept"] != 1 and (
                attack["kept"] == 20 or total >= target["ac"]
            )
            result.update({"attack": attack, "attack_total": total, "hit": hit})
            if hit:
                rolled = roll(expression, rng=self.rng,
                              critical=attack["kept"] == 20)
                result["roll"] = rolled.to_dict()
                result["applied"] = self._damage(
                    target, max(0, rolled.total), spell["damage_type"],
                    critical=attack["kept"] == 20,
                )
        elif kind == "save":
            dc = 8 + caster["proficiency_bonus"] + spell_mod
            save_ability = spell["save_ability"]
            save_bonus = ability_mod(target, save_ability)
            if save_ability in target["saving_throw_proficiencies"]:
                save_bonus += target["proficiency_bonus"]
            save_die = self.rng.randint(1, 20)
            saved = save_die + save_bonus >= dc
            rolled = roll(expression, rng=self.rng)
            amount = rolled.total
            if saved and spell.get("save_result") == "half":
                amount //= 2
            elif saved and spell.get("save_result") == "none":
                amount = 0
            result.update({
                "save": {"ability": save_ability, "dc": dc,
                         "roll": save_die, "bonus": save_bonus,
                         "saved": saved},
                "roll": rolled.to_dict(),
                "applied": self._damage(
                    target, max(0, amount), spell["damage_type"]
                ),
            })
        elif kind == "damage":
            rolled = roll(expression, rng=self.rng)
            result.update({"roll": rolled.to_dict(), "applied": self._damage(
                target, max(0, rolled.total), spell["damage_type"]
            )})
        elif kind == "heal":
            if target["life_state"] == "dead":
                raise RuleError("该法术不能复活死亡目标")
            rolled = roll(expression, rng=self.rng)
            amount = max(0, rolled.total + spell_mod)
            before = target["hp"]
            target["hp"] = min(target["max_hp"], target["hp"] + amount)
            if target["hp"] > 0:
                self._wake(target)
            result.update({"roll": rolled.to_dict(),
                           "spell_modifier": spell_mod,
                           "healed": target["hp"] - before,
                           "hp": target["hp"]})
        return result

    @staticmethod
    def _start_concentration(caster: dict, spell: dict) -> None:
        caster["conditions"]["concentrating"] = {
            "name": "concentrating", "duration": None,
            "source": spell["id"], "spell_name": spell["name"],
        }

    @staticmethod
    def _consume_budget(enc: dict, actor_id: str, kind: str) -> None:
        budget = enc["budgets"].setdefault(actor_id, {})
        if not budget.get(kind, False):
            raise RuleError(f"本回合已用完 {kind}")
        budget[kind] = False

    @staticmethod
    def _reset_budget(enc: dict, actor_id: str) -> None:
        enc["budgets"][actor_id] = {
            "action": True, "bonus_action": True, "reaction": True,
        }

    def _active_turn(self, state: dict, encounter_id: str,
                     actor_id: str, *, allow_unconscious: bool = False,
                     allow_dead: bool = False) -> dict:
        enc = self._encounter(state, encounter_id)
        if enc["status"] != "active":
            raise RuleError("遭遇未在进行中")
        current = enc["turn_order"][enc["current_index"]]
        if current != actor_id:
            raise RuleError(f"当前行动者是 {current}，不是 {actor_id}")
        actor = self._actor(state, actor_id)
        if actor["life_state"] == "dead" and not allow_dead:
            raise RuleError("死亡角色不能行动")
        if actor["life_state"] in {"unconscious", "stable"}:
            if allow_unconscious:
                return enc
            raise RuleError("昏迷或稳定角色不能执行该动作")
        if any(name in actor["conditions"] for name in (
            "incapacitated", "paralyzed", "petrified", "stunned", "unconscious"
        )):
            raise RuleError("角色当前无法行动")
        return enc

    def _finish_if_over(self, state: dict, enc: dict) -> None:
        """判定胜负，但保留倒地 PC 的死亡豁免收尾阶段。"""
        active_sides = 0
        for members in enc["sides"].values():
            if any(state["actors"][aid]["hp"] > 0
                   and state["actors"][aid]["life_state"] != "dead"
                   for aid in members):
                active_sides += 1
        if active_sides >= 2:
            enc["outcome"] = None
            return
        enc["outcome"] = "decided"
        unresolved_pc = any(
            state["actors"][actor_id]["kind"] == "pc"
            and state["actors"][actor_id]["life_state"] == "unconscious"
            for actor_id in enc["turn_order"]
        )
        if not unresolved_pc:
            enc["status"] = "finished"

    def _assert_capacity(self, state: dict, owner_id: str) -> None:
        """标准负重：角色背包总重不得超过力量值乘以 15 磅。"""
        if owner_id == "party":
            return
        actor = self._actor(state, owner_id)
        weight = self._inventory_weight(state, actor["inventory"])
        capacity = carrying_capacity_lb(actor)
        if weight > capacity + 1e-9:
            raise RuleError(f"负重超限: {weight:.2f}/{capacity:.2f} 磅")

    @staticmethod
    def _inventory(state: dict, owner_id: str) -> dict:
        if owner_id == "party":
            return state["party_inventory"]
        return WorkshopService._actor(state, owner_id)["inventory"]

    @staticmethod
    def _inventory_weight(state: dict, inventory: dict) -> float:
        return round(sum(
            float(state["items"][stack["item_id"]]["weight_lb"])
            * int(stack["quantity"]) for stack in inventory.values()
        ), 4)

    @staticmethod
    def _merge_stack(state: dict, inventory: dict, candidate: dict) -> None:
        item = state["items"][candidate["item_id"]]
        if not item.get("stackable"):
            return
        for stack_id, stack in list(inventory.items()):
            if stack_id == candidate["id"]:
                continue
            if (stack["item_id"] == candidate["item_id"]
                    and stack.get("container_id") == candidate.get("container_id")
                    and stack.get("notes", "") == candidate.get("notes", "")
                    and not stack.get("equipped_slot")):
                stack["quantity"] += candidate["quantity"]
                del inventory[candidate["id"]]
                return

    @staticmethod
    def _recalculate_ac(state: dict, actor: dict) -> None:
        """按基础 AC、已装备护甲和盾牌重新计算当前 AC。"""
        dex = ability_mod(actor, "DEX")
        base = int(actor.get("base_ac", 10 + dex))
        bonus = 0
        for stack in actor["inventory"].values():
            if not stack.get("equipped_slot"):
                continue
            armor = state["items"][stack["item_id"]].get("armor")
            if not armor:
                continue
            if "base_ac" in armor:
                cap = armor.get("dex_cap")
                base = armor["base_ac"] + (dex if cap is None else min(dex, cap))
            bonus += armor.get("ac_bonus", 0)
        actor["ac"] = base + bonus

    @staticmethod
    def _validate_actor(actor: dict) -> None:
        """校验可持久化角色的不变量，拒绝半合法状态进入数据库。"""
        if not actor["name"]:
            raise RuleError("角色名称不能为空")
        if not 1 <= int(actor["level"]) <= 20:
            raise RuleError("角色等级必须在 1 到 20 之间")
        if int(actor["max_hp"]) <= 0 or not 0 <= int(actor["hp"]) <= int(actor["max_hp"]):
            raise RuleError("HP 必须在 0 到最大 HP 之间")
        if int(actor.get("temp_hp", 0)) < 0:
            raise RuleError("临时 HP 不能为负")
        required_abilities = {"STR", "DEX", "CON", "INT", "WIS", "CHA"}
        if set(actor["abilities"]) != required_abilities:
            raise RuleError("角色必须且只能包含六项标准属性")
        for key, value in actor["abilities"].items():
            if not 1 <= int(value) <= 30:
                raise RuleError(f"属性 {key} 必须在 1 到 30 之间")
        if actor.get("spellcasting_ability", "INT") not in actor["abilities"]:
            raise RuleError("施法属性必须是角色已有的六项属性之一")
        for level, slot in actor["spell_slots"].items():
            try:
                numeric_level = int(level)
                maximum = int(slot["max"])
                used = int(slot.get("used", 0))
            except (KeyError, TypeError, ValueError) as exc:
                raise RuleError(f"法术位 {level!r} 格式错误") from exc
            if not 1 <= numeric_level <= 9 or maximum < 0 or not 0 <= used <= maximum:
                raise RuleError(f"法术位 {level!r} 数量非法")
        class_levels = actor.get("class_levels", {})
        if class_levels:
            normalized = normalize_class_levels(class_levels)
            if normalized != class_levels or sum(class_levels.values()) != int(actor["level"]):
                raise RuleError("职业等级必须使用规范英文枚举，且总和等于角色等级")
            pact = actor.get("pact_slots", {})
            if not (0 <= int(pact.get("used", 0)) <= int(pact.get("max", 0))):
                raise RuleError("契约魔法位使用量非法")
        for field in ("resistances", "vulnerabilities", "immunities"):
            unknown = set(actor.get(field, [])) - DAMAGE_TYPES
            if unknown:
                raise RuleError(f"{field} 包含未知伤害类型: {sorted(unknown)}")

    @staticmethod
    def _validate_item_definition(item: dict) -> None:
        """在物品进入目录时验证机器可执行字段，避免战斗中途才报内部错误。"""
        weapon = item.get("weapon")
        if weapon:
            ability = weapon.get("to_hit_ability")
            if ability not in {"STR", "DEX", "CON", "INT", "WIS", "CHA"}:
                raise RuleError("武器攻击属性必须是六项标准属性之一")
            damage_type = weapon.get("damage_type")
            if damage_type not in DAMAGE_TYPES:
                raise RuleError("武器包含未知伤害类型")
            damage = weapon.get("damage")
            if not damage:
                raise RuleError("武器必须提供伤害骰")
            roll(damage, rng=random.Random(0))
        armor = item.get("armor")
        if armor:
            if armor.get("slot") not in {"armor", "shield"}:
                raise RuleError("护甲装备栏必须是 armor 或 shield")
            if "base_ac" not in armor and "ac_bonus" not in armor:
                raise RuleError("护甲必须提供 base_ac 或 ac_bonus")
        container = item.get("container")
        if container:
            capacity = float(container.get("capacity_lb", 0))
            if not math.isfinite(capacity) or capacity <= 0:
                raise RuleError("容器容量必须是正数")

    @staticmethod
    def _actor(state: dict, actor_id: str) -> dict:
        try:
            return state["actors"][actor_id]
        except KeyError as exc:
            raise NotFoundError(f"找不到角色: {actor_id}") from exc

    @staticmethod
    def _item(state: dict, item_id: str) -> dict:
        try:
            return state["items"][item_id]
        except KeyError as exc:
            raise NotFoundError(f"找不到物品定义: {item_id}") from exc

    @staticmethod
    def _spell(state: dict, spell_id: str) -> dict:
        try:
            return state["spells"][spell_id]
        except KeyError as exc:
            raise NotFoundError(f"找不到法术定义: {spell_id}") from exc

    @staticmethod
    def _encounter(state: dict, encounter_id: str) -> dict:
        try:
            return state["encounters"][encounter_id]
        except KeyError as exc:
            raise NotFoundError(f"找不到遭遇: {encounter_id}") from exc

    @staticmethod
    def _stack(inventory: dict, stack_id: str) -> dict:
        try:
            return inventory[stack_id]
        except KeyError as exc:
            raise NotFoundError(f"找不到物品栈: {stack_id}") from exc

    # Compatibility names remain callable by the Web adapter, but never mutate state.
    def create_shop(self, *args: Any, **kwargs: Any) -> dict:
        raise UnsupportedFeatureError("商店系统当前已下线")

    def stock_shop(self, *args: Any, **kwargs: Any) -> dict:
        raise UnsupportedFeatureError("商店系统当前已下线")

    def buy_item(self, *args: Any, **kwargs: Any) -> dict:
        raise UnsupportedFeatureError("商店系统当前已下线")

    def sell_item(self, *args: Any, **kwargs: Any) -> dict:
        raise UnsupportedFeatureError("商店系统当前已下线")


def locals_request(**values: Any) -> dict:
    return values
