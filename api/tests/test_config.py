import pytest
from pydantic import ValidationError

from app.core.config import LLMMode, Settings
from app.main import create_app


@pytest.mark.parametrize("flag", ["TEST_RESET_ENABLED", "LOAD_TEST_ENABLED"])
def test_production_with_test_flag_blocks_startup(
    monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(flag, "true")
    with pytest.raises(ValidationError, match=flag):
        create_app()


def test_production_without_test_flags_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("TEST_RESET_ENABLED", "false")
    monkeypatch.setenv("LOAD_TEST_ENABLED", "false")
    create_app()


@pytest.mark.parametrize("env", ["local", "test"])
def test_test_flags_allowed_outside_production(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    monkeypatch.setenv("APP_ENV", env)
    monkeypatch.setenv("TEST_RESET_ENABLED", "true")
    monkeypatch.setenv("LOAD_TEST_ENABLED", "true")
    create_app()


def test_defaults_match_design(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LLM_MODE", "LLM_TIMEOUT_SECONDS", "APP_AS_OF_DATE"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings()
    assert settings.llm_mode is LLMMode.REPLAY
    assert settings.llm_timeout_seconds == 20
    assert settings.llm_report_deadline_seconds == 60
    assert settings.app_as_of_date.isoformat() == "2026-10-21"


def test_empty_optional_values_become_none(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "TEST_RESET_TOKEN"):
        monkeypatch.setenv(name, "")
    settings = Settings()
    assert settings.llm_base_url is None
    assert settings.llm_api_key is None
    assert settings.test_reset_token is None


def test_secrets_not_in_repr() -> None:
    settings = Settings(llm_api_key="sk-secret", test_reset_token="t" * 32)
    assert "sk-secret" not in repr(settings)
    assert "t" * 32 not in repr(settings)


def test_env_example_matches_settings() -> None:
    """Каждая переменная приложения из .env.example известна Settings, и наоборот."""
    from .conftest import REPO_ROOT

    names = {
        line.split("=", 1)[0]
        for line in (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    }
    app_names = {n for n in names if not n.startswith("POSTGRES_")}
    assert app_names == {f.upper() for f in Settings.model_fields}


def test_env_example_demo_secret_is_long_enough() -> None:
    from .conftest import REPO_ROOT

    values = dict(
        line.split("=", 1)
        for line in (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    assert len(values["APP_SECRET_KEY"].encode()) >= 32
