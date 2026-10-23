"""DTO входа и онбординга (design.md §3.3, issue #5)."""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.schemas.common import Schema

Inn = Annotated[str, Field(pattern=r"^\d{10}$|^\d{12}$", examples=["0099020010"])]


class Role(StrEnum):
    CLIENT = "CLIENT"
    MANAGER = "MANAGER"


class LoginRequest(Schema):
    login: str = Field(min_length=1, max_length=254, examples=["director.bakery@creditflow.demo"])
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(Schema):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Секунды до истечения (8 ч)")


class Me(Schema):
    id: UUID
    role: Role
    full_name: str
    company_id: UUID | None


class DemoAccount(Schema):
    login: str
    password: str = Field(description="Демо-пароль; маршрут доступен только с DEMO_AUTH_ENABLED")
    role: Role
    label: str = Field(description="Подпись на экране входа")
    scenario: str = Field(description="Ожидаемый сценарий: C1…C7, бухгалтер, менеджер")


class ConsentType(StrEnum):
    PD_PROCESSING = "PD_PROCESSING"
    BKI_REQUEST = "BKI_REQUEST"


class ConsentText(Schema):
    type: ConsentType
    version: str
    text: str


class CompanyBindingRequest(Schema):
    inn: Inn
    pd_consent_version: str = Field(min_length=1, max_length=64)


class Company(Schema):
    id: UUID
    inn: Inn
    legal_form: Literal["LLC", "IE"]
    name: str
    okved_main: str
    registered_at: date
    bound_at: datetime
