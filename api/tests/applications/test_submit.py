"""Submit (#7): C1–C7 в очереди с ожидаемой рекомендацией, атомарность, сбои ext-sim, гонки."""

import asyncio
import uuid
from datetime import timedelta

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app.applications.ai_reports import recover_stale_ai_reports
from tests.applications.conftest import Pipeline, count
from tests.applications.extsim_fake import FakeExtSim

EXPECTED = {
    "C1": ("ELIGIBLE_FOR_MANAGER_REVIEW", []),
    "C2": ("COUNTER_OFFER_CANDIDATE", []),
    "C3": ("MANUAL_REVIEW", []),
    "C4": ("BLOCKED_BY_RULE", ["ACCOUNT_HISTORY_INSUFFICIENT"]),
    "C5": ("BLOCKED_BY_RULE", ["COMPANY_INACTIVE"]),
    "C6": ("BLOCKED_BY_RULE", ["ACCOUNT_BLOCKED_BY_FNS"]),
    "C7": ("MANUAL_REVIEW", []),
}

EFFECT_TABLES = ("scoring_results", "decision_proposals", "ai_reports", "external_snapshots")


async def proposal(db: AsyncEngine) -> tuple[str, list[str]]:
    async with db.connect() as conn:
        row = (
            await conn.execute(
                sa.text("SELECT suggested_action, blocking_codes FROM decision_proposals")
            )
        ).one()
    return row.suggested_action, list(row.blocking_codes)


async def effects(db: AsyncEngine) -> dict[str, int]:
    return {t: await count(db, t) for t in (*EFFECT_TABLES, "application_events")}


@pytest.mark.parametrize("code", sorted(EXPECTED))
async def test_company_lands_in_queue_with_expected_action(
    code: str, pipeline: Pipeline, db: AsyncEngine
) -> None:
    headers, draft = await pipeline.draft(code)
    response = await pipeline.submit(headers, draft["id"], draft["revision"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "UNDER_REVIEW" and body["revision"] == 3
    assert body["submitted_at"] is not None and body["allowed_actions"] == []
    assert [e["to_status"] for e in body["timeline"]] == ["DRAFT", "UNDER_REVIEW"]
    assert await proposal(db) == EXPECTED[code]
    assert await effects(db) == {
        "scoring_results": 1,
        "decision_proposals": 1,
        "ai_reports": 1,
        "external_snapshots": 4,
        "application_events": 2,
    }


async def test_c2_scoring_matches_reference(pipeline: Pipeline, db: AsyncEngine) -> None:
    await pipeline.submitted("C2")
    async with db.connect() as conn:
        row = (
            await conn.execute(
                sa.text(
                    "SELECT kind, calculation_status, monthly_payment_rub, dscr, score, "
                    "risk_level, limit_rub, s.id = a.current_scoring_id AS current "
                    "FROM scoring_results s JOIN applications a ON a.id = s.application_id"
                )
            )
        ).one()
        categories = await conn.scalar(
            sa.text("SELECT count(DISTINCT category) FROM account_transactions")
        )
    assert row.kind == "SUBMISSION" and row.calculation_status == "OK" and row.current
    assert str(row.monthly_payment_rub) == "117698.56"  # M1
    assert str(row.dscr).startswith("1.1024")
    assert (row.score, row.risk_level, str(row.limit_rub)) == (63, "MODERATE", "2340000.00")
    assert categories and categories > 1  # операции категоризированы и сохранены


async def test_c4_skipped_calculation_has_no_metrics(pipeline: Pipeline, db: AsyncEngine) -> None:
    await pipeline.submitted("C4")
    async with db.connect() as conn:
        row = (
            await conn.execute(
                sa.text("SELECT calculation_status, dscr, score FROM scoring_results")
            )
        ).one()
    assert tuple(row) == ("SKIPPED", None, None)


async def test_ai_report_is_finalized_after_commit(pipeline: Pipeline, db: AsyncEngine) -> None:
    await pipeline.submitted("C2")
    async with db.connect() as conn:
        row = (
            await conn.execute(
                sa.text(
                    "SELECT status, fallback_reason, generation_id, report_json FROM ai_reports"
                )
            )
        ).one()
    # replay (#8): записанный ответ C2 → READY; статусы и сценарий от отчёта не зависят
    assert (row.status, row.fallback_reason, row.generation_id) == ("READY", None, None)
    assert {f["code"] for f in row.report_json["risk_factors"]} == {
        "DSCR_BELOW_TARGET",
        "REVENUE_DECLINE",
    }


async def test_stale_pending_report_is_recovered(
    pipeline: Pipeline, db: AsyncEngine, app: FastAPI
) -> None:
    await pipeline.submitted("C1")
    async with db.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE ai_reports SET status = 'PENDING', report_json = NULL, "
                "fallback_reason = NULL, generation_id = gen_random_uuid(), "
                "updated_at = now() - interval '2 minutes'"
            )
        )
    assert await recover_stale_ai_reports(app.state.session_factory, 60) == 1
    assert await recover_stale_ai_reports(app.state.session_factory, 60) == 0  # идемпотентно
    async with db.connect() as conn:
        row = (await conn.execute(sa.text("SELECT status, fallback_reason FROM ai_reports"))).one()
    assert tuple(row) == ("FALLBACK", "TIMEOUT")


