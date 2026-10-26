"""`POST /applications/{id}/interpret` на живой БД (#8): три режима, заявка не меняется,
доступ и статусы, медленный провайдер не тормозит остальные эндпоинты.
"""

import asyncio
import json
import statistics
import time
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
import respx
import sqlalchemy as sa
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.llm.client import DisabledClient, OpenAICompatibleClient, ReplayClient
from tests.applications.conftest import Manager, Pipeline, row_counts
from tests.llm_support import REPLAY_DIR, FakeLLM

CLEAN = "Ремонт кафе, 1,5 млн на 2 года"


def url(app_id: object) -> str:
    return f"/applications/{app_id}/interpret"


async def snapshot(db: AsyncEngine, app_id: object) -> Any:
    async with db.connect() as conn:
        return (
            await conn.execute(
                sa.text(
                    "SELECT revision, status, purpose_text, purpose_code, requested_amount_rub, "
                    "term_months, product_id, terms_source, terms_field_sources_json "
                    "FROM applications WHERE id = :id"
                ),
                {"id": app_id},
            )
        ).one()


async def test_disabled_fills_clean_phrase_and_never_changes_application(
    app: FastAPI, pipeline: Pipeline, api: httpx.AsyncClient, db: AsyncEngine
) -> None:
    app.state.llm = DisabledClient()
    headers = await pipeline.client("C2")
    created = (await api.post("/applications", json={}, headers=headers)).json()
    before, counts = await snapshot(db, created["id"]), await row_counts(db)
    response = await api.post(url(created["id"]), json={"purpose_text": CLEAN}, headers=headers)
    assert response.status_code == 200
    assert response.json() == {
        "status": "OK",
        "suggestion": {
            "purpose_code": {"value": "RENOVATION", "source": "RULES", "matched_text": "ремонт"},
            "requested_amount_rub": {
                "value": 1500000,
                "source": "RULES",
                "matched_text": "1,5 млн",
            },
            "term_months": {"value": 24, "source": "RULES", "matched_text": "на 2 года"},
        },
        "clarification_question": None,
    }
    assert await snapshot(db, created["id"]) == before  # ни поля, ни revision
    assert await row_counts(db) == counts  # ни событий, ни idempotency-записей


async def test_disabled_nothing_found_is_unavailable(
    app: FastAPI, pipeline: Pipeline, api: httpx.AsyncClient
) -> None:
    app.state.llm = DisabledClient()
    headers, draft = await pipeline.draft("C2")
    body = (
        await api.post(url(draft["id"]), json={"purpose_text": "хочу кредит"}, headers=headers)
    ).json()
    assert body["status"] == "UNAVAILABLE" and body["suggestion"] == {
        "purpose_code": None,
        "requested_amount_rub": None,
        "term_months": None,
    }


async def test_replay_uses_recorded_llm_answer_and_miss_falls_back(
    app: FastAPI, pipeline: Pipeline, api: httpx.AsyncClient
) -> None:
    app.state.llm = ReplayClient(REPLAY_DIR)
    headers, draft = await pipeline.draft("C2")
    # фраза eval-набора I19: сумму правила не узнают («милиона»), ответ записан make llm-record
    recorded = await api.post(
        url(draft["id"]),
        json={"purpose_text": "хачу 3 милиона на новый станок на 2 года"},
        headers=headers,
    )
    body = recorded.json()
    assert body["suggestion"]["requested_amount_rub"] == {
        "value": 3000000,
        "source": "LLM",
        "matched_text": None,
    }
    assert body["suggestion"]["purpose_code"]["source"] == "RULES"
    miss = await api.post(
        url(draft["id"]), json={"purpose_text": "непонятный текст без фиксации"}, headers=headers
    )
    assert miss.status_code == 200 and miss.json()["status"] == "UNAVAILABLE"


async def test_openai_mode_with_mocked_model(
    app: FastAPI, pipeline: Pipeline, api: httpx.AsyncClient
) -> None:
    fake = FakeLLM(
        [
            json.dumps(
                {
                    "purpose_code": "EQUIPMENT",
                    "requested_amount_rub": 400000,
                    "term_months": None,
                    "clarification_question": "На какой срок нужен кредит?",
                },
                ensure_ascii=False,
            )
        ]
    )
    app.state.llm = fake
    headers, draft = await pipeline.draft("C2")
    body = (
        await api.post(
            url(draft["id"]), json={"purpose_text": "печка новая, тыщ 400"}, headers=headers
        )
    ).json()
    assert body["status"] == "NEEDS_CLARIFICATION"
    assert body["suggestion"]["purpose_code"]["source"] == "RULES"
    assert body["suggestion"]["requested_amount_rub"]["source"] == "LLM"
    assert body["clarification_question"] == "На какой срок нужен кредит?"
    [call] = fake.calls
    assert call.task.value == "extract_intent" and call.prompt_version == "v1"


