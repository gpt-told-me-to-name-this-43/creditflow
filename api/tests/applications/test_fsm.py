"""FSM заявки (#7): полная таблица переходов, событие и revision, отсутствие обходов."""

import itertools
import re
import subprocess
import sys
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.applications import fsm
from app.applications.fsm import Action, Actor
from app.core.errors import AppError
from app.db.models import Application
from app.schemas.client import ClientAction as B
from app.schemas.common import ErrorCode
from app.schemas.enums import ApplicationStatus as S
from tests.applications.conftest import BAKERY, BAKERY_INN, BindCompany
from tests.conftest import REPO_ROOT

# Эталон — таблица из ишью #7, записанная независимо от fsm.TRANSITIONS.
EXPECTED: dict[tuple[S | None, Action, Actor], S] = {
    (None, Action.CREATE, Actor.CLIENT): S.DRAFT,
    (S.DRAFT, Action.SUBMIT, Actor.CLIENT): S.UNDER_REVIEW,
    (S.UNDER_REVIEW, Action.APPROVE, Actor.MANAGER): S.APPROVED,
    (S.UNDER_REVIEW, Action.REJECT, Actor.MANAGER): S.REJECTED,
    (S.UNDER_REVIEW, Action.COUNTER_OFFER, Actor.MANAGER): S.COUNTER_OFFER,
    (S.UNDER_REVIEW, Action.REQUEST_INFO, Actor.MANAGER): S.NEED_INFO,
    (S.NEED_INFO, Action.ANSWER_INFO, Actor.CLIENT): S.UNDER_REVIEW,
    (S.COUNTER_OFFER, Action.ACCEPT_OFFER, Actor.CLIENT): S.APPROVED,
    (S.COUNTER_OFFER, Action.DECLINE_OFFER, Actor.CLIENT): S.DECLINED,
    (S.APPROVED, Action.SIGN, Actor.CLIENT): S.SIGNED,
    (S.SIGNED, Action.DISBURSE, Actor.SYSTEM): S.ISSUED,
}

ALL = list(itertools.product([None, *S], Action, Actor))


@pytest.mark.parametrize(("source", "action", "actor"), ALL)
def test_every_status_action_actor(source: S | None, action: Action, actor: Actor) -> None:
    expected = EXPECTED.get((source, action, actor))
    if expected is not None:
        assert fsm.resolve(source, action, actor) is expected
    else:
        with pytest.raises(AppError) as error:
            fsm.resolve(source, action, actor)
        assert error.value.code is ErrorCode.INVALID_STATUS_TRANSITION


def test_table_has_no_extra_transitions() -> None:
    assert {(t.source, t.action, t.actor): t.target for t in fsm.TRANSITIONS} == EXPECTED
    assert len(fsm.TRANSITIONS) == len(EXPECTED)  # нет дублей


@pytest.mark.parametrize(
    ("status", "buttons"),
    [
        (S.DRAFT, [B.EDIT, B.INTERPRET, B.SUBMIT]),
        (S.UNDER_REVIEW, []),
        (S.NEED_INFO, [B.RESPOND_INFO]),
        (S.COUNTER_OFFER, [B.ACCEPT_OFFER, B.DECLINE_OFFER]),
        (S.APPROVED, [B.VIEW_CONTRACT, B.REQUEST_SIGN_CODE, B.SIGN]),
        (S.SIGNED, [B.VIEW_CONTRACT]),
        (S.ISSUED, [B.VIEW_CONTRACT]),
        (S.REJECTED, []),
        (S.DECLINED, []),
    ],
)
def test_client_actions(status: S, buttons: list[B]) -> None:
    assert fsm.client_actions(status) == buttons


def test_system_transition_has_no_user_and_user_transition_has_one() -> None:
    application = Application(status=S.SIGNED.value, revision=5)
    with pytest.raises(ValueError, match="SYSTEM"):
        fsm.transition(None, application, Action.DISBURSE, Actor.SYSTEM, uuid.uuid4())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="SYSTEM"):
        fsm.transition(None, application, Action.SIGN, Actor.CLIENT, None)  # type: ignore[arg-type]


async def test_transition_writes_event_and_bumps_revision(
    db: AsyncEngine, bind_company: BindCompany
) -> None:
    await bind_company(BAKERY, BAKERY_INN)
    async with db.begin() as conn:
        user = (
            await conn.execute(
                sa.text("SELECT id, company_id FROM users WHERE email = :e"), {"e": BAKERY}
            )
        ).one()
        app_id = await conn.scalar(
            sa.text(
                "INSERT INTO applications (company_id, owner_user_id, revision) "
                "VALUES (:c, :u, 3) RETURNING id"
            ),
            {"c": user.company_id, "u": user.id},
        )
    async with AsyncSession(db, expire_on_commit=False) as session, session.begin():
        application = await session.get(Application, app_id, with_for_update=True)
        assert application is not None
        target = fsm.transition(session, application, Action.SUBMIT, Actor.CLIENT, user.id)
    assert target is S.UNDER_REVIEW
    async with db.connect() as conn:
        row = (
            await conn.execute(
                sa.text("SELECT status, revision FROM applications WHERE id = :i"), {"i": app_id}
            )
        ).one()
        events = (
            await conn.execute(
                sa.text(
                    "SELECT from_status, to_status, actor_user_id FROM application_events "
                    "WHERE application_id = :i"
                ),
                {"i": app_id},
            )
        ).all()
    assert (row.status, row.revision) == ("UNDER_REVIEW", 4)
    assert [tuple(e) for e in events] == [("DRAFT", "UNDER_REVIEW", user.id)]


async def test_invalid_transition_changes_nothing(
    db: AsyncEngine, bind_company: BindCompany
) -> None:
    await bind_company(BAKERY, BAKERY_INN)
    async with db.begin() as conn:
        user = (
            await conn.execute(
                sa.text("SELECT id, company_id FROM users WHERE email = :e"), {"e": BAKERY}
            )
        ).one()
        app_id = await conn.scalar(
            sa.text(
                "INSERT INTO applications (company_id, owner_user_id) VALUES (:c, :u) RETURNING id"
            ),
            {"c": user.company_id, "u": user.id},
        )
    with pytest.raises(AppError):
        async with AsyncSession(db) as session, session.begin():
            application = await session.get(Application, app_id, with_for_update=True)
            assert application is not None
            fsm.transition(session, application, Action.SIGN, Actor.CLIENT, user.id)
    async with db.connect() as conn:
        assert await conn.scalar(sa.text("SELECT revision FROM applications")) == 0
        assert await conn.scalar(sa.text("SELECT count(*) FROM application_events")) == 0


# Присваивание статуса заявке где-либо, кроме fsm.py, — обход FSM.
_BYPASS = re.compile(
    r"\b\w*app\w*\.status\s*=(?!=)|update\(\s*Application\s*\)[^\n]*status", re.IGNORECASE
)


def test_status_is_assigned_only_in_fsm() -> None:
    app_dir = REPO_ROOT / "api" / "app"
    offenders = [
        f"{path.relative_to(app_dir)}:{n}"
        for path in app_dir.rglob("*.py")
        if path.name != "fsm.py"
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if _BYPASS.search(line)
    ]
    assert offenders == []


def test_state_machine_doc_is_up_to_date() -> None:
    script = REPO_ROOT / "scripts" / "gen_state_machine.py"
    result = subprocess.run(
        [sys.executable, str(script), "--check"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
