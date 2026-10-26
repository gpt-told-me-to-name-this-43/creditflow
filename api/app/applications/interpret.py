"""`POST /applications/{id}/interpret` (#8): распознавание потребности без записи в заявку.

Заявка только читается (владение, статус `DRAFT`) в короткой транзакции, которая закрывается
до вызова модели: медленный провайдер не держит соединение пула и не тормозит остальные
эндпоинты. Ни заявка, ни `revision`, ни события не меняются — сохранение отдельным PATCH.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.applications import repo
from app.auth.deps import CurrentUser
from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import Company
from app.llm.base import LLMClient
from app.llm.intent import interpret_text
from app.schemas.client import InterpretResponse
from app.schemas.common import ErrorCode
from app.schemas.enums import ApplicationStatus


async def interpret_application(
    session: AsyncSession,
    llm: LLMClient,
    settings: Settings,
    user: CurrentUser,
    application_id: uuid.UUID,
    purpose_text: str,
) -> InterpretResponse:
    async with session.begin():
        application = await repo.get_owned(session, application_id, user.id)
        if application.status != ApplicationStatus.DRAFT:
            raise AppError(
                ErrorCode.INVALID_STATUS_TRANSITION, "Распознавание доступно только в черновике"
            )
        company = await session.get(Company, application.company_id)
        company_names = (company.name,) if company else ()
    return await interpret_text(
        purpose_text,
        llm,
        settings.llm_timeout_seconds,
        person_names=(user.full_name,),
        company_names=company_names,
    )
