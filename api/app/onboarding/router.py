"""Онбординг (#5): тексты согласий (публично), привязка компании и `GET /company` (CLIENT).
Монтируется во всех окружениях."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.examples import EXAMPLE_ID, EXAMPLE_NOW, attach_examples, example_from
from app.auth.deps import CurrentUserDep, require_role
from app.core.db import get_db
from app.core.errors import errors
from app.extsim_client import ExtSimClient
from app.onboarding import service
from app.onboarding.consents import current_consents
from app.schemas.auth import Company, CompanyBindingRequest, ConsentText, ConsentType, Role
from app.schemas.common import ErrorCode as E

public_router = APIRouter(tags=["onboarding"])
router = APIRouter(tags=["onboarding"], dependencies=[Depends(require_role(Role.CLIENT))])

Session = Annotated[AsyncSession, Depends(get_db)]


def ext_sim(request: Request) -> ExtSimClient:
    client: ExtSimClient = request.app.state.ext_sim
    return client


def _build_consent_texts() -> list[ConsentText]:
    texts = current_consents()
    return [texts[ConsentType.PD_PROCESSING], texts[ConsentType.BKI_REQUEST]]


@public_router.get(
    "/consents/texts",
    response_model=list[ConsentText],
    responses=errors(public=True, not_found=False, validation=False),
)
@example_from(_build_consent_texts)
async def consent_texts() -> list[ConsentText]:
    return _build_consent_texts()


def _build_company_binding(body: CompanyBindingRequest) -> Company:
    return Company(
        id=UUID(EXAMPLE_ID),
        inn=body.inn,
        legal_form="LLC",
        name="ООО «Пекарня Плюс»",
        okved_main="10.71",
        registered_at=date(2023, 10, 21),
        bound_at=EXAMPLE_NOW,
    )


@router.post(
    "/onboarding/company-binding",
    response_model=Company,
    responses=errors(
        E.INVALID_INN,
        E.CONSENT_REQUIRED,
        E.COMPANY_NOT_IN_REGISTRY,
        E.APPLICANT_NOT_AUTHORIZED,
        E.COMPANY_ALREADY_BOUND,
        E.USER_ALREADY_BOUND,
        E.PROVIDER_UNAVAILABLE,
        not_found=False,
    ),
)
@example_from(_build_company_binding)
async def company_binding(
    body: CompanyBindingRequest,
    user: CurrentUserDep,
    session: Session,
    client: Annotated[ExtSimClient, Depends(ext_sim)],
) -> Company:
    return await service.bind_company(session, client, user, body)


def _build_company() -> Company:
    return Company(
        id=UUID(EXAMPLE_ID),
        inn="0099020010",
        legal_form="LLC",
        name="ООО «Пекарня Плюс»",
        okved_main="10.71",
        registered_at=date(2023, 10, 21),
        bound_at=EXAMPLE_NOW,
    )


@router.get(
    "/company",
    response_model=Company,
    responses=errors(E.COMPANY_NOT_BOUND, not_found=False, validation=False),
)
@example_from(_build_company)
async def company(user: CurrentUserDep, session: Session) -> Company:
    return await service.get_company(session, user)


attach_examples((public_router, router))
