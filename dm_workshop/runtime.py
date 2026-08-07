"""进程级服务构造器，确保 Web 或 MCP 进程复用同一个存储实例。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dm_workshop.service import WorkshopService
from dm_workshop.store import CampaignStore


@lru_cache(maxsize=1)
def get_service() -> WorkshopService:
    path = Path(os.getenv("DM_WORKSHOP_DB", "data/dm_workshop.db"))
    return WorkshopService(CampaignStore(path))
