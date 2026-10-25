"""GET /manager/stats (#7) против независимого SQL."""

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.applications.conftest import MANAGER, Manager, Pipeline


async def test_stats_match_independent_sql(
    pipeline: Pipeline, manager: Manager, api: httpx.AsyncClient, db: AsyncEngine
) -> None:
    ids = {}
    for code in ("C1", "C2", "C3", "C6"):
        _, body = await pipeline.submitted(code)
        ids[code] = body["id"]
    await manager.decide(ids["C1"], 3, action="APPROVE")  # совпадает с ELIGIBLE
    await manager.decide(ids["C2"], 3, action="APPROVE", comment="Беру риск")  # расходится
    await manager.decide(ids["C3"], 3, action="REQUEST_INFO", question_text="?")  # совпадает
    async with db.begin() as conn:
        manager_id = await conn.scalar(
            sa.text("SELECT id FROM users WHERE email = :e"), {"e": MANAGER}
        )
        reports = (
            (await conn.execute(sa.text("SELECT id FROM ai_reports ORDER BY id LIMIT 2")))
            .scalars()
            .all()
        )
        for report, verdict in zip(reports, ("UP", "DOWN"), strict=True):
            await conn.execute(
                sa.text(
                    "INSERT INTO ai_feedback (ai_report_id, manager_user_id, verdict) "
                    "VALUES (:r, :m, :v)"
                ),
                {"r": report, "m": manager_id, "v": verdict},
            )
        by_status: dict[str, int] = dict(
            (
                await conn.execute(
                    sa.text("SELECT status, count(*) FROM applications GROUP BY status")
                )
            ).all()
        )
        median = await conn.scalar(
            sa.text(
                "SELECT round(percentile_cont(0.5) WITHIN GROUP "
                "(ORDER BY extract(epoch FROM d - a.submitted_at))) "
                "FROM applications a JOIN (SELECT application_id, min(created_at) d "
                "FROM credit_decisions "
                "GROUP BY application_id) x ON x.application_id = a.id"
            )
        )
    response = await api.get("/manager/stats", headers=manager.headers)
    assert response.status_code == 200
    stats = response.json()
    assert stats["applications_by_status"] == by_status
    assert stats["median_time_to_decision_seconds"] == int(median)
    assert stats["suggested_action_distribution"] == {
        "BLOCKED_BY_RULE": 1
    }  # только UNDER_REVIEW: C6
    assert stats["decisions_matching_suggestion_share"] == "0.67"  # 2 из 3
    assert stats["ai_feedback_groups"] == [
        {
            "prompt_version": "explain-v1",
            "model_id": None,
            "source": "replay",
            "total": 2,
            "up_count": 1,
            "up_share": "0.50",
        }
    ]
    assert stats["ai_feedback_up_share"] == {"explain-v1|-|replay": "0.50"}


async def test_empty_stats(api: httpx.AsyncClient, manager: Manager) -> None:
    stats = (await api.get("/manager/stats", headers=manager.headers)).json()
    assert stats["applications_by_status"] == {}
    assert stats["median_time_to_decision_seconds"] is None
    assert stats["decisions_matching_suggestion_share"] is None
    assert stats["ai_feedback_groups"] == []
