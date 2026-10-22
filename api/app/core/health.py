"""`GET /api/v1/health` (design.md §3.7).

`db` и `ext_sim` проверяются реальным запросом; `llm` пока выводится из
конфигурации без обращения к провайдеру. Состояние circuit breaker
(`degraded`) добавит #8.

`status`: `ok`; `degraded` — недоступен только ext-sim (200, остальной API работает);
`unavailable` — недоступна БД (503). От `llm` не зависит.
"""

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import LLMMode, Settings
from app.extsim_client import ExtSimClient

logger = logging.getLogger(__name__)

DB_CHECK_TIMEOUT_SECONDS = 3.0

ComponentStatus = Literal["ok", "unavailable"]
OverallStatus = Literal["ok", "degraded", "unavailable"]
LLMStatus = Literal["ok", "replay", "disabled", "degraded", "not_configured"]

router = APIRouter(tags=["service"])


class HealthResponse(BaseModel):
    status: OverallStatus
    db: ComponentStatus
    ext_sim: ComponentStatus
    llm: LLMStatus


async def check_db(engine: AsyncEngine) -> ComponentStatus:
    try:
        async with asyncio.timeout(DB_CHECK_TIMEOUT_SECONDS), engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("health: db unavailable (%s)", type(exc).__name__)
        return "unavailable"
    return "ok"


async def check_ext_sim(client: ExtSimClient) -> ComponentStatus:
    return "ok" if await client.health() else "unavailable"


def llm_status(settings: Settings) -> LLMStatus:
    if settings.llm_mode is LLMMode.REPLAY:
        return "replay"
    if settings.llm_mode is LLMMode.DISABLED:
        return "disabled"
    return "ok" if settings.llm_base_url else "not_configured"


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "БД недоступна"}},
)
async def health(request: Request, response: Response) -> HealthResponse:
    db, ext_sim = await asyncio.gather(
        check_db(request.app.state.engine), check_ext_sim(request.app.state.ext_sim)
    )
    status: OverallStatus
    if db != "ok":
        status = "unavailable"
        response.status_code = 503
    else:
        status = "ok" if ext_sim == "ok" else "degraded"
    return HealthResponse(
        status=status, db=db, ext_sim=ext_sim, llm=llm_status(request.app.state.settings)
    )
