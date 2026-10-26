"""AI-заключение на живой БД (#8): PENDING → READY/FALLBACK, перегенерация, восстановление,
гонки по `generation_id`, бюджет, отмена задачи, минимизация данных, обратная связь.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
import respx
import sqlalchemy as sa
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app.applications.ai_reports import generate, recover_stale_ai_reports
from app.core.config import LLMMode, Settings
from app.llm.client import OpenAICompatibleClient
from app.llm.display import format_money, format_months, format_percent
from tests.applications.conftest import COMPANIES, MANAGER, AsUser, Manager, Pipeline
from tests.llm_support import FakeLLM

C2_CODES = {"DSCR_BELOW_TARGET", "REVENUE_DECLINE"}


def c2_answer(summary: str = "Умеренный риск: DSCR {dscr}, платёж {payment}.") -> str:
    return json.dumps(
        {
            "summary": summary,
            "risk_factors": [
                {"code": "DSCR_BELOW_TARGET", "text": "DSCR {dscr} ниже целевого уровня."},
                {"code": "REVENUE_DECLINE", "text": "Выручка снизилась на {revenue_change}."},
            ],
            "positive_factors": [
                {"code": "CLEAN_CREDIT_HISTORY", "text": "Кредитная история без нарушений."}
            ],
            "manager_questions": ["С чем связано снижение выручки?"],
        },
        ensure_ascii=False,
    )


async def report_row(db: AsyncEngine) -> Any:
    async with db.connect() as conn:
        return (
            await conn.execute(
                sa.text(
                    "SELECT id, status, fallback_reason, generation_id, report_json, model_id, "
                    "context_hash, llm_mode, prompt_version, updated_at FROM ai_reports "
                    "ORDER BY created_at DESC LIMIT 1"
                )
            )
        ).one()


async def make_stale(db: AsyncEngine, report_id: uuid.UUID, generation_id: uuid.UUID) -> None:
    async with db.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE ai_reports SET status = 'PENDING', report_json = NULL, "
                "fallback_reason = NULL, model_id = NULL, generation_id = :g, "
                "updated_at = now() - interval '2 minutes' WHERE id = :id"
            ),
            {"g": generation_id, "id": report_id},
        )


def report_url(app_id: object) -> str:
    return f"/manager/applications/{app_id}/ai-report"


# --- Submit → PENDING → READY ----------------------------------------------------------


async def test_pending_is_committed_with_submit_and_card_never_waits(
    app: FastAPI, pipeline: Pipeline, manager: Manager, api: httpx.AsyncClient, db: AsyncEngine
) -> None:
    gate = asyncio.Event()
    fake = FakeLLM([c2_answer()], gate=gate)
    app.state.llm = fake
    headers, draft = await pipeline.draft("C2")
    submit = asyncio.create_task(pipeline.submit(headers, draft["id"], draft["revision"]))
    await asyncio.wait_for(fake.started.wait(), 10)  # генерация идёт после COMMIT submit

    row = await report_row(db)
    assert (row.status, row.generation_id is not None, row.report_json) == ("PENDING", True, None)
    loop = asyncio.get_running_loop()
    started = loop.time()
    card = await manager.card(draft["id"])
    pending = await api.get(report_url(draft["id"]), headers=manager.headers)
    assert loop.time() - started < 2  # карточка не ждёт провайдера
    assert card["status"] == "UNDER_REVIEW"
    assert card["ai_report"]["status"] == "PENDING" and card["ai_report"]["report"] is None
    assert pending.status_code == 200 and pending.json()["status"] == "PENDING"

    gate.set()
    assert (await submit).status_code == 200
    row = await report_row(db)
    assert (row.status, row.fallback_reason, row.generation_id) == ("READY", None, None)
    assert row.model_id == "fake/model-1" and row.prompt_version == "explain_risk/v1"
    assert len(row.context_hash) == 64
    ready = (await api.get(report_url(draft["id"]), headers=manager.headers)).json()
    assert ready["status"] == "READY"
    assert {f["code"] for f in ready["report"]["risk_factors"]} == C2_CODES
    after = await manager.card(draft["id"])
    assert after["allowed_actions"] == card["allowed_actions"]  # отчёт не влияет на действия
    assert after["revision"] == card["revision"]


async def test_numbers_are_byte_equal_to_scoring_block(
    app: FastAPI, pipeline: Pipeline, manager: Manager
) -> None:
    app.state.llm = FakeLLM(
        [
            c2_answer(
                "DSCR {dscr}, платёж {payment}, лимит {limit}, поток {cfads}, долг {debt}, "
                "выручка {revenue_change}, сумма {amount}, срок {term}."
            )
        ]
    )
    _, body = await pipeline.submitted("C2")
    card = await manager.card(body["id"])
    s, summary = card["scoring"], card["ai_report"]["report"]["summary"]
    assert summary == (
        f"DSCR {s['dscr']}, платёж {format_money(s['monthly_payment_rub'])}, "
        f"лимит {format_money(s['limit_rub'])}, поток {format_money(s['cfads_monthly_rub'])}, "
        f"долг {format_money(s['existing_debt_payments_rub'])}, "
        f"выручка {format_percent(s['revenue_change_pct'])}, "
        f"сумма {format_money(card['requested_amount_rub'], kopecks=False)}, "
        f"срок {format_months(card['term_months'])}."
    )
    assert s["dscr"] == "1.10"  # эталон C2


@pytest.mark.parametrize(
    ("answer", "check"),
    [
        (c2_answer("DSCR равен 5, всё отлично."), "digits"),
        (c2_answer("Кредит одобрен, DSCR {dscr}."), "stop_phrase"),
        (
            json.dumps(
                {
                    "summary": "Риск умеренный.",
                    "risk_factors": [{"code": "YOUNG_BUSINESS", "text": "Молодой бизнес."}],
                    "positive_factors": [],
                    "manager_questions": [],
                },
                ensure_ascii=False,
            ),
            "codes",
        ),
    ],
)
async def test_invalid_answer_never_reaches_manager(
    app: FastAPI, pipeline: Pipeline, manager: Manager, answer: str, check: str
) -> None:
    fake = FakeLLM([answer])
    app.state.llm = fake
    _, body = await pipeline.submitted("C2")
    report = (await manager.card(body["id"]))["ai_report"]
    assert (report["status"], report["fallback_reason"]) == ("FALLBACK", "INVALID_OUTPUT")
    assert len(fake.calls) == 2  # один повтор с описанием ошибки
    text = json.dumps(report["report"], ensure_ascii=False)
    assert "одобр" not in text and "YOUNG_BUSINESS" not in text and "равен 5" not in text
    assert {f["code"] for f in report["report"]["risk_factors"]} == C2_CODES


async def test_disabled_mode_gives_template(
    pipeline: Pipeline, manager: Manager, db: AsyncEngine, app: FastAPI
) -> None:
    app.state.settings = app.state.settings.model_copy(update={"llm_mode": LLMMode.DISABLED})
    from app.llm.client import DisabledClient

    app.state.llm = DisabledClient()
    _, body = await pipeline.submitted("C2")
    report = (await manager.card(body["id"]))["ai_report"]
    assert (report["status"], report["fallback_reason"]) == ("FALLBACK", "DISABLED")
    assert report["llm_mode"] == "disabled" and report["model_id"] is None
    assert {f["code"] for f in report["report"]["risk_factors"]} == C2_CODES


async def test_unreachable_provider_gives_template_and_health_ok(
    app: FastAPI,
    pipeline: Pipeline,
    manager: Manager,
    api: httpx.AsyncClient,
    make_settings: Callable[..., Settings],
) -> None:
    dead = make_settings(
        llm_mode="openai", llm_base_url="http://127.0.0.1:1/v1", llm_model="m", llm_api_key="k"
    )
    app.state.llm = OpenAICompatibleClient(dead, http_client=httpx.AsyncClient(trust_env=False))
    app.state.settings = app.state.settings.model_copy(
        update={"llm_mode": dead.llm_mode, "llm_base_url": dead.llm_base_url, "llm_model": "m"}
    )
    _, body = await pipeline.submitted("C2")
    report = (await manager.card(body["id"]))["ai_report"]
    assert (report["status"], report["fallback_reason"]) == ("FALLBACK", "UNAVAILABLE")
    health = (await api.get("/health")).json()
    assert health["status"] == "ok" and health["llm"] == "ok"
    for _ in range(5):  # пять сбоев подряд — breaker открыт, health показывает degraded
        app.state.llm.breaker.record_failure()
    assert (await api.get("/health")).json() == {
        "status": "ok",
        "db": "ok",
        "ext_sim": "ok",
        "llm": "degraded",
    }


# --- POST/GET ai-report ----------------------------------------------------------------


async def test_post_returns_existing_and_regenerate_starts_new_generation(
    app: FastAPI, pipeline: Pipeline, manager: Manager, api: httpx.AsyncClient, db: AsyncEngine
) -> None:
    fake = FakeLLM([c2_answer("Первая версия: DSCR {dscr}."), c2_answer("Вторая: DSCR {dscr}.")])
    app.state.llm = fake
    _, body = await pipeline.submitted("C2")
    url = report_url(body["id"])
    before = await report_row(db)

    same = await api.post(url, headers=manager.headers)
    assert same.status_code == 200 and same.json()["status"] == "READY"
    assert len(fake.calls) == 1  # READY без regenerate — без нового запуска

    regen = await api.post(url, params={"regenerate": "true"}, headers=manager.headers)
    assert regen.status_code == 202
    assert regen.json()["status"] == "PENDING" and regen.json()["report"] is None
    after = await report_row(db)
    assert after.id == before.id and after.status == "READY"  # задача уже отработала
    assert after.report_json["summary"] == "Вторая: DSCR 1.10."
    assert after.updated_at > before.updated_at
    assert len(fake.calls) == 2
    card = await manager.card(body["id"])
    assert card["revision"] == body["revision"]  # не меняет revision заявки


async def test_fresh_pending_is_returned_without_new_run(
    app: FastAPI, pipeline: Pipeline, manager: Manager, api: httpx.AsyncClient, db: AsyncEngine
) -> None:
    app.state.llm = FakeLLM([c2_answer()])
    _, body = await pipeline.submitted("C2")
    row = await report_row(db)
    gen = uuid.uuid4()
    async with db.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE ai_reports SET status = 'PENDING', report_json = NULL, "
                "generation_id = :g, updated_at = now() WHERE id = :id"
            ),
            {"g": gen, "id": row.id},
        )
    fake = FakeLLM([c2_answer()])
    app.state.llm = fake
    for params in ({}, {"regenerate": "true"}):
        response = await api.post(report_url(body["id"]), params=params, headers=manager.headers)
        assert response.status_code == 200 and response.json()["status"] == "PENDING"
    assert fake.calls == [] and (await report_row(db)).generation_id == gen


async def test_stale_pending_post_starts_new_generation(
    app: FastAPI, pipeline: Pipeline, manager: Manager, api: httpx.AsyncClient, db: AsyncEngine
) -> None:
    app.state.llm = FakeLLM([c2_answer()])
    _, body = await pipeline.submitted("C2")
    row = await report_row(db)
    await make_stale(db, row.id, uuid.uuid4())
    response = await api.post(report_url(body["id"]), headers=manager.headers)
    assert response.status_code == 202
    assert (await report_row(db)).status == "READY"


async def test_report_not_found_cases(
    pipeline: Pipeline, manager: Manager, api: httpx.AsyncClient
) -> None:
    _, draft = await pipeline.draft("C2")  # черновик: заключения ещё нет
    for method in ("GET", "POST"):
        for app_id in (draft["id"], uuid.uuid4()):
            response = await api.request(method, report_url(app_id), headers=manager.headers)
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_get_returns_exactly_db_state(
    app: FastAPI, pipeline: Pipeline, manager: Manager, api: httpx.AsyncClient, db: AsyncEngine
) -> None:
    app.state.llm = FakeLLM([c2_answer()])
    _, body = await pipeline.submitted("C2")
    stored = {
        "summary": "Сохранено в БД.",
        "risk_factors": [],
        "positive_factors": [],
        "manager_questions": [],
    }
    async with db.begin() as conn:
        await conn.execute(
            sa.text("UPDATE ai_reports SET report_json = CAST(:r AS jsonb)"),
            {"r": json.dumps(stored, ensure_ascii=False)},
        )
    response = await api.get(report_url(body["id"]), headers=manager.headers)
    assert response.json()["report"] == stored  # GET ничего не пересчитывает


# --- Восстановление, гонки, бюджет, отмена ---------------------------------------------


async def test_old_generation_after_recovery_is_discarded(
    app: FastAPI,
    pipeline: Pipeline,
    db: AsyncEngine,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    app.state.llm = FakeLLM([c2_answer()])
    await pipeline.submitted("C2")
    row = await report_row(db)
    old_gen = uuid.uuid4()
    await make_stale(db, row.id, old_gen)
    gate = asyncio.Event()
    slow = FakeLLM([c2_answer("Поздний ответ: DSCR {dscr}.")], gate=gate)
    task = asyncio.create_task(generate(app.state.session_factory, slow, 60, row.id, old_gen))
    await asyncio.wait_for(slow.started.wait(), 5)

    assert await recover_stale_ai_reports(app.state.session_factory, 60) == 1
    recovered = await report_row(db)
    assert (recovered.status, recovered.fallback_reason, recovered.generation_id) == (
        "FALLBACK",
        "TIMEOUT",
        None,
    )
    gate.set()
    await task
    final = await report_row(db)
    assert (final.status, final.fallback_reason) == ("FALLBACK", "TIMEOUT")
    assert "Поздний ответ" not in json.dumps(final.report_json, ensure_ascii=False)
    assert "ai_report.stale_result_discarded" in caplog.text + capsys.readouterr().out


async def test_old_generation_after_regenerate_is_discarded(
    app: FastAPI, pipeline: Pipeline, manager: Manager, api: httpx.AsyncClient, db: AsyncEngine
) -> None:
    app.state.llm = FakeLLM([c2_answer()])
    _, body = await pipeline.submitted("C2")
    row = await report_row(db)
    old_gen = uuid.uuid4()
    await make_stale(db, row.id, old_gen)
    gate = asyncio.Event()
    slow = FakeLLM([c2_answer("Старая генерация: DSCR {dscr}.")], gate=gate)
    task = asyncio.create_task(generate(app.state.session_factory, slow, 60, row.id, old_gen))
    await asyncio.wait_for(slow.started.wait(), 5)

    app.state.llm = FakeLLM([c2_answer("Новая генерация: DSCR {dscr}.")])
    regen = await api.post(
        report_url(body["id"]), params={"regenerate": "true"}, headers=manager.headers
    )
    assert regen.status_code == 202
    gate.set()
    await task
    final = await report_row(db)
    assert final.status == "READY"
    assert final.report_json["summary"] == "Новая генерация: DSCR 1.10."


async def test_concurrent_regenerate_starts_one_generation(
    app: FastAPI, pipeline: Pipeline, manager: Manager, api: httpx.AsyncClient, db: AsyncEngine
) -> None:
    app.state.llm = FakeLLM([c2_answer()])
    _, body = await pipeline.submitted("C2")
    gate = asyncio.Event()
    fake = FakeLLM([c2_answer()], gate=gate)
    app.state.llm = fake
    url = report_url(body["id"])
    posts = [
        asyncio.create_task(api.post(url, params={"regenerate": "true"}, headers=manager.headers))
        for _ in range(5)
    ]
    await asyncio.wait_for(fake.started.wait(), 10)
    await asyncio.sleep(0.3)  # остальные POST видят свежий PENDING под FOR UPDATE
    gate.set()
    codes = sorted(r.status_code for r in await asyncio.gather(*posts))
    assert codes == [200, 200, 200, 200, 202]
    assert len(fake.calls) == 1
    assert (await report_row(db)).status == "READY"


async def test_provider_slower_than_budget_gives_timeout_fallback(
    app: FastAPI, pipeline: Pipeline, manager: Manager, db: AsyncEngine
) -> None:
    app.state.settings = app.state.settings.model_copy(update={"llm_report_deadline_seconds": 0.3})
    app.state.llm = FakeLLM([c2_answer()], delay=10)
    loop = asyncio.get_running_loop()
    started = loop.time()
    _, body = await pipeline.submitted("C2")
    assert loop.time() - started < 5
    report = (await manager.card(body["id"]))["ai_report"]
    assert (report["status"], report["fallback_reason"]) == ("FALLBACK", "TIMEOUT")
    assert {f["code"] for f in report["report"]["risk_factors"]} == C2_CODES


async def test_cancelled_generation_leaves_pending_for_recovery(
    app: FastAPI, pipeline: Pipeline, db: AsyncEngine
) -> None:
    app.state.llm = FakeLLM([c2_answer()])
    await pipeline.submitted("C2")
    row = await report_row(db)
    gen = uuid.uuid4()
    await make_stale(db, row.id, gen)
    gate = asyncio.Event()
    slow = FakeLLM([c2_answer()], gate=gate)
    task = asyncio.create_task(generate(app.state.session_factory, slow, 60, row.id, gen))
    await asyncio.wait_for(slow.started.wait(), 5)
    task.cancel()  # остановка процесса посреди вызова модели
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await report_row(db)).status == "PENDING"
    assert await recover_stale_ai_reports(app.state.session_factory, 60) == 1
    final = await report_row(db)
    assert (final.status, final.fallback_reason, final.generation_id) == (
        "FALLBACK",
        "TIMEOUT",
        None,
    )


async def test_recovery_runs_at_startup(
    pipeline: Pipeline, db: AsyncEngine, app: FastAPI, settings: Settings
) -> None:
    from app.main import create_app

    app.state.llm = FakeLLM([c2_answer()])
    await pipeline.submitted("C2")
    row = await report_row(db)
    await make_stale(db, row.id, uuid.uuid4())
    restarted = create_app(settings)
    restarted.state.recovery_interval = 3600.0  # первый проход — сразу при старте
    async with restarted.router.lifespan_context(restarted):
        for _ in range(50):
            if (await report_row(db)).status != "PENDING":
                break
            await asyncio.sleep(0.1)
    final = await report_row(db)
    assert (final.status, final.fallback_reason) == ("FALLBACK", "TIMEOUT")


async def test_generation_failure_never_escapes_task(
    app: FastAPI, pipeline: Pipeline, manager: Manager
) -> None:
    app.state.llm = FakeLLM([RuntimeError("модель упала")])
    _, body = await pipeline.submitted("C2")
    report = (await manager.card(body["id"]))["ai_report"]
    assert (report["status"], report["fallback_reason"]) == ("FALLBACK", "UNAVAILABLE")
    assert {f["code"] for f in report["report"]["risk_factors"]} == C2_CODES


# --- Минимизация данных ----------------------------------------------------------------

PII = (
    COMPANIES["C2"].inn,
    "Пекарня Плюс",
    "Кузнецова",
    "009902001009",  # ИНН руководителя
    "40702810900000000010",
    "Демо-Банк",  # контрагент выписки
)


@pytest.fixture
async def provider() -> AsyncIterator[respx.MockRouter]:
    with respx.mock(base_url="https://llm.test/v1", assert_all_called=False) as router:
        yield router


async def test_provider_never_receives_pii(
    app: FastAPI,
    pipeline: Pipeline,
    api: httpx.AsyncClient,
    make_settings: Callable[..., Settings],
    provider: respx.MockRouter,
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        is_report = body["response_format"]["json_schema"]["name"] == "risk_report"
        content = c2_answer() if is_report else json.dumps({"purpose_code": "EQUIPMENT"})
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": "m",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ],
            },
        )

    route = provider.post("/chat/completions").mock(side_effect=respond)
    live = make_settings(
        llm_mode="openai", llm_base_url="https://llm.test/v1", llm_model="m", llm_api_key="k"
    )
    app.state.llm = OpenAICompatibleClient(live, http_client=httpx.AsyncClient(trust_env=False))
    text = (
        "Я Кузнецова Анна Михайловна, ООО «Пекарня Плюс», ИНН 0099020010, счёт "
        "40702810900000000010, ИНН директора 009902001009. Нужна печь, сумму уточню"
    )
    headers = await pipeline.client("C2")
    created = (await api.post("/applications", json={}, headers=headers)).json()
    interpreted = await api.post(
        f"/applications/{created['id']}/interpret", json={"purpose_text": text}, headers=headers
    )
    assert interpreted.status_code == 200
    patched = await api.patch(
        f"/applications/{created['id']}",
        json={"revision": 1, "purpose_text": text, **COMPANIES["C2"].terms},
        headers=headers,
    )
    submitted = await pipeline.submit(headers, created["id"], patched.json()["revision"])
    assert submitted.status_code == 200
    bodies = [call.request.content.decode() for call in route.calls]
    names = sorted(json.loads(b)["response_format"]["json_schema"]["name"] for b in bodies)
    assert names == ["intent", "risk_report"]
    for body in bodies:
        decoded = json.dumps(json.loads(body), ensure_ascii=False)
        for secret in PII:
            assert secret not in decoded, secret
        assert "Нужна печь" in decoded  # сам текст потребности уходит


# --- Обратная связь --------------------------------------------------------------------


async def test_feedback_upsert_and_stats(
    app: FastAPI,
    pipeline: Pipeline,
    manager: Manager,
    manager2: Manager,
    api: httpx.AsyncClient,
    db: AsyncEngine,
    as_user: AsUser,
) -> None:
    app.state.llm = FakeLLM([c2_answer()])
    _, body = await pipeline.submitted("C2")
    report = (await manager.card(body["id"]))["ai_report"]
    url = f"/manager/applications/{body['id']}/ai-feedback"

    first = await api.post(
        url, json={"ai_report_id": report["id"], "verdict": "UP"}, headers=manager.headers
    )
    assert first.status_code == 204
    again = await api.post(
        url,
        json={"ai_report_id": report["id"], "verdict": "DOWN", "comment": "Мимо"},
        headers=manager.headers,
    )
    assert again.status_code == 204
    other = await api.post(
        url, json={"ai_report_id": report["id"], "verdict": "UP"}, headers=manager2.headers
    )
    assert other.status_code == 204
    async with db.connect() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT u.email, f.verdict, f.comment FROM ai_feedback f "
                    "JOIN users u ON u.id = f.manager_user_id ORDER BY u.email"
                )
            )
        ).all()
    assert [tuple(r) for r in rows] == [
        (MANAGER, "DOWN", "Мимо"),
        ("manager.oleg@creditflow.demo", "UP", None),
    ]
    stats = (await api.get("/manager/stats", headers=manager.headers)).json()
    assert stats["ai_feedback_groups"] == [
        {
            "prompt_version": "explain_risk/v1",
            "model_id": "fake/model-1",
            "source": "replay",
            "total": 2,
            "up_count": 1,
            "up_share": "0.50",
        }
    ]
    card = await manager.card(body["id"])
    assert card["status"] == "UNDER_REVIEW" and card["revision"] == body["revision"]

    missing = await api.post(
        url, json={"ai_report_id": str(uuid.uuid4()), "verdict": "UP"}, headers=manager.headers
    )
    assert missing.status_code == 404
    client_headers = await as_user(COMPANIES["C2"].email)
    forbidden = await api.post(
        url, json={"ai_report_id": report["id"], "verdict": "UP"}, headers=client_headers
    )
    assert forbidden.status_code == 403


async def test_feedback_for_pending_or_foreign_report_rejected(
    app: FastAPI, pipeline: Pipeline, manager: Manager, api: httpx.AsyncClient, db: AsyncEngine
) -> None:
    app.state.llm = FakeLLM([c2_answer()])
    _, c2 = await pipeline.submitted("C2")
    _, c1 = await pipeline.submitted("C1")
    c2_report = (await manager.card(c2["id"]))["ai_report"]["id"]
    foreign = await api.post(
        f"/manager/applications/{c1['id']}/ai-feedback",
        json={"ai_report_id": c2_report, "verdict": "UP"},
        headers=manager.headers,
    )
    assert foreign.status_code == 404
    await make_stale(db, uuid.UUID(c2_report), uuid.uuid4())
    pending = await api.post(
        f"/manager/applications/{c2['id']}/ai-feedback",
        json={"ai_report_id": c2_report, "verdict": "UP"},
        headers=manager.headers,
    )
    assert pending.status_code == 422
    assert pending.json()["error"]["details"]["fields"][0]["field"] == "body.ai_report_id"


async def test_regenerate_does_not_attribute_old_feedback_to_new_model(
    app: FastAPI, pipeline: Pipeline, manager: Manager, api: httpx.AsyncClient
) -> None:
    app.state.llm = FakeLLM([c2_answer()], model="old-model")
    _, body = await pipeline.submitted("C2")
    report = (await manager.card(body["id"]))["ai_report"]
    feedback_url = f"/manager/applications/{body['id']}/ai-feedback"
    assert (
        await api.post(
            feedback_url,
            headers=manager.headers,
            json={"ai_report_id": report["id"], "verdict": "UP"},
        )
    ).status_code == 204
    app.state.llm = FakeLLM([c2_answer()], model="new-model")
    assert (
        await api.post(report_url(body["id"]), params={"regenerate": True}, headers=manager.headers)
    ).status_code == 202
    stats = (await api.get("/manager/stats", headers=manager.headers)).json()
    assert stats["ai_feedback_groups"] == []
    assert (
        await api.post(
            feedback_url,
            headers=manager.headers,
            json={"ai_report_id": report["id"], "verdict": "DOWN"},
        )
    ).status_code == 204
    stats = (await api.get("/manager/stats", headers=manager.headers)).json()
    assert [(g["model_id"], g["total"], g["up_count"]) for g in stats["ai_feedback_groups"]] == [
        ("new-model", 1, 0)
    ]
