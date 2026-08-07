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
    created = client.post("/api/campaigns", json={"name": "Web 战役"})
    assert created.status_code == 201
    campaign = created.json()
    assert campaign["revision"] == 1  # SRD seed is an audited operation.

    actor_result = client.post(
        f"/api/campaigns/{campaign['id']}/commands/create_actor",
        json={"name": "游侠", "kind": "pc", "max_hp": 12, "ac": 14},
    )
    assert actor_result.status_code == 200
    actor_id = actor_result.json()["result"]["actor"]["id"]
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


def test_missing_campaign_operations_returns_404(tmp_path: Path, monkeypatch):
    service = WorkshopService(CampaignStore(tmp_path / "missing.db"))
    monkeypatch.setattr(web, "get_service", lambda: service)
    response = TestClient(web.app).get("/api/campaigns/not-found/operations")
    assert response.status_code == 404
