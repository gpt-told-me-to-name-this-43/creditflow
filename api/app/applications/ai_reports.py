"""Жизненный цикл `ai_reports` (design.md §3.6; конвейер — #7, генерация — #8).

- `new_pending` — запись `PENDING` с новым `generation_id` в транзакции Submit.
- `generate` — фоновая задача после COMMIT со своей сессией: `explain_risk` под общим
  бюджетом `LLM_REPORT_DEADLINE_SECONDS`, любой сбой → `FALLBACK` с шаблоном.
- `request_generation` — `POST …/ai-report` (и `?regenerate=true`) под `SELECT … FOR UPDATE`.
- `recover_stale_ai_reports` — зависший `PENDING` → `FALLBACK (TIMEOUT)`.

Результат сохраняется только условным обновлением
`WHERE id = :id AND generation_id = :gen AND status = 'PENDING'`: 0 строк — результат
устарел (восстановление или перегенерация сменили `generation_id`), он отбрасывается
и пишется в лог `ai_report.stale_result_discarded`. Соединение с БД на время вызова
модели не удерживается. Отчёт не влияет на статус заявки и `allowed_actions`.
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.applications.scoring_store import ScoringInputs
from app.core.config import LLMMode
from app.core.errors import AppError
from app.core.logs import get_logger
from app.db.models import AiFeedback, AiReport, Application, Company, ScoringResult, User
from app.llm.base import LLMClient, LlmTask, context_hash
from app.llm.explain import (
    PROMPT_LABEL,
    ExplainOutcome,
    ReportInputs,
    explain,
    explain_context,
    render_template,
)
from app.llm.explain import PROMPT_VERSION as EXPLAIN_VERSION
from app.manager.views import scoring_view
from app.schemas.common import ErrorCode, ValidationDetail, ValidationDetails
from app.schemas.enums import AiReportStatus, FallbackReason

logger = get_logger("app.ai_reports")

PROMPT_VERSION = PROMPT_LABEL
STALE_GRACE = timedelta(seconds=15)  # design §3.6: порог = LLM_REPORT_DEADLINE + 15 с


def stale_threshold(deadline_seconds: float) -> timedelta:
    return timedelta(seconds=deadline_seconds) + STALE_GRACE


def new_pending(
    session: AsyncSession, application_id: uuid.UUID, scoring: ScoringResult, llm_mode: LLMMode
) -> AiReport:
    report = AiReport(
        id=uuid.uuid4(),
        application_id=application_id,
        scoring_result_id=scoring.id,
        status=AiReportStatus.PENDING.value,
        llm_mode=llm_mode.value,
        prompt_version=PROMPT_VERSION,
        context_hash=scoring.inputs_hash,  # до генерации; финальное значение — хеш контекста
        generation_id=uuid.uuid4(),
    )
    session.add(report)
    return report


async def load_inputs(session: AsyncSession, report: AiReport) -> ReportInputs:
    """Расчёт карточки и условия заявки; ФИО и название — только для маскирования."""
    scoring = await session.get(ScoringResult, report.scoring_result_id)
    application = await session.get(Application, report.application_id)
    assert scoring is not None and application is not None
    company = await session.get(Company, application.company_id)
    owner = await session.get(User, application.owner_user_id)
    inputs = ScoringInputs.from_json(scoring.inputs_json)
    return ReportInputs(
        scoring=scoring_view(scoring),
        purpose_code=application.purpose_code,
        product_id=inputs.product_id,
        amount_rub=int(inputs.amount_rub),
        term_months=inputs.term_months,
        client_text=application.purpose_text,
        person_names=(owner.full_name,) if owner else (),
        company_names=(company.name,) if company else (),
    )


async def _save(
    session: AsyncSession,
    report_id: uuid.UUID,
    generation_id: uuid.UUID,
    outcome: ExplainOutcome,
) -> bool:
    result = await session.execute(
        update(AiReport)
        .where(
            AiReport.id == report_id,
            AiReport.generation_id == generation_id,
            AiReport.status == AiReportStatus.PENDING.value,
        )
        .values(
            status=(AiReportStatus.READY if outcome.ready else AiReportStatus.FALLBACK).value,
            fallback_reason=outcome.fallback_reason.value if outcome.fallback_reason else None,
            report_json=outcome.body.model_dump(mode="json"),
            model_id=outcome.model_id,
            context_hash=outcome.context_hash,
            generation_id=None,
            updated_at=datetime.now(UTC),
        )
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def generate(
    sessions: async_sessionmaker[AsyncSession],
    llm: LLMClient,
    deadline_seconds: float,
    report_id: uuid.UUID,
    generation_id: uuid.UUID,
) -> None:
    """Фоновая задача после COMMIT; своя сессия. Любой сбой не выходит за пределы задачи."""
    log = logger.bind(ai_report_id=str(report_id), generation_id=str(generation_id))
    try:
        async with sessions() as session:
            async with session.begin():
                report = await session.get(AiReport, report_id)
                if report is None or report.generation_id != generation_id:
                    log.info("ai_report.stale_result_discarded", stage="start")
                    return
                inputs = await load_inputs(session, report)
                llm_mode = report.llm_mode
            # транзакция закрыта: соединение не держится, пока ждём провайдера
            outcome = await _run(llm, inputs, llm_mode, deadline_seconds, log)
            async with session.begin():
                saved = await _save(session, report_id, generation_id, outcome)
        if saved:
            log.info(
                "ai_report.saved",
                status="READY" if outcome.ready else "FALLBACK",
                fallback_reason=outcome.fallback_reason.value if outcome.fallback_reason else None,
                model=outcome.model_id,
                context_hash=outcome.context_hash,
            )
        else:
            log.info("ai_report.stale_result_discarded", stage="save")
    except Exception:
        log.exception("ai_report.generation_failed")


async def _run(
    llm: LLMClient, inputs: ReportInputs, llm_mode: str, deadline_seconds: float, log: Any
) -> ExplainOutcome:
    template = ExplainOutcome(body=render_template(inputs), context_hash="")
    if llm_mode == LLMMode.DISABLED or llm.mode == LLMMode.DISABLED:
        template.fallback_reason = FallbackReason.DISABLED
        return _with_hash(template, inputs)
    try:
        async with asyncio.timeout(deadline_seconds):
            return await explain(llm, inputs)
    except TimeoutError:
        template.fallback_reason = FallbackReason.TIMEOUT
    except Exception as exc:
        log.error("ai_report.explain_failed", error_type=type(exc).__name__)
        template.fallback_reason = FallbackReason.UNAVAILABLE
    return _with_hash(template, inputs)


def _with_hash(outcome: ExplainOutcome, inputs: ReportInputs) -> ExplainOutcome:
    outcome.context_hash = context_hash(
        LlmTask.EXPLAIN_RISK, EXPLAIN_VERSION, explain_context(inputs)
    )
    return outcome


async def _template_fallback(
    session: AsyncSession, report: AiReport, reason: FallbackReason
) -> bool:
    assert report.generation_id is not None
    inputs = await load_inputs(session, report)
    outcome = _with_hash(ExplainOutcome(body=render_template(inputs), context_hash=""), inputs)
    outcome.fallback_reason = reason
    return await _save(session, report.id, report.generation_id, outcome)


async def recover_stale_ai_reports(
    sessions: async_sessionmaker[AsyncSession], deadline_seconds: float
) -> int:
    """Идемпотентно: PENDING старше бюджета + 15 с → FALLBACK TIMEOUT. При старте и раз в 15 с.

    Живая задача к этому моменту уже завершилась по бюджету; если она всё же допишет
    результат позже, условное обновление по сброшенному `generation_id` его отбросит.
    """
    threshold = datetime.now(UTC) - stale_threshold(deadline_seconds)
    closed = 0
    async with sessions() as session, session.begin():
        stale = await session.scalars(
            select(AiReport)
            .where(AiReport.status == AiReportStatus.PENDING.value, AiReport.updated_at < threshold)
            .with_for_update(skip_locked=True)
        )
        for report in list(stale):
            if await _template_fallback(session, report, FallbackReason.TIMEOUT):
                closed += 1
    if closed:
        logger.warning("ai_reports.recovered_stale", closed=closed)
    return closed


# --- API менеджера ---------------------------------------------------------------------


def _latest(application_id: uuid.UUID) -> Any:
    return (
        select(AiReport)
        .where(AiReport.application_id == application_id)
        .order_by(AiReport.created_at.desc())
        .limit(1)
    )


async def get_report(session: AsyncSession, application_id: uuid.UUID) -> AiReport:
    """`GET …/ai-report`: ровно то, что в БД. Нет заявки или заключения — 404."""
    report: AiReport | None = await session.scalar(_latest(application_id))
    if report is None:
        raise AppError(ErrorCode.NOT_FOUND, "AI-заключение не найдено")
    return report


@dataclass(frozen=True)
class GenerationRequest:
    report: AiReport
    started: bool  # True → 202 и фоновая задача после COMMIT


async def request_generation(
    session: AsyncSession,
    application_id: uuid.UUID,
    *,
    regenerate: bool,
    llm_mode: LLMMode,
    deadline_seconds: float,
) -> GenerationRequest:
    """`POST …/ai-report` под `SELECT … FOR UPDATE` на запись заключения (design §3.6)."""
    async with session.begin():
        report: AiReport | None = await session.scalar(
            _latest(application_id).with_for_update().execution_options(populate_existing=True)
        )
        if report is None:
            raise AppError(ErrorCode.NOT_FOUND, "AI-заключение не найдено")
        now = datetime.now(UTC)
        if report.status == AiReportStatus.PENDING.value:
            if now - report.updated_at < stale_threshold(deadline_seconds):
                return GenerationRequest(report, started=False)
        elif not regenerate:
            return GenerationRequest(report, started=False)
        report.status = AiReportStatus.PENDING.value
        report.generation_id = uuid.uuid4()
        report.report_json = None
        report.fallback_reason = None
        report.model_id = None
        report.llm_mode = llm_mode.value
        report.prompt_version = PROMPT_VERSION
        report.updated_at = now
        # Оценка относится к показанному тексту. После замены текста она не должна
        # попадать в агрегат новой модели/версии. Блокировка отчёта общая с feedback.
        await session.execute(delete(AiFeedback).where(AiFeedback.ai_report_id == report.id))
    return GenerationRequest(report, started=True)


async def upsert_feedback(
    session: AsyncSession,
    application_id: uuid.UUID,
    manager_id: uuid.UUID,
    ai_report_id: uuid.UUID,
    verdict: str,
    comment: str | None,
) -> None:
    """Повторная оценка того же менеджера заменяет предыдущую. Статус и расчёт не меняются."""
    async with session.begin():
        report = await session.get(AiReport, ai_report_id, with_for_update=True)
        if report is None or report.application_id != application_id:
            raise AppError(ErrorCode.NOT_FOUND, "AI-заключение не найдено")
        if report.status == AiReportStatus.PENDING.value:
            message = "Заключение ещё готовится: оценить можно READY или FALLBACK"
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                message,
                ValidationDetails(
                    fields=[
                        ValidationDetail(
                            field="body.ai_report_id", code="AI_REPORT_PENDING", message=message
                        )
                    ]
                ),
            )
        stmt = insert(AiFeedback).values(
            ai_report_id=ai_report_id,
            manager_user_id=manager_id,
            verdict=verdict,
            comment=comment,
        )
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=["ai_report_id", "manager_user_id"],
                set_={
                    "verdict": stmt.excluded.verdict,
                    "comment": stmt.excluded.comment,
                    "created_at": datetime.now(UTC),
                },
            )
        )
