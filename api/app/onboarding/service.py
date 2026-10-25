"""Привязка компании по ИНН (#5, design.md §3.3).

Порядок проверок: контрольная сумма ИНН → версия согласия ПД → реестр → полномочия →
уникальность. Запись — одна транзакция: `companies`, `users.company_id`,
`consents (PD_PROCESSING)`, `external_snapshots`.

Конкурентность. Транзакция блокирует сначала строку пользователя, затем строку компании
(`SELECT … FOR UPDATE`; новая компания вставляется `ON CONFLICT (inn) DO NOTHING`,
конкурент ждёт её коммита). Все привязки идут через эти две блокировки в одном порядке,
поэтому проверка «компания уже у другого клиента» видит закоммиченный результат
соперника, а взаимной блокировки нет. Схема БД при этом не меняется.

Повтор той же привязки тем же клиентом — `200` без новых согласия и снимка.
Статус компании (ликвидация) не проверяется: это стоп-фактор Submit (#7).
"""

from datetime import datetime

from sqlalchemy import exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser
from app.core.errors import AppError
from app.db.models import Company as CompanyRow
from app.db.models import Consent, ExternalSnapshot, User
from app.extsim_client import ExtSimClient
from app.extsim_client.dto import EgrulCompany, RegistryRecord
from app.extsim_client.errors import CompanyNotInRegistryError, ProviderUnavailableError
from app.onboarding.authorization import is_authorized_applicant
from app.onboarding.consents import current_version
from app.onboarding.inn import is_valid_inn
from app.schemas.auth import Company, CompanyBindingRequest, ConsentType
from app.schemas.common import ErrorCode as E


def _ie_name(full_name: str) -> str:
    surname, *rest = full_name.split()
    return " ".join(["ИП", surname, *(f"{part[0]}." for part in rest)])


def _company_values(record: RegistryRecord) -> dict[str, object]:
    if isinstance(record, EgrulCompany):
        return {"legal_form": "LLC", "name": record.name}
    return {"legal_form": "IE", "name": _ie_name(record.full_name)}


async def _view(session: AsyncSession, company: CompanyRow, user_id: object) -> Company:
    # Время привязки — время согласия ПД на эту компанию.
    bound_at: datetime | None = await session.scalar(
        select(func.max(Consent.granted_at)).where(
            Consent.user_id == user_id,
            Consent.company_id == company.id,
            Consent.type == ConsentType.PD_PROCESSING,
        )
    )
    return Company(
        id=company.id,
        inn=company.inn,
        legal_form=company.legal_form,
        name=company.name,
        okved_main=company.okved_main,
        registered_at=company.registered_at,
        bound_at=bound_at or company.created_at,
    )


async def bind_company(
    session: AsyncSession, ext_sim: ExtSimClient, user: CurrentUser, body: CompanyBindingRequest
) -> Company:
    if not is_valid_inn(body.inn):
        raise AppError(E.INVALID_INN, "Проверьте ИНН")
    pd_version = current_version(ConsentType.PD_PROCESSING)
    if body.pd_consent_version != pd_version:
        raise AppError(E.CONSENT_REQUIRED, "Подтвердите актуальное согласие")
    try:
        record = await ext_sim.get_registry_record(body.inn)
    except CompanyNotInRegistryError:
        raise AppError(E.COMPANY_NOT_IN_REGISTRY, "Компания не найдена в реестре") from None
    except ProviderUnavailableError:
        raise AppError(E.PROVIDER_UNAVAILABLE, "Реестр недоступен, повторите позже") from None
    if not is_authorized_applicant(record, user):
        raise AppError(
            E.APPLICANT_NOT_AUTHORIZED,
            "Подать заявку может только руководитель компании или сам ИП",
        )

    async with session.begin():
        bound = await session.scalar(
            select(User.company_id).where(User.id == user.id).with_for_update()
        )
        if bound is not None:
            current = await session.get_one(CompanyRow, bound)
            if current.inn != body.inn:
                raise AppError(E.USER_ALREADY_BOUND, "К учётной записи уже привязана компания")
            return await _view(session, current, user.id)

        await session.execute(
            insert(CompanyRow)
            .values(
                inn=body.inn,
                okved_main=record.okved_main,
                registered_at=record.registered_at,
                **_company_values(record),
            )
            .on_conflict_do_nothing(index_elements=["inn"])
        )
        company = (
            await session.execute(
                select(CompanyRow)
                .where(CompanyRow.inn == body.inn)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        taken = await session.scalar(
            select(exists().where(User.company_id == company.id, User.id != user.id))
        )
        if taken:
            raise AppError(E.COMPANY_ALREADY_BOUND, "Компания уже привязана")
        await session.execute(update(User).where(User.id == user.id).values(company_id=company.id))
        await session.execute(
            insert(Consent).values(
                user_id=user.id,
                company_id=company.id,
                type=ConsentType.PD_PROCESSING,
                text_version=pd_version,
            )
        )
        await session.execute(
            insert(ExternalSnapshot).values(
                company_id=company.id,
                provider="EGRUL" if isinstance(record, EgrulCompany) else "EGRIP",
                response_json=record.model_dump(mode="json"),
            )
        )
        return await _view(session, company, user.id)


async def get_company(session: AsyncSession, user: CurrentUser) -> Company:
    if user.company_id is None:
        raise AppError(E.COMPANY_NOT_BOUND, "Привяжите компанию")
    company = await session.get_one(CompanyRow, user.company_id)
    return await _view(session, company, user.id)
