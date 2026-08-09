"""仅绑定本机的 REST API 与已构建 Web 管理台宿主。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from dm_workshop.errors import (
    ConflictError, NotFoundError, RuleError, UnsupportedFeatureError,
    WorkshopError,
)
from dm_workshop.runtime import get_service

app = FastAPI(title="DM Workshop", version="0.1.0")

COMMANDS = {
    name for name in (
        "update_actor", "define_item", "define_spell", "add_item",
        "remove_item", "transfer_item", "equip_item", "unequip_item",
        "create_shop", "stock_shop", "buy_item", "sell_item",
        "apply_damage", "heal", "set_condition", "create_encounter",
        "start_encounter", "combat_attack", "combat_cast", "combat_death_save",
        "combat_end_turn", "rest",
        "learn_spell",
    )
}

LEGACY_COMMERCE_COMMANDS = {"create_shop", "stock_shop", "buy_item", "sell_item"}


@app.exception_handler(WorkshopError)
async def workshop_error_handler(_, exc: WorkshopError):
    from fastapi.responses import JSONResponse
    status = 501 if isinstance(exc, UnsupportedFeatureError) else (
        404 if isinstance(exc, NotFoundError) else (
        409 if isinstance(exc, ConflictError) else 422
    ))
    content = {"detail": str(exc)}
    if isinstance(exc, UnsupportedFeatureError):
        content["code"] = exc.code
    return JSONResponse(status_code=status, content=content)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/campaigns")
def list_campaigns() -> list[dict]:
    return get_service().list_campaigns()


@app.get("/api/actor-presets")
def actor_presets() -> list[dict]:
    return get_service().list_actor_presets()


@app.post("/api/campaigns", status_code=201)
def create_campaign(body: dict[str, Any]) -> dict:
    try:
        if "preset_characters" not in body:
            raise HTTPException(status_code=422, detail="preset_characters 至少包含一个角色")
        return get_service().create_campaign(
            str(body.get("name", "")),
            preset_characters=body.get("preset_characters"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/campaigns/{campaign_id}")
def get_campaign(campaign_id: str) -> dict:
    return get_service().get_campaign(campaign_id)


@app.get("/api/campaigns/{campaign_id}/summary")
def campaign_summary(campaign_id: str) -> dict:
    return get_service().campaign_summary(campaign_id)


@app.get("/api/campaigns/{campaign_id}/items")
def search_items(campaign_id: str, q: str = "") -> list[dict]:
    return get_service().search_items(campaign_id, q)


@app.get("/api/campaigns/{campaign_id}/spells")
def search_spells(campaign_id: str, q: str = "") -> list[dict]:
    return get_service().search_spells(campaign_id, q)


@app.get("/api/campaigns/{campaign_id}/saves")
def save_slots(campaign_id: str, limit: int = 50,
               offset: int = 0) -> dict:
    return get_service().store.list_save_slots(
        campaign_id, limit=limit, offset=offset,
    )


@app.post("/api/campaigns/{campaign_id}/save")
def save_campaign(campaign_id: str, body: dict[str, Any]) -> dict:
    return get_service().store.save_campaign(
        campaign_id, body.get("slot_name"),
        note=str(body.get("note", "")),
        overwrite=bool(body.get("overwrite", False)),
    )


@app.post("/api/campaigns/{campaign_id}/discard")
def discard_campaign(campaign_id: str) -> dict:
    return get_service().store.discard_campaign_changes(campaign_id)


@app.post("/api/campaigns/{campaign_id}/saves/{save_id}/load")
def load_save_slot(campaign_id: str, save_id: str) -> dict:
    return get_service().store.load_save_slot(campaign_id, save_id)


@app.post("/api/campaigns/{campaign_id}/commands/{command}")
def execute_command(campaign_id: str, command: str,
                    body: dict[str, Any]) -> dict:
    if command in LEGACY_COMMERCE_COMMANDS:
        raise UnsupportedFeatureError("商店系统当前已下线")
    if command not in COMMANDS:
        raise HTTPException(status_code=404, detail=f"未知命令: {command}")
    # 白名单阻止调用者借动态路由访问 service 的内部辅助方法。
    if command not in COMMANDS:
        raise HTTPException(status_code=404, detail=f"未知命令: {command}")
    method = getattr(get_service(), command)
    try:
        # 动态命令路由没有 FastAPI 函数签名可校验，因此在边界统一转换参数错误。
        return method(campaign_id, source="web", **body)
    except TypeError as exc:
        raise HTTPException(status_code=422, detail=f"命令参数错误: {exc}") from exc


_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        candidate = (_DIST / path).resolve()
        if path and candidate.is_file() and _DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html")
