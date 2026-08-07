import sqlite3
from pathlib import Path

from dm_workshop.spell_catalog import (
    ExternalSpellCatalog, parse_class_metadata, stable_spell_id,
)


ROOT_CATALOG = Path(__file__).parents[1] / "spells.db"


def test_external_catalog_cleans_and_parses_user_database():
    catalog = ExternalSpellCatalog(ROOT_CATALOG)
    status = catalog.status()

    assert status["available"] is True
    assert status["raw_rows"] == 1071
    assert status["unique_spells"] == 356
    assert "去除重复行 712" in " ".join(status["warnings"])
    levels = {spell["level"] for spell in catalog.search()}
    assert levels == set(range(10))


def test_catalog_ids_are_stable_and_search_supports_filters():
    first = ExternalSpellCatalog(ROOT_CATALOG)
    second = ExternalSpellCatalog(ROOT_CATALOG)
    result = first.search("祈愿术", level=9, school="咒法",
                          caster_class="法师")

    assert len(result) == 1
    assert result[0]["id"] == second.search("祈愿术")[0]["id"]
    assert result[0]["id"] == stable_spell_id("祈愿术")
    assert result[0]["name_en"] == ""


def test_metadata_parser_accepts_reversed_cantrip_and_ritual():
    assert parse_class_metadata("塑能 戏法 邪术师") == {
        "level": 0, "school": "塑能", "ritual": False,
        "classes": ["warlock"],
    }
    ritual = parse_class_metadata("1 环 防护（仪式） 游侠 法师")
    assert ritual == {"level": 1, "school": "防护", "ritual": True,
                      "classes": ["ranger", "wizard"]}


def test_resolution_is_automatic_only_for_simple_effects():
    catalog = ExternalSpellCatalog(ROOT_CATALOG)
    ray = catalog.search("冷冻射线")[0]
    call_lightning = catalog.search("召雷术")[0]
    wish = catalog.search("祈愿术")[0]

    assert ray["resolution"]["mode"] == "automatic"
    assert ray["kind"] == "attack"
    assert call_lightning["manual_resolution_required"] is True
    assert wish["manual_resolution_required"] is True


def test_missing_or_invalid_catalog_reports_status(tmp_path: Path):
    missing = ExternalSpellCatalog(tmp_path / "missing.db").status()
    assert missing["available"] is False

    invalid_path = tmp_path / "invalid.db"
    with sqlite3.connect(invalid_path) as connection:
        connection.execute("CREATE TABLE spells (id INTEGER PRIMARY KEY, name TEXT)")
    invalid = ExternalSpellCatalog(invalid_path).status()
    assert invalid["available"] is False
    assert "缺少字段" in invalid["warnings"][0]
