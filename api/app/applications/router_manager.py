"""Роутер менеджерского кабинета (issue #7)."""

import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.applications.service import ApplicationService
from app.applications.schemas import ManagerDecisionRequest, OfferPreviewRequest

router = APIRouter(prefix="/manager/applications", tags=["manager"])


@router.get("")
async def get_queue(
    status: str | None = None, db: AsyncSession = Depends(get_db)
):
    return {"items": [], "total": 0}


@router.post("/{app_id}/decisions")
async def make_decision(
    app_id: str,
    req: ManagerDecisionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    # TODO (#5): Извлечь manager_user_id из JWT
    manager_id = uuid.UUID("00000000-0000-0000-0000-000000000099")

    service = ApplicationService(
        db, request.app.state.ext_sim, request.app.state.categorization_rules
    )
    return await service.make_decision(
        uuid.UUID(app_id),
        req.revision,
        req.action,
        manager_id,
        req.amount_rub,
        req.term_months,
        req.comment,
    )


@router.post("/{app_id}/offer-preview")
async def preview_offer(
    app_id: str,
    req: OfferPreviewRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    # TODO: Чистая функция расчета без записи в БД
    return {
        "monthly_payment_rub": "91804.88",
        "dscr": "1.25",
        "valid": True,
        "violations": [],
    }