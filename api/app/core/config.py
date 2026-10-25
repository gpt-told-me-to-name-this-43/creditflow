"""Конфигурация из переменных окружения (design.md §3.2, таблица «Конфигурация»)."""

from datetime import date
from enum import StrEnum
from functools import lru_cache
from ipaddress import IPv4Network, IPv6Network
from typing import Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(StrEnum):
    LOCAL = "local"
    TEST = "test"
    PRODUCTION = "production"


class LLMMode(StrEnum):
    OPENAI = "openai"
    REPLAY = "replay"
    DISABLED = "disabled"


class StructuredOutput(StrEnum):
    JSON_SCHEMA = "json_schema"
    JSON_OBJECT = "json_object"
    PROMPT = "prompt"


# Демо-значение APP_SECRET_KEY из .env.example: допустимо только с DEMO_AUTH_ENABLED=true
# и никогда — в production (#5).
DEMO_SECRET_KEY = "local-demo-only-jwt-secret-not-for-production"
MIN_SECRET_KEY_BYTES = 32

_PRIVATE_NETWORKS: tuple[IPv4Network | IPv6Network, ...] = (
    IPv4Network("127.0.0.0/8"),
    IPv4Network("10.0.0.0/8"),
    IPv4Network("172.16.0.0/12"),
    IPv4Network("192.168.0.0/16"),
    IPv6Network("::1/128"),
)


class Settings(BaseSettings):
    # hide_input_in_errors: ошибка валидации не печатает входные значения — среди них
    # APP_SECRET_KEY, LLM_API_KEY и TEST_RESET_TOKEN.
    model_config = SettingsConfigDict(
        case_sensitive=False, extra="ignore", hide_input_in_errors=True
    )

    # Приложение
    database_url: str = "postgresql+psycopg://creditflow@localhost:5432/creditflow"
    app_secret_key: str = Field(default="", repr=False)
    demo_auth_enabled: bool = False
    app_as_of_date: date = date(2026, 10, 21)
    ext_sim_base_url: str = "http://ext-sim:8000"

    # Окружение
    app_env: AppEnv = AppEnv.LOCAL

    # LLM
    llm_mode: LLMMode = LLMMode.REPLAY
    llm_base_url: str | None = None
    llm_api_key: str | None = Field(default=None, repr=False)
    llm_model: str | None = None
    llm_model_intent: str | None = None
    llm_model_explain: str | None = None
    llm_structured_output: StructuredOutput = StructuredOutput.JSON_SCHEMA
    llm_timeout_seconds: float = Field(default=20, gt=0)
    llm_report_deadline_seconds: float = Field(default=60, gt=0)
    llm_max_concurrency: int = Field(default=4, ge=1)
    llm_temperature: float = Field(default=0, ge=0)
    llm_seed: int | None = 42

    # Тестовый контур
    test_reset_enabled: bool = False
    test_reset_token: str | None = Field(default=None, repr=False)
    load_test_enabled: bool = False

    # Адреса, от которых api принимает X-Real-IP (nginx в сети compose). Остальным
    # клиентам IP берётся из соединения: заголовок от них подделывается.
    trusted_proxy_cidrs: list[IPv4Network | IPv6Network] = Field(
        default_factory=lambda: list(_PRIVATE_NETWORKS)
    )

    @field_validator(
        "llm_base_url",
        "llm_api_key",
        "llm_model",
        "llm_model_intent",
        "llm_model_explain",
        "test_reset_token",
        "llm_seed",
        mode="before",
    )
    @classmethod
    def _empty_as_none(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def _check_secret_key(self) -> Self:
        # #5: сообщения не содержат значение ключа.
        if len(self.app_secret_key.encode()) < MIN_SECRET_KEY_BYTES:
            raise ValueError(f"APP_SECRET_KEY короче {MIN_SECRET_KEY_BYTES} байт, старт запрещён")
        if self.app_secret_key == DEMO_SECRET_KEY:
            if self.app_env is AppEnv.PRODUCTION:
                raise ValueError("APP_ENV=production: демо-значение APP_SECRET_KEY запрещено")
            if not self.demo_auth_enabled:
                raise ValueError(
                    "демо-значение APP_SECRET_KEY допустимо только с DEMO_AUTH_ENABLED=true"
                )
        return self

    @model_validator(mode="after")
    def _forbid_test_flags_in_production(self) -> Self:
        # design.md §3.2, §4: в production тестовые флаги блокируют старт.
        if self.app_env is AppEnv.PRODUCTION:
            enabled = [
                name
                for name, value in (
                    ("TEST_RESET_ENABLED", self.test_reset_enabled),
                    ("LOAD_TEST_ENABLED", self.load_test_enabled),
                )
                if value
            ]
            if enabled:
                raise ValueError(
                    f"APP_ENV=production: {', '.join(enabled)} должны быть false, старт запрещён"
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
