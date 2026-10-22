"""Конфигурация из переменных окружения (design.md §3.2, таблица «Конфигурация»)."""

from datetime import date
from enum import StrEnum
from functools import lru_cache
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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    # Приложение
    database_url: str = "postgresql+psycopg://creditflow@localhost:5432/creditflow"
    app_secret_key: str = ""
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
