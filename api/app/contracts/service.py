"""ContractService: договор, подписание кодом из UI, смоделированная выдача (design §3.3, §3.7).

- Договор создаётся в той же транзакции, что переход в `APPROVED` (APPROVE или accept_offer).
- Подписание — простая электронная подпись: одноразовый код показывается в UI
  (`demo_code` только при DEMO_AUTH_ENABLED). Без SMS, email и реальной ЭП. Код не логируется,
  в БД — только HMAC.
- Выдача смоделирована: через 3–5 с после COMMIT подписания SYSTEM переводит заявку в `ISSUED`.
  Реальных проводок нет. `recover_pending_disbursements()` закрывает выдачи после перезапуска.
"""

import asyncio
import hashlib
import hmac
import logging
import random
import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.applications import fsm, repo
from app.core.errors import AppError
from app.db.models import (
    CONTRACT_NUMBER_SEQ,
    Application,
    Contract,
    ExternalSnapshot,
    SignChallenge,
)
from app.schemas.client import ContractView, ScheduleItem
from app.schemas.client import SignChallenge as SignChallengeView
from app.schemas.common import (
    ErrorCode,
    SignCodeInvalidDetails,
    TooManyAttemptsDetails,
)
from app.schemas.enums import ApplicationStatus
from app.scoring.money import money_str
from app.scoring.schedule import build_schedule

logger = logging.getLogger("app.contracts")

CHALLENGE_TTL = timedelta(minutes=5)
MAX_ATTEMPTS = 3
CHALLENGE_WINDOW = timedelta(minutes=15)
MAX_CHALLENGES_PER_WINDOW = 5
DISBURSE_DELAY_SECONDS = (3.0, 5.0)
DISBURSE_AFTER = timedelta(seconds=10)  # recover_pending_disbursements: SIGNED старше 10 с
DEFAULT_ACCOUNT = "40702 •••• 0000"


async def create_contract(
    session: AsyncSession,
    application: Application,
    amount_rub: Decimal,
    term_months: int,
    annual_rate_pct: Decimal,
    as_of: date,
) -> Contract:
    """В транзакции перехода в APPROVED с итоговыми условиями. График — от `APP_AS_OF_DATE`:
    первый платёж через месяц, то же число (для 29–31 — последний день короткого месяца)."""
    seq = await session.scalar(CONTRACT_NUMBER_SEQ.next_value())
    account = await session.scalar(
        select(ExternalSnapshot.response_json["account_masked"].astext)
        .where(
            ExternalSnapshot.company_id == application.company_id,
            ExternalSnapshot.provider == "BANK",
        )
        .order_by(ExternalSnapshot.fetched_at.desc())
        .limit(1)
    )
    rows = build_schedule(amount_rub, annual_rate_pct, term_months, as_of)
    contract = Contract(
        id=uuid.uuid4(),
        application_id=application.id,
        number=f"CF-{as_of.year}-{seq:06d}",
        amount_rub=amount_rub,
        term_months=term_months,
        annual_rate_pct=annual_rate_pct,
        monthly_payment_rub=rows[0].payment_rub,
        schedule_json=[
            {
                "number": r.number,
                "due_date": r.due_date.isoformat(),
                "payment_rub": money_str(r.payment_rub),
                "interest_rub": money_str(r.interest_rub),
                "principal_rub": money_str(r.principal_rub),
                "balance_after_rub": money_str(r.balance_after_rub),
            }
            for r in rows
        ],
        account_masked=account or DEFAULT_ACCOUNT,
    )
    session.add(contract)
    return contract


def key_terms_markdown(contract: Contract, overpayment: str) -> str:
    def rub(value: str) -> str:
        whole, cents = value.split(".")
        return f"{int(whole):,}".replace(",", " ") + f",{cents} ₽"

    return (
        f"## Основные условия договора {contract.number}\n\n"
        f"- Сумма кредита: {rub(money_str(contract.amount_rub))}\n"
        f"- Срок: {contract.term_months} мес.\n"
        f"- Ставка: {money_str(contract.annual_rate_pct)}% годовых, фиксированная\n"
        f"- Ежемесячный платёж: {rub(money_str(contract.monthly_payment_rub))} "
        "(последний платёж корректируется до полного погашения)\n"
        f"- Переплата за весь срок: {rub(overpayment)}\n"
        f"- Счёт зачисления: {contract.account_masked}\n\n"
        "Подписание — простой электронной подписью кодом из интерфейса (демо: вместо SMS). "
        "Выдача смоделирована, реальных операций нет."
    )


