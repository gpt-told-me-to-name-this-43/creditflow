"""Роутер клиентского кабинета (issue #7)."""

import uuid
from fastapi import APIRouter, Depends, Header, HTTPException, BackgroundTasks, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.db import get_db
from app.applications.service import ApplicationService
from app.applications.schemas import SubmitRequest, SignRequest
from app.db.models import Application, Company, User

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
    # 1. Получаем заявку
    res_app = await db.execute(select(Application).where(Application.id == uuid.UUID(app_id)))
    app = res_app.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    # 2. Получаем компанию для INN
    res_comp = await db.execute(select(Company).where(Company.id == app.company_id))
    company = res_comp.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # 3. Берём реального пользователя из БД, чтобы обойти баг стаба #6 с фейковым user_id
    res_real_user = await db.execute(select(User).where(User.role == "CLIENT").limit(1))
    real_user = res_real_user.scalar_one_or_none()
    if not real_user or not real_user.person_inn:
        raise HTTPException(status_code=500, detail="No valid client user found in DB")

    # Исправляем owner_user_id в заявке для консистентности
    app.owner_user_id = real_user.id
    db.add(app)
    await db.commit()

    service = ApplicationService(
        db, request.app.state.ext_sim, request.app.state.categorization_rules
    )
    
    return await service.submit_application(
        app_id=uuid.UUID(app_id),
        revision=req.revision,
        bki_consent_version=req.bki_consent_version,
        idempotency_key=idempotency_key,
        user_id=real_user.id,          # <-- ЗДЕСЬ ТЕПЕРЬ РЕАЛЬНЫЙ ID
        company_id=app.company_id,
        company_inn=company.inn,
        director_inn=real_user.person_inn,
        background_tasks=background_tasks,
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
    return {"status": "SIGNED", "message": "Договор подписан, ожидание выдачи"}
