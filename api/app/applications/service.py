"""ApplicationService: черновик заявки (design.md §3.3, §3.7, issue #7).

Изменяющая операция — одна транзакция: блокировка заявки, проверки, эффект, `revision`.
Статус меняет только `fsm`; создание черновика тоже проходит через таблицу FSM.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications import fsm, repo
from app.auth.deps import CurrentUser
from app.core.errors import AppError
from app.db.models import Application, CreditProduct
from app.schemas.client import ApplicationCreate, ApplicationPatch, FieldSource, TermsField
from app.schemas.common import ErrorCode, ValidationDetail, ValidationDetails
from app.schemas.enums import ApplicationStatus, TermsSource

_TERMS_FIELDS = {f.value for f in TermsField}


def derive_terms_source(sources: dict[str, str]) -> TermsSource:
    """LLM_CONFIRMED — хотя бы одно поле от LLM; иначе RULES_CONFIRMED — от правил; иначе MANUAL."""
    values = set(sources.values())
    if FieldSource.LLM in values:
        return TermsSource.LLM_CONFIRMED
    if FieldSource.RULES in values:
        return TermsSource.RULES_CONFIRMED
    return TermsSource.MANUAL


async def create_draft(
    session: AsyncSession, user: CurrentUser, body: ApplicationCreate
) -> tuple[Application, bool]:
    """Новый DRAFT (True) или существующий без применения тела (False).

    Второй черновик исключает частичный уникальный индекс `uq_applications_one_draft`:
    при гонке конкурентный INSERT ждёт COMMIT первого и получает DO NOTHING.
    """
    assert user.company_id is not None  # гарантирует зависимость BoundClient
    async with session.begin():
        new_id = await session.scalar(
            insert(Application)
            .values(
                company_id=user.company_id,
                owner_user_id=user.id,
                status=fsm.initial_status(fsm.Actor.CLIENT).value,
                revision=1,  # создание — первый переход FSM (— → DRAFT)
                purpose_text=body.purpose_text,
            )
            .on_conflict_do_nothing(
                index_elements=[Application.owner_user_id],
                index_where=text("status = 'DRAFT'"),
            )
            .returning(Application.id)
        )
        if new_id is not None:
            fsm.record_event(session, new_id, None, ApplicationStatus.DRAFT, user.id)
            application_id = new_id
        else:
            existing = await session.scalar(
                select(Application.id).where(
                    Application.owner_user_id == user.id,
                    Application.status == ApplicationStatus.DRAFT,
                )
            )
            assert existing is not None  # конфликт по индексу = DRAFT уже закоммичен
            application_id = existing
    return await repo.get_owned(session, application_id, user.id), new_id is not None


async def list_applications(session: AsyncSession, user: CurrentUser) -> list[Application]:
    rows = await session.scalars(
        select(Application)
        .where(Application.owner_user_id == user.id)
        .order_by(Application.created_at.desc(), Application.id)
    )
    return list(rows)


def _invalid_field(field: str, code: str, message: str) -> AppError:
    return AppError(
        ErrorCode.VALIDATION_ERROR,
        message,
        ValidationDetails(fields=[ValidationDetail(field=field, code=code, message=message)]),
    )


async def patch_draft(
    session: AsyncSession, user: CurrentUser, application_id: uuid.UUID, body: ApplicationPatch
) -> Application:
    """Сохраняет только явно переданные поля (null очищает). Только DRAFT, свежая revision.

    Источники полей: переданный `terms_field_sources` дополняет сохранённые; поле условий,
    изменённое без указания источника, получает MANUAL; очищенное поле теряет источник.
    """
    changes = body.model_dump(exclude_unset=True, exclude={"revision", "terms_field_sources"})
    async with session.begin():
        application = await repo.lock_owned(session, application_id, user.id)
        if application.status != ApplicationStatus.DRAFT:
            raise AppError(ErrorCode.INVALID_STATUS_TRANSITION, "Изменять можно только черновик")
        repo.ensure_revision(application, body.revision)
        product_id = changes.get("product_id")
        if product_id is not None and await session.get(CreditProduct, product_id) is None:
            raise _invalid_field("body.product_id", "UNKNOWN_PRODUCT", "Такого продукта нет")

        sources = dict(application.terms_field_sources_json)
        given = {k.value: v.value for k, v in (body.terms_field_sources or {}).items()}
        for field, value in changes.items():
            if field == "requested_amount_rub" and value is not None:
                value = Decimal(value)
            setattr(application, field, value)
            if field in _TERMS_FIELDS:
                if value is None:
                    sources.pop(field, None)
                else:
                    sources[field] = given.get(field, FieldSource.MANUAL.value)
        sources |= {f: s for f, s in given.items() if getattr(application, f) is not None}
        application.terms_field_sources_json = sources
        application.terms_source = derive_terms_source(sources).value
        application.revision += 1
        application.updated_at = datetime.now(UTC)
    return application
