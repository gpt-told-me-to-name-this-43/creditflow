"""Сводка менеджера `GET /manager/stats` (design §3.5, issue #7 «Сводка менеджера»).

- `applications_by_status` — все заявки по статусам;
- `median_time_to_decision_seconds` — медиана от Submit до первого решения менеджера;
- `suggested_action_distribution` — рекомендации заявок в `UNDER_REVIEW`;
- `decisions_matching_suggestion_share` — доля решений, совпавших с рекомендацией;
- `ai_feedback_*` — доля 👍 по `prompt_version`, модели и источнику (оценки — из #8).
"""

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Integer, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AiFeedback,
    AiReport,
    Application,
    CreditDecision,
    DecisionProposal,
    ScoringResult,
)
from app.manager.service import MATCHING
from app.schemas.enums import ApplicationStatus, SuggestedAction
from app.schemas.manager import AiFeedbackGroup, ManagerStats


def _share(part: int, total: int) -> str | None:
    if total == 0:
        return None
    return str((Decimal(part) / Decimal(total)).quantize(Decimal("0.01"), ROUND_HALF_UP))


async def manager_stats(session: AsyncSession) -> ManagerStats:
    by_status = {
        ApplicationStatus(status): n
        for status, n in await session.execute(
            select(Application.status, func.count()).group_by(Application.status)
        )
    }

    first_decision = (
        select(
            CreditDecision.application_id,
            func.min(CreditDecision.created_at).label("decided_at"),
        )
        .group_by(CreditDecision.application_id)
        .subquery()
    )
    median = await session.scalar(
        select(
            func.percentile_cont(0.5).within_group(
                func.extract("epoch", first_decision.c.decided_at - Application.submitted_at)
            )
        ).join(first_decision, first_decision.c.application_id == Application.id)
    )

    latest = (
        select(DecisionProposal.suggested_action)
        .join(ScoringResult, ScoringResult.id == DecisionProposal.scoring_result_id)
        .where(ScoringResult.application_id == Application.id)
        .order_by(DecisionProposal.created_at.desc())
        .limit(1)
        .scalar_subquery()
    )
    distribution = {
        SuggestedAction(action): n
        for action, n in await session.execute(
            select(latest.label("action"), func.count())
            .where(Application.status == ApplicationStatus.UNDER_REVIEW)
            .group_by("action")
        )
        if action is not None
    }

    pairs = await session.execute(
        select(CreditDecision.action, DecisionProposal.suggested_action).join(
            DecisionProposal, DecisionProposal.id == CreditDecision.proposal_id
        )
    )
    decided = matched = 0
    for action, suggested in pairs:
        decided += 1
        matched += MATCHING[SuggestedAction(suggested)] == action

    groups = [
        AiFeedbackGroup(
            prompt_version=prompt,
            model_id=model,
            source=source,
            total=total,
            up_count=up,
            up_share=_share(up, total),
        )
        for prompt, model, source, total, up in await session.execute(
            select(
                AiReport.prompt_version,
                AiReport.model_id,
                AiReport.llm_mode,
                func.count(),
                func.sum(case((AiFeedback.verdict == "UP", 1), else_=0)).cast(Integer),
            )
            .join(AiReport, AiReport.id == AiFeedback.ai_report_id)
            .group_by(AiReport.prompt_version, AiReport.model_id, AiReport.llm_mode)
            .order_by(AiReport.prompt_version, AiReport.llm_mode)
        )
    ]
    return ManagerStats(
        applications_by_status=by_status,
        median_time_to_decision_seconds=round(median) if median is not None else None,
        suggested_action_distribution=distribution,
        decisions_matching_suggestion_share=_share(matched, decided),
        ai_feedback_up_share={
            f"{g.prompt_version}|{g.model_id or '-'}|{g.source}": g.up_share
            for g in groups
            if g.up_share is not None
        },
        ai_feedback_groups=groups,
    )
