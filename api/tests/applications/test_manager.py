"""Кабинет менеджера (#7): очередь, карточка, решения, оффер со сменой срока, дозапрос."""

import asyncio
from decimal import Decimal
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.applications.conftest import (
    Manager,
    Pipeline,
    client_keys_only,
    count,
    row_counts,
)

COMMENT = "Обоснование решения"


async def test_queue_has_all_companies_with_suggestions(
    pipeline: Pipeline, manager: Manager, api: httpx.AsyncClient
) -> None:
    for code in ("C1", "C2", "C3", "C4", "C5", "C6", "C7"):
        await pipeline.submitted(code)
    response = await api.get("/manager/applications", headers=manager.headers)
    assert response.status_code == 200
    items = response.json()
    by_inn = {i["company_inn"]: i for i in items}
    assert by_inn["0099010012"]["suggested_action"] == "ELIGIBLE_FOR_MANAGER_REVIEW"
    assert by_inn["0099020010"]["suggested_action"] == "COUNTER_OFFER_CANDIDATE"
    assert by_inn["0099060013"]["blocking_codes"] == ["ACCOUNT_BLOCKED_BY_FNS"]
    assert by_inn["009907001027"]["suggested_action"] == "MANUAL_REVIEW"
    assert [i["submitted_at"] for i in items] == sorted(i["submitted_at"] for i in items)
    filtered = await api.get(
        "/manager/applications", params={"status": "APPROVED"}, headers=manager.headers
    )
    assert filtered.json() == []


async def test_c2_card(pipeline: Pipeline, manager: Manager) -> None:
    _, body = await pipeline.submitted("C2")
    card = await manager.card(body["id"])
    assert card["revision"] == 3 and card["status"] == "UNDER_REVIEW"
    assert {s["provider"] for s in card["sources"]} == {"EGRUL", "FNS", "BKI", "BANK"}
    assert all(s["fetched_at"] for s in card["sources"])
    scoring = card["scoring"]
    assert (scoring["dscr"], scoring["score"], scoring["limit_rub"]) == ("1.10", 63, "2340000.00")
    assert scoring["cfads_monthly_rub"] == "240000.00"
    assert scoring["revenue_change_pct"] == "-8.00"
    assert scoring["account_history_months"] == 12 and len(scoring["monthly"]) == 12
    assert card["proposal"]["suggested_action"] == "COUNTER_OFFER_CANDIDATE"
    assert [t["rule"] for t in card["proposal"]["rule_trace"]] == ["R1", "R2", "R3", "R4", "R5"]
    assert card["allowed_actions"] == ["APPROVE", "COUNTER_OFFER", "REQUEST_INFO", "REJECT"]
    assert card["offer_constraints"] == {
        "min_amount_rub": "100000.00",
        "max_amount_rub": "5000000.00",
        "min_term_months": 12,
        "max_term_months": 60,
    }
    assert card["ai_report"]["status"] == "FALLBACK"
    assert card["timeline"][-1]["actor_full_name"] == "Кузнецова Анна Михайловна"


async def test_stop_factor_allows_only_reject(pipeline: Pipeline, manager: Manager) -> None:
    _, body = await pipeline.submitted("C6")
    card = await manager.card(body["id"])
    assert card["allowed_actions"] == ["REJECT"] and card["offer_constraints"] is None
    response = await manager.decide(body["id"], 3, action="APPROVE", comment=COMMENT)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ACTION_NOT_ALLOWED"


async def test_client_cannot_use_manager_routes(pipeline: Pipeline, api: httpx.AsyncClient) -> None:
    headers, body = await pipeline.submitted("C1")
    response = await api.get(f"/manager/applications/{body['id']}", headers=headers)
    assert response.status_code == 403


async def test_draft_is_invisible_to_manager(
    pipeline: Pipeline, manager: Manager, api: httpx.AsyncClient
) -> None:
    _, draft = await pipeline.draft("C1")
    response = await api.get(f"/manager/applications/{draft['id']}", headers=manager.headers)
    assert response.status_code == 404
    assert (await api.get("/manager/applications", headers=manager.headers)).json() == []


# Эталон из ишью для «Пекарни», 24%: (сумма, срок) → ожидаемое
OFFER_TABLE: list[tuple[int, int, dict[str, Any]]] = [
    (
        2_340_000,
        36,
        {"valid": True, "monthly_payment_rub": "91804.88", "dscr": "1.25", "score": 83},
    ),
    (3_000_000, 53, {"valid": False, "dscr": "1.24", "violations": ["AMOUNT_ABOVE_LIMIT"]}),
    (3_000_000, 54, {"valid": True, "monthly_payment_rub": "91356.79", "dscr": "1.25"}),
    (
        3_000_000,
        60,
        {
            "valid": True,
            "monthly_payment_rub": "86303.90",
            "dscr": "1.28",
            "limit_for_term_rub": "3190000.00",
        },
    ),
    (3_300_000, 60, {"valid": False, "violations": ["AMOUNT_ABOVE_LIMIT"]}),
]