async def test_t1_provider_failure_keeps_draft_and_consent(
    pipeline: Pipeline, db: AsyncEngine, ext_sim: FakeExtSim
) -> None:
    headers, draft = await pipeline.draft("T1")
    key = str(uuid.uuid4())
    for _ in range(2):
        response = await pipeline.submit(headers, draft["id"], draft["revision"], key=key)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "PROVIDER_UNAVAILABLE"
    async with db.connect() as conn:
        status = await conn.scalar(sa.text("SELECT status FROM applications"))
    assert status == "DRAFT"
    assert await effects(db) == {t: 0 for t in EFFECT_TABLES} | {"application_events": 1}
    assert await count(db, "account_transactions") == 0
    assert await count(db, "idempotency_keys") == 0  # ключ освобождён
    assert await count(db, "consents") == 1
    consent_ids = {cid for source, cid in ext_sim.calls if source == "bki"}
    assert len(consent_ids) == 1  # повтор передаёт тот же consent_id


async def test_transient_failure_then_retry_with_same_key_succeeds(
    pipeline: Pipeline, db: AsyncEngine, ext_sim: FakeExtSim
) -> None:
    headers, draft = await pipeline.draft("C1")
    key = str(uuid.uuid4())
    ext_sim.fail = {"bank"}
    failed = await pipeline.submit(headers, draft["id"], draft["revision"], key=key)
    assert failed.status_code == 503
    ext_sim.fail = set()
    retried = await pipeline.submit(headers, draft["id"], draft["revision"], key=key)
    assert retried.status_code == 200 and retried.json()["status"] == "UNDER_REVIEW"
    assert await count(db, "consents") == 1
    assert await count(db, "scoring_results") == 1
    assert len({cid for source, cid in ext_sim.calls if source == "bki"}) == 1


async def test_parallel_submits_same_key_one_effect(pipeline: Pipeline, db: AsyncEngine) -> None:
    headers, draft = await pipeline.draft("C2")
    key = str(uuid.uuid4())
    responses = await asyncio.gather(
        *(pipeline.submit(headers, draft["id"], draft["revision"], key=key) for _ in range(2))
    )
    outcomes = sorted((r.status_code, r.json().get("error", {}).get("code")) for r in responses)
    assert outcomes in ([(200, None), (409, "IDEMPOTENCY_IN_PROGRESS")], [(200, None), (200, None)])
    await _one_effect(db)


async def test_parallel_submits_different_keys_one_effect(
    pipeline: Pipeline, db: AsyncEngine
) -> None:
    headers, draft = await pipeline.draft("C2")
    responses = await asyncio.gather(
        *(pipeline.submit(headers, draft["id"], draft["revision"]) for _ in range(2))
    )
    codes = sorted(r.status_code for r in responses)
    assert codes == [200, 409]
    loser = next(r for r in responses if r.status_code == 409).json()["error"]["code"]
    assert loser in {"REVISION_CONFLICT", "INVALID_STATUS_TRANSITION"}
    await _one_effect(db)


async def _one_effect(db: AsyncEngine) -> None:
    assert await effects(db) == {
        "scoring_results": 1,
        "decision_proposals": 1,
        "ai_reports": 1,
        "external_snapshots": 4,
        "application_events": 2,
    }
    async with db.connect() as conn:
        assert await conn.scalar(sa.text("SELECT revision FROM applications")) == 3


