"""Жизненный цикл записи `ai_reports` со стороны конвейера (design.md §3.6, issue #7 шаг 7).

Конвейер создаёт `PENDING` с новым `generation_id` в транзакции Submit, после COMMIT
запускает генерацию и закрывает зависшие записи. Сама генерация LLM (`explain_risk`,
валидаторы, replay) — задача #8; до неё `generate` сразу пишет шаблон по кодам
(`FALLBACK`). Результат сохраняется только условным обновлением по `generation_id`:
поздний ответ никогда не перезапишет более новое состояние.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import LLMMode
from app.db.models import AiReport, ScoringResult
from app.schemas.enums import AiReportStatus, FallbackReason, ReasonCode
from app.scoring.codes import REASON_CODES

logger = logging.getLogger("app.ai_reports")

PROMPT_VERSION = "explain-v1"
STALE_GRACE = timedelta(seconds=15)  # design §3.6: порог = LLM_REPORT_DEADLINE + 15 с


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
        context_hash=scoring.inputs_hash,
        generation_id=uuid.uuid4(),
    )
    session.add(report)
    return report


def template_report(reason_codes: list[str], positive_codes: list[str]) -> dict[str, Any]:
    """Шаблон по кодам расчёта: без чисел, каждый риск-код покрыт (те же правила, что у LLM)."""

    def factors(codes: list[str]) -> list[dict[str, str]]:
        return [{"code": c, "text": REASON_CODES[ReasonCode(c)].manager_text} for c in codes]

    summary = (
        "Автоматическое заключение по кодам расчёта. Решение принимает менеджер."
        if reason_codes or positive_codes
        else "Расчёт пропущен: признаков выписки недостаточно. Решение принимает менеджер."
    )
    return {
        "summary": summary,
        "risk_factors": factors(reason_codes),
        "positive_factors": factors(positive_codes),
        "manager_questions": [],
    }


def _fallback_reason(llm_mode: str) -> FallbackReason:
    # До #8 вызова модели нет: в режиме disabled это штатно, в остальных — недоступно.
    return FallbackReason.DISABLED if llm_mode == LLMMode.DISABLED else FallbackReason.UNAVAILABLE


async def _finalize(
    session: AsyncSession, report: AiReport, generation_id: uuid.UUID, reason: FallbackReason
) -> bool:
    scoring = await session.get(ScoringResult, report.scoring_result_id)
    assert scoring is not None
    result = await session.execute(
        update(AiReport)
        .where(
            AiReport.id == report.id,
            AiReport.generation_id == generation_id,
            AiReport.status == AiReportStatus.PENDING.value,
        )
        .values(
            status=AiReportStatus.FALLBACK.value,
            fallback_reason=reason.value,
            report_json=template_report(scoring.reason_codes, scoring.positive_codes),
            generation_id=None,
            updated_at=datetime.now(UTC),
        )
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def generate(
    sessions: async_sessionmaker[AsyncSession], report_id: uuid.UUID, generation_id: uuid.UUID
) -> None:
    """Фоновая задача после COMMIT; своя сессия. Любой сбой не выходит за пределы задачи."""
    try:
        async with sessions() as session, session.begin():
            report = await session.get(AiReport, report_id)
            if report is None:
                return
            if not await _finalize(
                session, report, generation_id, _fallback_reason(report.llm_mode)
            ):
                logger.info("ai_report %s: устаревшая генерация отброшена", report_id)
    except Exception:
        logger.exception("ai_report %s: генерация упала", report_id)


async def recover_stale_ai_reports(
    sessions: async_sessionmaker[AsyncSession], deadline_seconds: float
) -> int:
    """Идемпотентно: PENDING старше дедлайна + 15 с → FALLBACK TIMEOUT. При старте и раз в 15 с."""
    threshold = datetime.now(UTC) - timedelta(seconds=deadline_seconds) - STALE_GRACE
    closed = 0
    async with sessions() as session, session.begin():
        stale = await session.scalars(
            select(AiReport)
            .where(AiReport.status == AiReportStatus.PENDING.value, AiReport.updated_at < threshold)
            .with_for_update(skip_locked=True)
        )
        for report in stale:
            assert report.generation_id is not None
            if await _finalize(session, report, report.generation_id, FallbackReason.TIMEOUT):
                closed += 1
    if closed:
        logger.warning("ai_reports: закрыто зависших PENDING: %d", closed)
    return closed