@pytest.mark.parametrize(("amount", "term", "expected"), OFFER_TABLE)
async def test_offer_preview_table_and_no_writes(
    pipeline: Pipeline,
    manager: Manager,
    db: AsyncEngine,
    amount: int,
    term: int,
    expected: dict[str, Any],
) -> None:
    _, body = await pipeline.submitted("C2")
    before = await row_counts(db)
    response = await manager.preview(body["id"], amount, term)
    assert response.status_code == 200, response.text
    result = response.json()
    assert {k: result[k] for k in expected} == expected
    assert await row_counts(db) == before  # offer-preview ничего не пишет


@pytest.mark.parametrize(("amount", "term", "expected"), OFFER_TABLE)
async def test_counter_offer_decisions_follow_same_table(
    pipeline: Pipeline, manager: Manager, amount: int, term: int, expected: dict[str, Any]
) -> None:
    _, body = await pipeline.submitted("C2")
    response = await manager.decide(
        body["id"],
        3,
        action="COUNTER_OFFER",
        amount_rub=amount,
        term_months=term,
        client_reason_code="HIGH_DEBT_LOAD",
        comment=COMMENT,
    )
    if expected["valid"]:
        assert response.status_code == 201, response.text
        assert response.json()["status"] == "COUNTER_OFFER"
    else:
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "AMOUNT_ABOVE_LIMIT"


async def test_offer_preview_rules(pipeline: Pipeline, manager: Manager) -> None:
    _, body = await pipeline.submitted("C2")
    same = (await manager.preview(body["id"], 3_000_000, 36)).json()
    assert same["violations"] == ["AMOUNT_ABOVE_LIMIT", "OFFER_NOT_IMPROVED"]
    out = (await manager.preview(body["id"], 2_000_000, 72)).json()
    assert out["calculation_status"] == "SKIPPED" and out["violations"] == ["TERM_OUT_OF_PRODUCT"]


async def test_preview_and_decision_outside_review_are_409(
    pipeline: Pipeline, manager: Manager
) -> None:
    _, body = await pipeline.submitted("C1")
    approved = await manager.decide(body["id"], 3, action="APPROVE")
    assert approved.status_code == 201
    preview = await manager.preview(body["id"], 1_000_000, 36)
    again = await manager.decide(
        body["id"], 4, action="REJECT", client_reason_code="LOW_SCORE", comment=COMMENT
    )
    for response in (preview, again):
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"


async def test_comment_required_when_deviating_from_suggestion(
    pipeline: Pipeline, manager: Manager
) -> None:
    _, body = await pipeline.submitted("C2")  # рекомендация — встречное предложение
    missing = await manager.decide(body["id"], 3, action="APPROVE")
    assert missing.status_code == 422
    assert missing.json()["error"]["details"]["fields"][0]["field"] == "body.comment"
    ok = await manager.decide(body["id"], 3, action="APPROVE", comment=COMMENT)
    assert ok.status_code == 201 and ok.json() == {**ok.json(), "status": "APPROVED", "revision": 4}


async def test_counter_offer_accept_flow(
    pipeline: Pipeline, manager: Manager, api: httpx.AsyncClient, db: AsyncEngine
) -> None:
    headers, body = await pipeline.submitted("C2")
    decided = await manager.decide(
        body["id"],
        3,
        action="COUNTER_OFFER",
        amount_rub=2_340_000,
        client_reason_code="HIGH_DEBT_LOAD",
        comment=COMMENT,
    )
    assert decided.status_code == 201
    view = (await api.get(f"/applications/{body['id']}", headers=headers)).json()
    client_keys_only(view)
    assert view["status"] == "COUNTER_OFFER"
    assert view["allowed_actions"] == ["ACCEPT_OFFER", "DECLINE_OFFER"]
    assert view["offer"]["amount_rub"] == "2340000.00"
    assert view["offer"]["monthly_payment_rub"] == "91804.88"
    accepted = await api.post(
        f"/applications/{body['id']}/offer/accept",
        json={"revision": view["revision"]},
        headers={**headers, "Idempotency-Key": "accept-0001"},
    )
    assert accepted.status_code == 200, accepted.text
    result = accepted.json()
    client_keys_only(result)
    assert result["status"] == "APPROVED"
    assert result["requested_amount_rub"] == "3000000.00"  # исходный запрос сохранён
    assert result["monthly_payment_rub"] == "91804.88"  # текущие условия — из оффера
    async with db.connect() as conn:
        row = (
            await conn.execute(
                sa.text(
                    "SELECT s.kind, c.amount_rub, c.term_months, o.status FROM applications a "
                    "JOIN scoring_results s ON s.id = a.current_scoring_id "
                    "JOIN contracts c ON c.application_id = a.id JOIN offers o ON true"
                )
            )
        ).one()
    assert (row.kind, str(row.amount_rub), row.term_months, row.status) == (
        "COUNTER_OFFER",
        "2340000.00",
        36,
        "ACCEPTED",
    )
    card = await manager.card(body["id"])
    assert card["scoring"]["kind"] == "COUNTER_OFFER" and card["scoring"]["score"] == 83
    assert card["offers"][0]["status"] == "ACCEPTED"