async def test_provider_timeout_returns_rules(
    app: FastAPI, pipeline: Pipeline, api: httpx.AsyncClient
) -> None:
    app.state.settings = app.state.settings.model_copy(update={"llm_timeout_seconds": 0.3})
    app.state.llm = FakeLLM(["{}"], delay=10)
    headers, draft = await pipeline.draft("C2")
    started = time.perf_counter()
    response = await api.post(
        url(draft["id"]), json={"purpose_text": "нужно 2 млн на ремонт"}, headers=headers
    )
    assert time.perf_counter() - started < 2
    body = response.json()
    assert response.status_code == 200 and body["status"] == "NEEDS_CLARIFICATION"
    assert body["suggestion"]["requested_amount_rub"]["source"] == "RULES"


async def test_interpret_only_in_draft_and_only_own(
    app: FastAPI,
    pipeline: Pipeline,
    api: httpx.AsyncClient,
    manager: Manager,
) -> None:
    app.state.llm = DisabledClient()
    headers, submitted = await pipeline.submitted("C2")
    response = await api.post(url(submitted["id"]), json={"purpose_text": CLEAN}, headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
    other = await pipeline.client("C1")
    foreign = await api.post(url(submitted["id"]), json={"purpose_text": CLEAN}, headers=other)
    assert foreign.status_code == 404
    unknown = await api.post(url(uuid.uuid4()), json={"purpose_text": CLEAN}, headers=headers)
    assert unknown.status_code == 404
    as_manager = await api.post(
        url(submitted["id"]), json={"purpose_text": CLEAN}, headers=manager.headers
    )
    assert as_manager.status_code == 403


async def test_unbound_client_gets_company_not_bound(
    api: httpx.AsyncClient, as_user: Callable[[str], Any]
) -> None:
    headers = await as_user("director.newstart@creditflow.demo")
    response = await api.post(url(uuid.uuid4()), json={"purpose_text": CLEAN}, headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "COMPANY_NOT_BOUND"


async def test_interpret_text_limit(pipeline: Pipeline, api: httpx.AsyncClient) -> None:
    headers, draft = await pipeline.draft("C2")
    response = await api.post(url(draft["id"]), json={"purpose_text": "x" * 1001}, headers=headers)
    assert response.status_code == 422
    assert response.json()["error"]["details"]["fields"][0]["field"] == "body.purpose_text"
    ok = await api.post(url(draft["id"]), json={"purpose_text": "x" * 1000}, headers=headers)
    assert ok.status_code == 200


# --- 20 параллельных /interpret и медленный провайдер ----------------------------------


@pytest.fixture
async def slow_provider() -> AsyncIterator[respx.MockRouter]:
    async def respond(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1.5)
        content = json.dumps(
            {
                "purpose_code": None,
                "requested_amount_rub": None,
                "term_months": None,
                "clarification_question": None,
            }
        )
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": "slow",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ],
            },
        )

    with respx.mock(base_url="https://slow.test/v1", assert_all_called=False) as router:
        router.post("/chat/completions").mock(side_effect=respond)
        yield router


async def test_parallel_interpret_with_slow_provider_keeps_other_endpoints_fast(
    app: FastAPI,
    pipeline: Pipeline,
    api: httpx.AsyncClient,
    manager: Manager,
    make_settings: Callable[..., Settings],
    slow_provider: respx.MockRouter,
) -> None:
    """issue #8: 20 параллельных interpret, провайдер отвечает 1,5 с, LLM_MAX_CONCURRENCY=4.
    Чтение заявки и очереди — в SLO #5 (p95 ≤ 200 мс): interpret не держит соединения
    пула, пока ждёт модель."""
    live = make_settings(
        llm_mode="openai",
        llm_base_url="https://slow.test/v1",
        llm_model="slow",
        llm_timeout_seconds=5,
        llm_max_concurrency=4,
    )
    app.state.llm = OpenAICompatibleClient(live, http_client=httpx.AsyncClient(trust_env=False))
    headers, draft = await pipeline.draft("C2")
    statuses: list[int] = []

    async def interpret() -> None:
        response = await api.post(
            url(draft["id"]), json={"purpose_text": "нужно на ремонт"}, headers=headers
        )
        statuses.append(response.status_code)

    load = [asyncio.create_task(interpret()) for _ in range(20)]
    await asyncio.sleep(0.2)  # interpret-ы уже ждут провайдера
    latencies: list[float] = []
    while not all(t.done() for t in load):
        for method_url, auth in (
            (f"/applications/{draft['id']}", headers),
            ("/manager/applications", manager.headers),
        ):
            started = time.perf_counter()
            response = await api.get(method_url, headers=auth)
            latencies.append(time.perf_counter() - started)
            assert response.status_code == 200
        await asyncio.sleep(0.05)
    await asyncio.gather(*load)
    assert statuses == [200] * 20
    assert len(latencies) >= 20
    p95 = statistics.quantiles(latencies, n=20)[-1]
    assert p95 <= 0.2, p95
    assert slow_provider.calls.call_count == 20
