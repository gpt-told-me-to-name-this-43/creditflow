"""Черновик заявки (#7): POST/GET/PATCH, один DRAFT, revision, источники условий, гонки."""

import asyncio
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from app.schemas.client import ClientApplicationView
from tests.applications.conftest import (
    TECHSERVICE,
    TECHSERVICE_INN,
    AsUser,
    BindCompany,
    count,
)

C2_TERMS = {
    "purpose_code": "EQUIPMENT",
    "requested_amount_rub": 3_000_000,
    "term_months": 36,
    "product_id": "investment",
    "terms_field_sources": {
        "purpose_code": "RULES",
        "requested_amount_rub": "RULES",
        "term_months": "MANUAL",
    },
}


async def create(api: httpx.AsyncClient, headers: dict[str, str], **body: Any) -> httpx.Response:
    return await api.post("/applications", json=body, headers=headers)


async def draft(api: httpx.AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    response = await create(api, headers)
    assert response.status_code in {200, 201}, response.text
    result: dict[str, Any] = response.json()
    return result


async def patch(
    api: httpx.AsyncClient, headers: dict[str, str], app_id: str, **body: Any
) -> httpx.Response:
    return await api.patch(f"/applications/{app_id}", json=body, headers=headers)


async def set_status(db: AsyncEngine, app_id: str, status: str) -> None:
    # Подготовка состояния для теста в обход API (переходы submit и далее — следующие фазы).
    async with db.begin() as conn:
        await conn.execute(
            sa.text("UPDATE applications SET status = :s WHERE id = :i"),
            {"s": status, "i": app_id},
        )


# --- POST /applications ---------------------------------------------------------------------


async def test_new_draft_does_not_save_unconfirmed_suggestions(
    api: httpx.AsyncClient, bakery: dict[str, str]
) -> None:
    response = await create(api, bakery, purpose_text="Нужно 2 млн на 3 года на новую печь")
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "DRAFT" and body["revision"] == 1
    assert body["purpose_text"] == "Нужно 2 млн на 3 года на новую печь"
    for field in ("purpose_code", "requested_amount_rub", "term_months", "product_id"):
        assert body[field] is None
    assert body["terms_field_sources"] == {} and body["terms_source"] == "MANUAL"
    assert body["allowed_actions"] == ["EDIT", "INTERPRET"]
    assert [(e["from_status"], e["to_status"]) for e in body["timeline"]] == [(None, "DRAFT")]
    assert set(body) == set(ClientApplicationView.model_fields)  # никаких внутренних полей


async def test_second_post_returns_existing_draft_without_applying_body(
    api: httpx.AsyncClient, bakery: dict[str, str], db: AsyncEngine
) -> None:
    first = await create(api, bakery, purpose_text="первый")
    second = await create(api, bakery, purpose_text="второй")
    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["purpose_text"] == "первый"
    assert await count(db, "applications") == 1
    assert await count(db, "application_events") == 1


async def test_parallel_posts_create_exactly_one_draft(
    api: httpx.AsyncClient, bakery: dict[str, str], db: AsyncEngine
) -> None:
    responses = await asyncio.gather(*(create(api, bakery) for _ in range(5)))
    assert sorted(r.status_code for r in responses) == [200, 200, 200, 200, 201]
    assert len({r.json()["id"] for r in responses}) == 1
    assert await count(db, "applications") == 1
    assert await count(db, "application_events") == 1


async def test_new_draft_allowed_when_previous_left_draft(
    api: httpx.AsyncClient, bakery: dict[str, str], db: AsyncEngine
) -> None:
    old = await draft(api, bakery)
    await set_status(db, old["id"], "UNDER_REVIEW")
    response = await create(api, bakery)
    assert response.status_code == 201
    assert response.json()["id"] != old["id"]
    listed = await api.get("/applications", headers=bakery)
    assert {a["id"] for a in listed.json()} == {old["id"], response.json()["id"]}


# --- GET ------------------------------------------------------------------------------------


async def test_foreign_application_is_404(
    api: httpx.AsyncClient,
    bakery: dict[str, str],
    as_user: AsUser,
    bind_company: BindCompany,
) -> None:
    mine = await draft(api, bakery)
    await bind_company(TECHSERVICE, TECHSERVICE_INN)
    other = await as_user(TECHSERVICE)
    assert (await api.get(f"/applications/{mine['id']}", headers=other)).status_code == 404
    response = await patch(api, other, mine["id"], revision=1, term_months=12)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert (await api.get("/applications", headers=other)).json() == []


async def test_get_does_not_change_database(
    api: httpx.AsyncClient, bakery: dict[str, str], db: AsyncEngine
) -> None:
    created = await draft(api, bakery)
    query = sa.text("SELECT revision, updated_at FROM applications")
    async with db.connect() as conn:
        before = (await conn.execute(query)).one()
    for _ in range(2):
        await api.get(f"/applications/{created['id']}", headers=bakery)
        await api.get("/applications", headers=bakery)
    async with db.connect() as conn:
        assert (await conn.execute(query)).one() == before
    assert await count(db, "application_events") == 1


# --- PATCH ----------------------------------------------------------------------------------


async def test_patch_saves_terms_and_derives_source(
    api: httpx.AsyncClient, bakery: dict[str, str]
) -> None:
    created = await draft(api, bakery)
    response = await patch(api, bakery, created["id"], revision=1, **C2_TERMS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["revision"] == 2
    assert body["requested_amount_rub"] == "3000000.00"
    assert body["terms_field_sources"] == C2_TERMS["terms_field_sources"]
    assert body["terms_source"] == "RULES_CONFIRMED"
    assert body["annual_rate_pct"] == "24.00"
    assert body["monthly_payment_rub"] == "117698.56"  # M1
    assert body["overpayment_rub"] is not None
    assert body["allowed_actions"] == ["EDIT", "INTERPRET", "SUBMIT"]
    assert body["timeline"] == created["timeline"]  # PATCH не меняет статус и не пишет событие


async def test_changed_field_without_source_becomes_manual(
    api: httpx.AsyncClient, bakery: dict[str, str]
) -> None:
    created = await draft(api, bakery)
    await patch(api, bakery, created["id"], revision=1, **C2_TERMS)
    response = await patch(api, bakery, created["id"], revision=2, requested_amount_rub=2_340_000)
    body = response.json()
    assert body["terms_field_sources"] == {
        "purpose_code": "RULES",
        "requested_amount_rub": "MANUAL",
        "term_months": "MANUAL",
    }
    assert body["terms_source"] == "RULES_CONFIRMED"
    assert body["monthly_payment_rub"] == "91804.88"  # M3


async def test_llm_source_wins_and_null_clears_field(
    api: httpx.AsyncClient, bakery: dict[str, str]
) -> None:
    created = await draft(api, bakery)
    await patch(
        api,
        bakery,
        created["id"],
        revision=1,
        purpose_code="EQUIPMENT",
        terms_field_sources={"purpose_code": "LLM"},
    )
    response = await patch(api, bakery, created["id"], revision=2, purpose_code=None)
    body = response.json()
    assert body["purpose_code"] is None
    assert body["terms_field_sources"] == {}
    assert body["terms_source"] == "MANUAL"


async def test_ineligible_product_hides_submit(
    api: httpx.AsyncClient, bakery: dict[str, str]
) -> None:
    created = await draft(api, bakery)
    terms = {**C2_TERMS, "purpose_code": "INVENTORY"}  # цель не для инвестиционного кредита
    body = (await patch(api, bakery, created["id"], revision=1, **terms)).json()
    assert "SUBMIT" not in body["allowed_actions"]


async def test_stale_revision_is_409_with_current_revision(
    api: httpx.AsyncClient, bakery: dict[str, str]
) -> None:
    created = await draft(api, bakery)
    await patch(api, bakery, created["id"], revision=1, term_months=24)
    response = await patch(api, bakery, created["id"], revision=1, term_months=48)
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "REVISION_CONFLICT"
    assert error["details"] == {"current_revision": 2}
    current = await api.get(f"/applications/{created['id']}", headers=bakery)
    assert current.json()["term_months"] == 24


async def test_patch_outside_draft_is_invalid_transition(
    api: httpx.AsyncClient, bakery: dict[str, str], db: AsyncEngine
) -> None:
    created = await draft(api, bakery)
    await set_status(db, created["id"], "UNDER_REVIEW")
    response = await patch(api, bakery, created["id"], revision=1, term_months=24)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"


async def test_unknown_product_is_validation_error(
    api: httpx.AsyncClient, bakery: dict[str, str]
) -> None:
    created = await draft(api, bakery)
    response = await patch(api, bakery, created["id"], revision=1, product_id="leasing")
    assert response.status_code == 422
    assert response.json()["error"]["details"]["fields"] == [
        {"field": "body.product_id", "code": "UNKNOWN_PRODUCT", "message": "Такого продукта нет"}
    ]


async def test_invalid_amount_uses_json_field_path(
    api: httpx.AsyncClient, bakery: dict[str, str]
) -> None:
    created = await draft(api, bakery)
    response = await patch(api, bakery, created["id"], revision=1, requested_amount_rub=0)
    assert response.status_code == 422
    assert response.json()["error"]["details"]["fields"][0]["field"] == (
        "body.requested_amount_rub"
    )


async def test_parallel_patches_with_same_revision_apply_once(
    api: httpx.AsyncClient, bakery: dict[str, str], db: AsyncEngine
) -> None:
    created = await draft(api, bakery)
    responses = await asyncio.gather(
        *(patch(api, bakery, created["id"], revision=1, term_months=t) for t in (24, 36, 48))
    )
    assert sorted(r.status_code for r in responses) == [200, 409, 409]
    assert {r.json()["error"]["code"] for r in responses if r.status_code == 409} == {
        "REVISION_CONFLICT"
    }
    async with db.connect() as conn:
        assert await conn.scalar(sa.text("SELECT revision FROM applications")) == 2