async def test_counter_offer_by_term_and_decline(
    pipeline: Pipeline, manager: Manager, api: httpx.AsyncClient
) -> None:
    headers, body = await pipeline.submitted("C2")
    await manager.decide(
        body["id"],
        3,
        action="COUNTER_OFFER",
        term_months=54,
        client_reason_code="HIGH_DEBT_LOAD",
        comment=COMMENT,
    )
    view = (await api.get(f"/applications/{body['id']}", headers=headers)).json()
    assert (view["offer"]["amount_rub"], view["offer"]["term_months"]) == ("3000000.00", 54)
    assert Decimal(view["offer"]["overpayment_rub"]) > Decimal(view["overpayment_rub"])
    declined = await api.post(
        f"/applications/{body['id']}/offer/decline",
        json={"revision": view["revision"]},
        headers={**headers, "Idempotency-Key": "decline-0001"},
    )
    assert declined.status_code == 200
    assert declined.json()["status"] == "DECLINED" and declined.json()["allowed_actions"] == []


async def test_request_info_and_answer_without_rescoring(
    pipeline: Pipeline, manager: Manager, api: httpx.AsyncClient, db: AsyncEngine
) -> None:
    headers, body = await pipeline.submitted("C3")
    decided = await manager.decide(
        body["id"], 3, action="REQUEST_INFO", question_text="Чем подтвердите выручку?"
    )
    assert decided.status_code == 201 and decided.json()["status"] == "NEED_INFO"
    view = (await api.get(f"/applications/{body['id']}", headers=headers)).json()
    assert view["info_request"]["question_text"] == "Чем подтвердите выручку?"
    assert view["allowed_actions"] == ["RESPOND_INFO"]
    too_long = await api.post(
        f"/applications/{body['id']}/info-response",
        json={"revision": view["revision"], "answer_text": "x" * 2001},
        headers={**headers, "Idempotency-Key": "answer-long-1"},
    )
    assert too_long.status_code == 422
    scorings = await count(db, "scoring_results")
    answered = await api.post(
        f"/applications/{body['id']}/info-response",
        json={"revision": view["revision"], "answer_text": "Выписки за год"},
        headers={**headers, "Idempotency-Key": "answer-0001"},
    )
    assert answered.status_code == 200
    assert answered.json()["status"] == "UNDER_REVIEW"
    assert answered.json()["info_request"]["answer_text"] == "Выписки за год"
    assert await count(db, "scoring_results") == scorings  # без пересчёта
    card = await manager.card(body["id"])
    assert card["allowed_actions"]  # снова можно решать


async def test_reject_shows_client_reason(
    pipeline: Pipeline, manager: Manager, api: httpx.AsyncClient
) -> None:
    headers, body = await pipeline.submitted("C5")
    rejected = await manager.decide(
        body["id"], 3, action="REJECT", client_reason_code="COMPANY_STATUS", comment="Ликвидация"
    )
    assert rejected.status_code == 201
    view = (await api.get(f"/applications/{body['id']}", headers=headers)).json()
    client_keys_only(view)
    assert (view["status"], view["client_reason_code"]) == ("REJECTED", "COMPANY_STATUS")


async def test_parallel_decisions_one_record(
    pipeline: Pipeline, manager: Manager, manager2: Manager, db: AsyncEngine
) -> None:
    _, body = await pipeline.submitted("C1")
    responses = await asyncio.gather(
        manager.decide(body["id"], 3, action="APPROVE"),
        manager2.decide(
            body["id"], 3, action="REJECT", client_reason_code="LOW_SCORE", comment=COMMENT
        ),
    )
    assert sorted(r.status_code for r in responses) == [201, 409]
    loser = next(r for r in responses if r.status_code == 409).json()["error"]["code"]
    assert loser in {"REVISION_CONFLICT", "INVALID_STATUS_TRANSITION"}
    assert await count(db, "credit_decisions") == 1


async def test_same_decision_key_replays(
    pipeline: Pipeline, manager: Manager, db: AsyncEngine
) -> None:
    _, body = await pipeline.submitted("C1")
    first = await manager.decide(body["id"], 3, key="decision-key-1", action="APPROVE")
    second = await manager.decide(body["id"], 3, key="decision-key-1", action="APPROVE")
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert await count(db, "credit_decisions") == 1


async def test_invalid_amount_uses_json_field_path(pipeline: Pipeline, manager: Manager) -> None:
    _, body = await pipeline.submitted("C2")
    response = await manager.decide(
        body["id"],
        3,
        action="COUNTER_OFFER",
        amount_rub=0,
        client_reason_code="HIGH_DEBT_LOAD",
        comment=COMMENT,
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"]["fields"][0]["field"] == "body.amount_rub"