def contract_view(contract: Contract) -> ContractView:
    overpayment = money_str(
        sum((Decimal(r["interest_rub"]) for r in contract.schedule_json), Decimal(0))
    )
    return ContractView(
        number=contract.number,
        status=contract.status,
        amount_rub=money_str(contract.amount_rub),
        term_months=contract.term_months,
        annual_rate_pct=money_str(contract.annual_rate_pct),
        monthly_payment_rub=money_str(contract.monthly_payment_rub),
        overpayment_rub=overpayment,
        account_masked=contract.account_masked,
        key_terms_markdown=key_terms_markdown(contract, overpayment),
        schedule=[ScheduleItem.model_validate(r) for r in contract.schedule_json],
        signed_at=contract.signed_at,
        issued_at=contract.issued_at,
    )


async def get_contract(session: AsyncSession, application_id: uuid.UUID) -> Contract | None:
    contract: Contract | None = await session.scalar(
        select(Contract).where(Contract.application_id == application_id)
    )
    return contract


def _code_hash(secret: str, challenge_id: uuid.UUID, code: str) -> str:
    return hmac.new(secret.encode(), f"{challenge_id}:{code}".encode(), hashlib.sha256).hexdigest()


async def issue_challenge(
    session: AsyncSession,
    owner_id: uuid.UUID,
    application_id: uuid.UUID,
    revision: int,
    secret: str,
    demo: bool,
) -> SignChallengeView:
    async with session.begin():
        application = await repo.lock_owned(session, application_id, owner_id)
        if application.status != ApplicationStatus.APPROVED:
            raise AppError(
                ErrorCode.INVALID_STATUS_TRANSITION, "Подписать можно только одобренную заявку"
            )
        repo.ensure_revision(application, revision)
        now = await session.scalar(select(func.clock_timestamp()))
        assert now is not None
        recent = list(
            await session.scalars(
                select(SignChallenge.created_at)
                .where(
                    SignChallenge.application_id == application_id,
                    SignChallenge.created_at > now - CHALLENGE_WINDOW,
                )
                .order_by(SignChallenge.created_at)
            )
        )
        if len(recent) >= MAX_CHALLENGES_PER_WINDOW:
            wait = max(1, int((recent[0] + CHALLENGE_WINDOW - now).total_seconds()) + 1)
            raise AppError(
                ErrorCode.TOO_MANY_ATTEMPTS,
                "Слишком много кодов, попробуйте позже",
                TooManyAttemptsDetails(scope="CHALLENGE_ISSUE", retry_after_seconds=wait),
            )
        # новый код делает прежние недействительными
        await session.execute(
            update(SignChallenge)
            .where(
                SignChallenge.application_id == application_id,
                SignChallenge.used_at.is_(None),
                SignChallenge.expires_at > now,
            )
            .values(expires_at=now)
        )
        code = f"{secrets.randbelow(10**6):06d}"
        challenge_id = uuid.uuid4()
        challenge = SignChallenge(
            id=challenge_id,
            application_id=application_id,
            code_hash=_code_hash(secret, challenge_id, code),
            expires_at=now + CHALLENGE_TTL,
            created_at=now,
        )
        session.add(challenge)
        application.revision += 1  # контракт: sign передаёт revision из ответа challenge
        application.updated_at = now
        return SignChallengeView(
            challenge_id=challenge_id,
            revision=application.revision,
            expires_at=challenge.expires_at,
            attempts_remaining=MAX_ATTEMPTS,
            demo_code=code if demo else None,
        )


