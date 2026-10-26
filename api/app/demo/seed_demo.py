"""Демо-состояние для проверяющих и стенда (issue #7 «Демо-состояние»).

Работает через сервисный слой — те же create_draft, PATCH, submit, decisions, ответы клиента,
подписание и выдача, что и API, — поэтому состояние гарантированно достижимо из интерфейса.
Требует ext-sim (Submit собирает данные). Расчёты и графики — от `APP_AS_OF_DATE`;
у исторических заявок `submitted_at` сдвинут назад, чтобы сводка показывала время рассмотрения.

| Компания | После seed |
| C1 | прошлые заявки (ISSUED и др.), можно подать новую |
| C2, C4 | компания не привязана, заявок нет — путь с нуля |
| C3 | NEED_INFO с вопросом |
| C5 | REJECTED по стоп-фактору |
| C6 | UNDER_REVIEW, BLOCKED_BY_RULE |
| C7 | UNDER_REVIEW, MANUAL_REVIEW |
| история | 9 решённых заявок для сводки |

Привязка компаний — сервисом `bind_company` (#5), как POST /onboarding/company-binding.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.applications import responses, service
from app.applications.submit import submit
from app.auth.deps import CurrentUser
from app.contracts import service as contracts
from app.core.config import Settings
from app.core.idempotency import Idempotency
from app.db.models import Application, User
from app.extsim_client import ExtSimClient
from app.llm.base import LLMClient
from app.llm.client import build_llm_client
from app.manager import service as manager_service
from app.onboarding.consents import current_version
from app.onboarding.service import bind_company
from app.schemas.auth import CompanyBindingRequest, ConsentType, Role
from app.schemas.client import ApplicationCreate, ApplicationPatch
from app.schemas.manager import (
    ApproveDecision,
    CounterOfferDecision,
    DecisionRequest,
    RejectDecision,
    RequestInfoDecision,
)
from app.scoring.categorization import RuleSet

MANAGER_EMAIL = "manager.anna@creditflow.demo"
# C2 и C4 — путь с нуля: компания не привязана, привязка — часть сценария.
BOUND = ("C1", "C3", "C5", "C6", "C7")


@dataclass(frozen=True)
class Client:
    email: str
    inn: str
    terms: dict[str, Any]


CLIENTS = {
    "C1": Client(
        "director.techservice@creditflow.demo",
        "0099010012",
        {
            "purpose_code": "EQUIPMENT",
            "requested_amount_rub": 2_000_000,
            "term_months": 36,
            "product_id": "investment",
        },
    ),
    "C2": Client("director.bakery@creditflow.demo", "0099020010", {}),
    "C3": Client(
        "ip.sokolova@creditflow.demo",
        "009903001040",
        {
            "purpose_code": "INVENTORY",
            "requested_amount_rub": 800_000,
            "term_months": 12,
            "product_id": "working_capital",
        },
    ),
    "C4": Client("director.newstart@creditflow.demo", "0099040017", {}),
    "C5": Client(
        "director.vector@creditflow.demo",
        "0099050015",
        {
            "purpose_code": "SUPPLIERS",
            "requested_amount_rub": 1_000_000,
            "term_months": 12,
            "product_id": "working_capital",
        },
    ),
    "C6": Client(
        "director.sklad@creditflow.demo",
        "0099060013",
        {
            "purpose_code": "WORKING_CAPITAL",
            "requested_amount_rub": 1_500_000,
            "term_months": 18,
            "product_id": "working_capital",
        },
    ),
    "C7": Client(
        "ip.orlov@creditflow.demo",
        "009907001027",
        {
            "purpose_code": "RENOVATION",
            "requested_amount_rub": 1_000_000,
            "term_months": 36,
            "product_id": "investment",
        },
    ),
}


class _NoKey(Idempotency):
    """Seed вызывает сервисы напрямую, без HTTP и Idempotency-Key."""

    def __init__(self) -> None:
        super().__init__(user_id=uuid.UUID(int=0), key="seed", token=datetime.now(UTC))

    async def complete(self, session: AsyncSession, status_code: int, payload: Any) -> Any:
        return payload


class DemoSeeder:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        ext_sim: ExtSimClient,
        rules: RuleSet,
        settings: Settings,
        llm: LLMClient | None = None,
    ) -> None:
        self.sessions, self.ext_sim, self.rules, self.settings = sessions, ext_sim, rules, settings
        # тот же клиент, что у api: в replay демо-карточки получают записанные заключения
        self.llm = llm or build_llm_client(settings)
        self.users: dict[str, CurrentUser] = {}
        self.history: list[tuple[uuid.UUID, int]] = []  # (заявка, часов до решения)

    async def user(self, email: str) -> CurrentUser:
        async with self.sessions() as session:
            row = await session.scalar(select(User).where(User.email == email))
        assert row is not None
        return CurrentUser(row.id, Role(row.role), row.full_name, row.person_inn, row.company_id)

    async def bind(self, code: str) -> CurrentUser:
        """Привязка компании тем же сервисом, что POST /onboarding/company-binding (#5)."""
        client = CLIENTS[code]
        user = await self.user(client.email)
        request = CompanyBindingRequest(
            inn=client.inn, pd_consent_version=current_version(ConsentType.PD_PROCESSING)
        )
        async with self.sessions() as session:
            company = await bind_company(session, self.ext_sim, user, request)
        current = CurrentUser(user.id, user.role, user.full_name, user.person_inn, company.id)
        self.users[code] = current
        return current

    async def manager(self) -> CurrentUser:
        return await self.user(MANAGER_EMAIL)

    async def submitted(self, code: str, **override: Any) -> tuple[uuid.UUID, int]:
        user = self.users[code]
        async with self.sessions() as session:
            application, _ = await service.create_draft(session, user, ApplicationCreate())
            app_id = application.id
        async with self.sessions() as session:
            terms = {**CLIENTS[code].terms, **override}
            await service.patch_draft(session, user, app_id, ApplicationPatch(revision=1, **terms))
        async with self.sessions() as session:
            result = await submit(
                session,
                self.sessions,
                self.ext_sim,
                self.rules,
                self.settings,
                user,
                app_id,
                2,
                current_version(ConsentType.BKI_REQUEST),
                _NoKey(),
            )
        await self.finish_ai(result.report_id, result.generation_id)
        return app_id, result.view.revision

    async def finish_ai(self, report_id: uuid.UUID, generation_id: uuid.UUID) -> None:
        from app.applications.ai_reports import generate

        await generate(
            self.sessions,
            self.llm,
            self.settings.llm_report_deadline_seconds,
            report_id,
            generation_id,
        )

    async def decide(self, app_id: uuid.UUID, revision: int, body: dict[str, Any]) -> int:
        from pydantic import TypeAdapter

        request: DecisionRequest = TypeAdapter(DecisionRequest).validate_python(
            {"revision": revision, **body}
        )
        assert isinstance(
            request, ApproveDecision | CounterOfferDecision | RejectDecision | RequestInfoDecision
        )
        async with self.sessions() as session:
            response = await manager_service.decide(
                session,
                await self.manager(),
                app_id,
                request,
                self.settings.app_as_of_date,
                _NoKey(),
            )
        return response.revision

    async def sign_and_issue(self, code: str, app_id: uuid.UUID, revision: int) -> None:
        user = self.users[code]
        async with self.sessions() as session:
            challenge = await contracts.issue_challenge(
                session, user.id, app_id, revision, self.settings.app_secret_key, demo=True
            )
        assert challenge.demo_code is not None
        async with self.sessions() as session:
            await responses.sign(
                session,
                user,
                app_id,
                challenge.revision,
                challenge.challenge_id,
                challenge.demo_code,
                self.settings.app_secret_key,
                self.settings.app_as_of_date,
                _NoKey(),
            )
        await contracts.disburse(self.sessions, app_id)

    async def run(self) -> None:
        for code in BOUND:
            await self.bind(code)
        reject_low = {"action": "REJECT", "client_reason_code": "LOW_SCORE", "comment": "История"}

        # --- история для сводки: 9 решённых заявок ---
        app_id, rev = await self.submitted("C1")  # прошлая заявка C1: одобрена и выдана
        rev = await self.decide(app_id, rev, {"action": "APPROVE"})
        await self.sign_and_issue("C1", app_id, rev)
        self.history.append((app_id, 6))

        app_id, rev = await self.submitted("C1", requested_amount_rub=1_500_000)
        rev = await self.decide(
            app_id,
            rev,
            {
                "action": "COUNTER_OFFER",
                "amount_rub": 1_200_000,
                "client_reason_code": "LOW_SCORE",
                "comment": "Сумма ниже запрошенной",
            },
        )
        async with self.sessions() as session:
            await responses.decline_offer(
                session, self.users["C1"], app_id, rev, self.settings.app_as_of_date, _NoKey()
            )
        self.history.append((app_id, 20))

        app_id, rev = await self.submitted("C1", requested_amount_rub=1_000_000)
        rev = await self.decide(
            app_id,
            rev,
            {
                "action": "COUNTER_OFFER",
                "amount_rub": 900_000,
                "client_reason_code": "LOW_SCORE",
                "comment": "Скорректировали сумму",
            },
        )
        async with self.sessions() as session:
            view = await responses.accept_offer(
                session, self.users["C1"], app_id, rev, self.settings.app_as_of_date, _NoKey()
            )
        await self.sign_and_issue("C1", app_id, view.revision)
        self.history.append((app_id, 30))

        app_id, rev = await self.submitted("C1", requested_amount_rub=500_000)
        await self.decide(app_id, rev, reject_low | {"comment": "Клиент отозвал потребность"})
        self.history.append((app_id, 3))

        app_id, rev = await self.submitted("C3")  # прошлая заявка C3: одобрена несмотря на БКИ
        rev = await self.decide(app_id, rev, {"action": "APPROVE", "comment": "Просрочки закрыты"})
        await self.sign_and_issue("C3", app_id, rev)
        self.history.append((app_id, 48))

        for code, reason, hours in (
            ("C5", "COMPANY_STATUS", 2),
            ("C6", "TAX_AUTHORITY_RESTRICTIONS", 4),
            ("C7", "HIGH_DEBT_LOAD", 26),
        ):
            app_id, rev = await self.submitted(code)
            await self.decide(
                app_id,
                rev,
                {
                    "action": "REJECT",
                    "client_reason_code": reason,
                    "comment": "Историческая заявка",
                },
            )
            self.history.append((app_id, hours))

        # --- текущее состояние для сценариев ---
        app_id, rev = await self.submitted("C5")  # REJECTED по стоп-фактору
        await self.decide(
            app_id,
            rev,
            {
                "action": "REJECT",
                "client_reason_code": "COMPANY_STATUS",
                "comment": "Компания в ликвидации",
            },
        )
        self.history.append((app_id, 1))

        app_id, rev = await self.submitted("C3")  # NEED_INFO с вопросом
        await self.decide(
            app_id,
            rev,
            {
                "action": "REQUEST_INFO",
                "question_text": "Подтвердите, что просрочки по кредитной истории закрыты",
            },
        )
        await self.submitted("C6")  # UNDER_REVIEW, BLOCKED_BY_RULE
        await self.submitted("C7")  # UNDER_REVIEW, MANUAL_REVIEW
        await self.backdate()

    async def backdate(self) -> None:
        """Реалистичное время рассмотрения для сводки: `submitted_at` = решение − N часов.
        Сдвигается только `submitted_at`: события и решения insert-only."""
        async with self.sessions() as session, session.begin():
            for app_id, hours in self.history:
                decided = await session.scalar(
                    text("SELECT min(created_at) FROM credit_decisions WHERE application_id = :a"),
                    {"a": app_id},
                )
                assert decided is not None
                await session.execute(
                    update(Application)
                    .where(Application.id == app_id)
                    .values(submitted_at=decided - timedelta(hours=hours))
                )


async def run_demo_seed(
    sessions: async_sessionmaker[AsyncSession],
    ext_sim: ExtSimClient,
    rules: RuleSet,
    settings: Settings,
    llm: LLMClient | None = None,
) -> None:
    await DemoSeeder(sessions, ext_sim, rules, settings, llm).run()
