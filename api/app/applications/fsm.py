"""FSM заявки (design.md §3.7, issue #7): единственное место, где меняется статус.

Таблица `TRANSITIONS` — источник истины: по ней работает `transition`, считаются
действия клиента и генерируется `docs/state-machine.md` (`make state-machine`).
Каждая смена статуса в той же транзакции пишет событие в `application_events`
и увеличивает `revision`. Вызывающий обязан заранее взять заявку под
`SELECT … FOR UPDATE` и проверить `revision` (`app.applications.repo`).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models import Application, ApplicationEvent
from app.schemas.client import ClientAction
from app.schemas.common import ErrorCode
from app.schemas.enums import ApplicationStatus as S


class Actor(StrEnum):
    CLIENT = "CLIENT"
    MANAGER = "MANAGER"
    SYSTEM = "SYSTEM"


class Action(StrEnum):
    CREATE = "create"
    SUBMIT = "submit"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    COUNTER_OFFER = "COUNTER_OFFER"
    REQUEST_INFO = "REQUEST_INFO"
    ANSWER_INFO = "answer_info"
    ACCEPT_OFFER = "accept_offer"
    DECLINE_OFFER = "decline_offer"
    SIGN = "sign"
    DISBURSE = "disburse"


@dataclass(frozen=True)
class Transition:
    source: S | None  # None — заявки ещё нет
    action: Action
    actor: Actor
    target: S


TRANSITIONS: tuple[Transition, ...] = (
    Transition(None, Action.CREATE, Actor.CLIENT, S.DRAFT),
    Transition(S.DRAFT, Action.SUBMIT, Actor.CLIENT, S.UNDER_REVIEW),
    Transition(S.UNDER_REVIEW, Action.APPROVE, Actor.MANAGER, S.APPROVED),
    Transition(S.UNDER_REVIEW, Action.REJECT, Actor.MANAGER, S.REJECTED),
    Transition(S.UNDER_REVIEW, Action.COUNTER_OFFER, Actor.MANAGER, S.COUNTER_OFFER),
    Transition(S.UNDER_REVIEW, Action.REQUEST_INFO, Actor.MANAGER, S.NEED_INFO),
    Transition(S.NEED_INFO, Action.ANSWER_INFO, Actor.CLIENT, S.UNDER_REVIEW),
    Transition(S.COUNTER_OFFER, Action.ACCEPT_OFFER, Actor.CLIENT, S.APPROVED),
    Transition(S.COUNTER_OFFER, Action.DECLINE_OFFER, Actor.CLIENT, S.DECLINED),
    Transition(S.APPROVED, Action.SIGN, Actor.CLIENT, S.SIGNED),
    Transition(S.SIGNED, Action.DISBURSE, Actor.SYSTEM, S.ISSUED),
)

_INDEX = {(t.source, t.action): t for t in TRANSITIONS}

# Кнопки клиента в статусе (ClientApplicationView.allowed_actions). Переходы FSM дают
# действия, меняющие статус; просмотр договора и запрос кода — сопутствующие им.
_CLIENT_BUTTONS: dict[Action, tuple[ClientAction, ...]] = {
    Action.SUBMIT: (ClientAction.EDIT, ClientAction.INTERPRET, ClientAction.SUBMIT),
    Action.ANSWER_INFO: (ClientAction.RESPOND_INFO,),
    Action.ACCEPT_OFFER: (ClientAction.ACCEPT_OFFER,),
    Action.DECLINE_OFFER: (ClientAction.DECLINE_OFFER,),
    Action.SIGN: (ClientAction.VIEW_CONTRACT, ClientAction.REQUEST_SIGN_CODE, ClientAction.SIGN),
}
_VIEW_CONTRACT_AFTER_SIGN = frozenset({S.SIGNED, S.ISSUED})


def resolve(source: S | None, action: Action, actor: Actor) -> S:
    """Целевой статус перехода или 409 INVALID_STATUS_TRANSITION."""
    rule = _INDEX.get((source, action))
    if rule is None or rule.actor is not actor:
        raise AppError(
            ErrorCode.INVALID_STATUS_TRANSITION,
            f"Действие {action.value} недоступно в статусе {source.value if source else '—'}",
        )
    return rule.target


def client_actions(status: S) -> list[ClientAction]:
    buttons: list[ClientAction] = []
    for rule in TRANSITIONS:
        if rule.source is status and rule.actor is Actor.CLIENT:
            buttons += [b for b in _CLIENT_BUTTONS[rule.action] if b not in buttons]
    if status in _VIEW_CONTRACT_AFTER_SIGN:
        buttons.append(ClientAction.VIEW_CONTRACT)
    return buttons


def record_event(
    session: AsyncSession,
    application_id: uuid.UUID,
    source: S | None,
    target: S,
    actor_user_id: uuid.UUID | None,
) -> None:
    # clock_timestamp(), а не now(): порядок таймлайна не зависит от начала транзакции
    session.add(
        ApplicationEvent(
            application_id=application_id,
            actor_user_id=actor_user_id,
            from_status=source.value if source else None,
            to_status=target.value,
            created_at=func.clock_timestamp(),
        )
    )


def initial_status(actor: Actor) -> S:
    return resolve(None, Action.CREATE, actor)


def transition(
    session: AsyncSession,
    application: Application,
    action: Action,
    actor: Actor,
    actor_user_id: uuid.UUID | None,
) -> S:
    """Меняет статус заблокированной заявки. `actor_user_id` = None только у SYSTEM."""
    if (actor is Actor.SYSTEM) != (actor_user_id is None):
        raise ValueError("actor_user_id задаётся для пользователя и отсутствует у SYSTEM")
    source = S(application.status)
    target = resolve(source, action, actor)
    application.status = target.value
    application.revision += 1
    application.updated_at = datetime.now(UTC)
    record_event(session, application.id, source, target, actor_user_id)
    return target
