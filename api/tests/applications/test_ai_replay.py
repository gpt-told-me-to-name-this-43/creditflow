"""Заключения C1–C7 и демо-состояния в replay (#8 «Готово, когда»): без сети — READY.

Тот же тест записывает фикстуры: `LLM_RECORD=1` (`make llm-record`) — ответы настоящего
провайдера сохраняются в `llm-replay/`, затем проверяются теми же утверждениями.
"""

import re
from collections.abc import Callable
from datetime import date
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.llm.display import format_money, format_months, format_percent
from tests.applications.conftest import COMPANIES, Manager, Pipeline
from tests.llm_support import scenario_client

TOKEN = "r" * 32
SCENARIOS = ("C1", "C2", "C3", "C4", "C5", "C6", "C7")


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(
        demo_auth_enabled=True,
        app_as_of_date=date(2026, 10, 21),
        test_reset_enabled=True,
        test_reset_token=TOKEN,
    )


@pytest.fixture
def scenario_app(app: FastAPI) -> FastAPI:
    app.state.llm = scenario_client()
    return app


def displayed_values(card: dict[str, Any]) -> set[str]:
    """Все значения, которые backend вправе подставить: формат показа блока расчёта."""
    s = card["scoring"]
    values = {format_money(s["existing_debt_payments_rub"])}
    for key in ("monthly_payment_rub", "limit_rub", "cfads_monthly_rub"):
        if s[key]:
            values.add(format_money(s[key]))
    if s["dscr"]:
        values.add(s["dscr"])
    if s["revenue_change_pct"]:
        values.add(format_percent(s["revenue_change_pct"]))
    values.add(format_money(card["requested_amount_rub"], kopecks=False))
    values.add(format_months(card["term_months"]))
    return values


def assert_report_consistent(card: dict[str, Any]) -> None:
    """Коды ⊆ расчёта, каждый риск-код покрыт, числа — только значения блока расчёта."""
    report = card["ai_report"]["report"]
    scoring = card["scoring"]
    assert sorted(f["code"] for f in report["risk_factors"]) == sorted(scoring["reason_codes"])
    assert {f["code"] for f in report["positive_factors"]} <= set(scoring["positive_codes"])
    texts = [
        report["summary"],
        *(f["text"] for f in report["risk_factors"] + report["positive_factors"]),
        *report["manager_questions"],
    ]
    allowed = displayed_values(card)
    for text in texts:
        rest = text
        for value in sorted(allowed, key=len, reverse=True):
            rest = rest.replace(value, "")
        assert not re.search(r"\d", rest), (text, allowed)
        assert not re.search(r"одобр|гарантир", text, re.IGNORECASE), text


@pytest.mark.parametrize("code", SCENARIOS)
async def test_scenario_card_shows_ready_report(
    code: str, scenario_app: FastAPI, pipeline: Pipeline, manager: Manager, settings: Settings
) -> None:
    _, body = await pipeline.submitted(code)
    card = await manager.card(body["id"])
    report = card["ai_report"]
    assert report["status"] == "READY", report
    assert report["fallback_reason"] is None
    assert report["model_id"]
    assert report["llm_mode"] == settings.llm_mode.value  # из настроек api, не из клиента
    assert report["prompt_version"] == "explain_risk/v1"
    assert card["status"] == "UNDER_REVIEW"  # заключение статус не меняет
    assert_report_consistent(card)
    assert COMPANIES[code].inn not in str(report)


async def test_demo_state_reports_are_ready(
    scenario_app: FastAPI, api: httpx.AsyncClient, db: AsyncEngine
) -> None:
    response = await api.post(
        "/_test/reset", params={"mode": "demo"}, headers={"X-Test-Reset-Token": TOKEN}
    )
    assert response.status_code == 200, response.text
    async with db.connect() as conn:
        rows = (await conn.execute(sa.text("SELECT status, fallback_reason FROM ai_reports"))).all()
    assert rows
    assert {tuple(r) for r in rows} == {("READY", None)}