async def check_code(
    session: AsyncSession,
    application: Application,
    challenge_id: uuid.UUID,
    code: str,
    secret: str,
) -> AppError | None:
    """Внутри транзакции подписания. Возвращает ошибку попытки: её нужно отдать ПОСЛЕ COMMIT,
    чтобы счётчик попыток сохранился (ошибка внутри транзакции откатила бы его)."""
    now = await session.scalar(select(func.clock_timestamp()))
    assert now is not None
    challenge = await session.scalar(
        select(SignChallenge)
        .where(SignChallenge.id == challenge_id, SignChallenge.application_id == application.id)
        .with_for_update()
    )
    if (
        challenge is None
        or challenge.used_at is not None
        or challenge.expires_at <= now
        or challenge.attempts >= MAX_ATTEMPTS
    ):
        return AppError(ErrorCode.SIGN_CHALLENGE_EXPIRED, "Запросите новый код подтверждения")
    if hmac.compare_digest(challenge.code_hash, _code_hash(secret, challenge.id, code)):
        challenge.used_at = now
        return None
    challenge.attempts += 1
    remaining = MAX_ATTEMPTS - challenge.attempts
    if remaining == 0:
        challenge.expires_at = now  # третья неверная попытка закрывает challenge
        return AppError(
            ErrorCode.TOO_MANY_ATTEMPTS,
            "Код введён неверно 3 раза, запросите новый",
            TooManyAttemptsDetails(scope="SIGN_ATTEMPTS"),
        )
    return AppError(
        ErrorCode.SIGN_CODE_INVALID,
        "Неверный код подтверждения",
        SignCodeInvalidDetails(remaining_attempts=remaining),
    )


async def mark_signed(
    session: AsyncSession, application: Application, user_id: uuid.UUID
) -> Contract:
    contract = await get_contract(session, application.id)
    assert contract is not None  # создан при переходе в APPROVED
    contract.status = "SIGNED"
    contract.signed_at = datetime.now(UTC)
    contract.signed_by_user_id = user_id
    fsm.transition(session, application, fsm.Action.SIGN, fsm.Actor.CLIENT, user_id)
    return contract


async def disburse(sessions: async_sessionmaker[AsyncSession], application_id: uuid.UUID) -> bool:
    """SIGNED → ISSUED от SYSTEM. Идемпотентно: не SIGNED — ничего не делает."""
    async with sessions() as session, session.begin():
        application = await session.scalar(
            select(Application)
            .where(Application.id == application_id)
            .with_for_update(skip_locked=True)
        )
        if application is None or application.status != ApplicationStatus.SIGNED:
            return False
        contract = await get_contract(session, application_id)
        assert contract is not None
        contract.status = "ISSUED"
        contract.issued_at = datetime.now(UTC)
        fsm.transition(session, application, fsm.Action.DISBURSE, fsm.Actor.SYSTEM, None)
        tail = contract.account_masked.replace(" ", "")[-4:]
        logger.info("application %s: средства зачислены на счёт ••••%s", application_id, tail)
    return True


async def disburse_later(
    sessions: async_sessionmaker[AsyncSession],
    application_id: uuid.UUID,
    delay: tuple[float, float] = DISBURSE_DELAY_SECONDS,
) -> None:
    """BackgroundTasks после COMMIT подписания: пауза 3–5 с, затем выдача."""
    try:
        await asyncio.sleep(random.uniform(*delay))
        await disburse(sessions, application_id)
    except Exception:
        logger.exception("application %s: выдача упала, закроет recovery", application_id)


async def recover_pending_disbursements(sessions: async_sessionmaker[AsyncSession]) -> int:
    """Идемпотентно: SIGNED дольше 10 с → ISSUED. При старте (lifespan) и раз в 15 с."""
    threshold = datetime.now(UTC) - DISBURSE_AFTER
    async with sessions() as session:
        ids = list(
            await session.scalars(
                select(Application.id)
                .join(Contract, Contract.application_id == Application.id)
                .where(
                    Application.status == ApplicationStatus.SIGNED, Contract.signed_at < threshold
                )
            )
        )
    done = 0
    for application_id in ids:
        done += await disburse(sessions, application_id)
    return done
