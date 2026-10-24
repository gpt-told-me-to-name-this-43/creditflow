"""Роутер клиентского кабинета (issue #7)."""

import uuid
from fastapi import APIRouter, Depends, Header, HTTPException, BackgroundTasks, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.applications.service import ApplicationService
from app.applications.schemas import SubmitRequest, SignRequest

router = APIRouter(prefix="/applications", tags=["client"])


@router.post("/{app_id}/submit")
async def submit_application(
    app_id: str,
    req: SubmitRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    # TODO (#5): Извлечь из JWT
    user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    company_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    company_inn = "009902001009"
    director_inn = "009902001009"

    service = ApplicationService(
        db, request.app.state.ext_sim, request.app.state.categorization_rules
    )
    return await service.submit_application(
        uuid.UUID(app_id),
        req.revision,
        req.bki_consent_version,
        idempotency_key,
        user_id,
        company_id,
        company_inn,
        director_inn,
        background_tasks,
    )


@router.post("/{app_id}/sign/challenge")
async def create_challenge(
    app_id: str, db: AsyncSession = Depends(get_db)
):
    return {
        "challenge_id": "demo-challenge-123",
        "expires_at": "2026-10-25T12:05:00Z",
        "demo_code": "123456",
    }


@router.post("/{app_id}/sign")
async def sign_application(
    app_id: str, req: SignRequest, db: AsyncSession = Depends(get_db)
):
    # TODO: Реализовать проверку хеша и смену статуса на SIGNED + фоновую задачу на ISSUED
    return {"status": "SIGNED", "message": "Договор подписан, ожидание выдачи"}
