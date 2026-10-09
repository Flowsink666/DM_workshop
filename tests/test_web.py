from pathlib import Path

from fastapi.testclient import TestClient

import dm_workshop.web as web
from dm_workshop.service import WorkshopService
from dm_workshop.store import CampaignStore


def test_web_campaign_command_flow(tmp_path: Path, monkeypatch):
    service = WorkshopService(CampaignStore(tmp_path / "web.db"))
    monkeypatch.setattr(web, "get_service", lambda: service)
    client = TestClient(web.app)

    assert client.get("/api/health").json() == {"status": "ok"}
    created = client.post("/api/campaigns", json={
        "name": "Web 战役",
        "preset_characters": [{"preset_id": "fighter", "name": "游侠"}],
    })
    assert created.status_code == 201
    campaign = created.json()
    assert campaign["revision"] == 0
    assert campaign["workspace"]["dirty"] is True

    actor_result = client.post(
        f"/api/campaigns/{campaign['id']}/commands/create_actor",
        json={"name": "游侠", "kind": "pc", "max_hp": 12, "ac": 14},
    )
    assert actor_result.status_code == 404
    actor_id = next(iter(campaign["actors"]))
    summary = client.get(f"/api/campaigns/{campaign['id']}/summary").json()
    assert summary["actors"][0]["id"] == actor_id

    invalid = client.post(
        f"/api/campaigns/{campaign['id']}/commands/apply_damage",
        json={"actor_id": actor_id, "amount": -1},
    )
    assert invalid.status_code == 422
    assert "伤害不能为负" in invalid.json()["detail"]


def test_built_frontend_is_served():
    client = TestClient(web.app)
    response = client.get("/")
    assert response.status_code == 200
    assert "DM Workshop" in response.text


def test_missing_campaign_save_slots_returns_404(tmp_path: Path, monkeypatch):
    service = WorkshopService(CampaignStore(tmp_path / "missing.db"))
    monkeypatch.setattr(web, "get_service", lambda: service)
    response = TestClient(web.app).get("/api/campaigns/not-found/saves")
    assert response.status_code == 404


def test_web_preset_catalog_and_required_campaign_selection(tmp_path: Path, monkeypatch):
    service = WorkshopService(CampaignStore(tmp_path / "preset-web.db"))
    monkeypatch.setattr(web, "get_service", lambda: service)
    client = TestClient(web.app)
    presets = client.get("/api/actor-presets")
    assert presets.status_code == 200
    assert len(presets.json()) == 12
    assert client.post("/api/campaigns", json={"name": "缺少角色"}).status_code == 422


def test_web_monster_presets_and_commands(tmp_path: Path, monkeypatch):
    service = WorkshopService(CampaignStore(tmp_path / "monster-web.db"))
    monkeypatch.setattr(web, "get_service", lambda: service)
    client = TestClient(web.app)

    # 1. 验证怪物预设接口
    m_presets = client.get("/api/monster-presets")
    assert m_presets.status_code == 200
    assert any(m["preset_id"] == "goblin" for m in m_presets.json())

    # 2. 创建战役
    c_res = client.post("/api/campaigns", json={
        "name": "怪物测试战役",
        "preset_characters": [{"preset_id": "fighter", "name": "战士"}],
    })
    campaign_id = c_res.json()["id"]

    # 3. 通过 web commands 刷出怪物
    spawn_res = client.post(
        f"/api/campaigns/{campaign_id}/commands/spawn_monster",
        json={"preset_id": "goblin", "count": 1},
    )
    assert spawn_res.status_code == 200
    assert spawn_res.json()["result"]["count"] == 1

    # 4. 通过 web commands 执行属性检定
    actor_id = next(iter(c_res.json()["actors"]))
    check_res = client.post(
        f"/api/campaigns/{campaign_id}/commands/check_ability",
        json={"actor_id": actor_id, "ability": "STR", "dc": 10},
    )
    assert check_res.status_code == 200
    assert "d20" in check_res.json()["result"]