async def test_revision_change_between_fetch_and_lock_is_conflict(
    pipeline: Pipeline, db: AsyncEngine, ext_sim: FakeExtSim
) -> None:
    headers, draft = await pipeline.draft("C1")

    async def concurrent_patch() -> None:
        async with db.begin() as conn:
            await conn.execute(sa.text("UPDATE applications SET revision = revision + 1"))

    ext_sim.on_statement = concurrent_patch
    response = await pipeline.submit(headers, draft["id"], draft["revision"])
    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "REVISION_CONFLICT",
        "message": "Заявка изменилась, обновите данные",
        "details": {"current_revision": 3},
    }
    assert await effects(db) == {t: 0 for t in EFFECT_TABLES} | {"application_events": 1}
    assert await count(db, "consents") == 1


async def test_incomplete_draft(
    pipeline: Pipeline, api: httpx.AsyncClient, ext_sim: FakeExtSim
) -> None:
    headers = await pipeline.client("C1")
    draft = (await api.post("/applications", json={}, headers=headers)).json()
    response = await pipeline.submit(headers, draft["id"], 1)
    assert response.status_code == 422
    assert response.json()["error"]["details"] == {
        "missing_fields": ["purpose_code", "requested_amount_rub", "term_months", "product_id"]
    }
    assert ext_sim.calls == []


async def test_product_not_eligible(pipeline: Pipeline, api: httpx.AsyncClient) -> None:
    headers, draft = await pipeline.draft("C1")
    patched = await api.patch(
        f"/applications/{draft['id']}",
        json={"revision": 2, "purpose_code": "INVENTORY"},
        headers=headers,
    )
    response = await pipeline.submit(headers, draft["id"], patched.json()["revision"])
    assert response.status_code == 422
    assert response.json()["error"]["details"] == {
        "product_id": "investment",
        "unmet_constraints": ["PURPOSE_NOT_ALLOWED"],
    }


async def test_outdated_consent_version(pipeline: Pipeline, db: AsyncEngine) -> None:
    headers, draft = await pipeline.draft("C1")
    response = await pipeline.submit(headers, draft["id"], draft["revision"], consent="bki-v0")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CONSENT_REQUIRED"
    assert await count(db, "consents") == 0


async def test_second_submit_is_invalid_transition(pipeline: Pipeline) -> None:
    headers, body = await pipeline.submitted("C1")
    again = await pipeline.submit(headers, body["id"], body["revision"])
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"


async def test_director_mismatch_is_stop_factor(pipeline: Pipeline, db: AsyncEngine) -> None:
    headers, draft = await pipeline.draft("C1")
    async with db.begin() as conn:  # смена руководителя после привязки
        await conn.execute(
            sa.text(
                "UPDATE users SET full_name = 'Другой Человек' WHERE email LIKE 'director.tech%'"
            )
        )
    response = await pipeline.submit(headers, draft["id"], draft["revision"])
    assert response.status_code == 200
    assert await proposal(db) == ("BLOCKED_BY_RULE", ["APPLICANT_NOT_AUTHORIZED"])


async def test_repeat_submission_upserts_transactions(
    pipeline: Pipeline, db: AsyncEngine, api: httpx.AsyncClient
) -> None:
    headers, _ = await pipeline.submitted("C1")
    before = await count(db, "account_transactions")
    created = (await api.post("/applications", json={}, headers=headers)).json()
    from tests.applications.conftest import COMPANIES

    patched = (
        await api.patch(
            f"/applications/{created['id']}",
            json={"revision": 1, **COMPANIES["C1"].terms},
            headers=headers,
        )
    ).json()
    assert (await pipeline.submit(headers, created["id"], patched["revision"])).status_code == 200
    assert await count(db, "account_transactions") == before
    assert await count(db, "scoring_results") == 2


def test_statement_period_covers_two_years_before_window() -> None:
    from datetime import date

    from app.applications.submit import statement_period

    period = statement_period(date(2026, 10, 21))
    assert (period.from_, period.to) == (date(2024, 10, 1), date(2026, 9, 30))
    assert period.to - period.from_ > timedelta(days=700)
