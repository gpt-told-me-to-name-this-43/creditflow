"""Сервис заявок: submit, решения менеджера, подписание (issue #7)."""

import json
import uuid
import hashlib
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, BackgroundTasks
from sqlalchemy import select, delete, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Application,
    ApplicationStatus,
    ApplicationEvent,
    Consent,
    IdempotencyKey,
    ScoringResult,
    DecisionProposal,
    CreditDecision,
    Offer,
    Contract,
    SignChallenge,
    ExternalSnapshot,
    AccountTransaction,
    CreditProduct,
    AiReport,
)
from app.applications.fsm import validate_transition, FSMError
from app.scoring.categorization import categorize, StatementTransaction
from app.scoring.features import build_features
from app.scoring.risk import assess, Product, limit_for_term
from app.scoring.policy import evaluate, stop_factors, allowed_actions
from app.scoring.hashing import inputs_hash
from app.scoring.versions import ENGINE_VERSION, POLICY_VERSION
from app.extsim_client import ExtSimClient, ProviderUnavailableError
from app.scoring.money import to_decimal


class ApplicationService:
    def __init__(self, db: AsyncSession, ext_sim_client: ExtSimClient, rules):
        self.db = db
        self.ext_sim = ext_sim_client
        self.rules = rules

    async def submit_application(
        self,
        app_id: uuid.UUID,
        revision: int,
        bki_consent_version: str,
        idempotency_key: str,
        user_id: uuid.UUID,
        company_id: uuid.UUID,
        company_inn: str,
        director_inn: str,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        # ШАГ 1: Проверка идемпотентности
        res_idem = await self.db.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.user_id == user_id,
                IdempotencyKey.key == idempotency_key,
            )
        )
        existing = res_idem.scalar_one_or_none()
        if existing:
            if existing.status == "IN_PROGRESS":
                raise HTTPException(status_code=409, detail="IDEMPOTENCY_IN_PROGRESS")
            return existing.response_json or {}

        self.db.add(
            IdempotencyKey(
                user_id=user_id,
                key=idempotency_key,
                status="IN_PROGRESS",
                method="POST",
                canonical_path=f"/applications/{app_id}/submit",
                request_hash=hashlib.sha256(idempotency_key.encode()).hexdigest(),
            )
        )
        await self.db.commit()

        try:
            # ШАГ 2: Согласие БКИ (отдельная транзакция)
            await self.db.execute(
                insert(Consent)
                .values(
                    user_id=user_id,
                    company_id=company_id,
                    application_id=app_id,
                    type="BKI_REQUEST",
                    text_version=bki_consent_version,
                )
                .on_conflict_do_nothing(
                    index_elements=["application_id", "type", "text_version"]
                )
            )
            await self.db.commit()

            res_c = await self.db.execute(
                select(Consent.id).where(
                    Consent.application_id == app_id,
                    Consent.type == "BKI_REQUEST",
                    Consent.text_version == bki_consent_version,
                ).limit(1)
            )
            consent_id = res_c.scalar_one()

            # ШАГ 3: Внешние данные (ВНЕ транзакции с FOR UPDATE!)
            try:
                ext_data = await self.ext_sim.fetch_all_for_submit(
                    inn=company_inn, consent_id=str(consent_id)
                )
            except ProviderUnavailableError:
                await self.db.execute(
                    delete(IdempotencyKey).where(
                        IdempotencyKey.user_id == user_id,
                        IdempotencyKey.key == idempotency_key,
                    )
                )
                await self.db.commit()
                raise HTTPException(status_code=503, detail="EXTERNAL_SERVICE_UNAVAILABLE")

            # ШАГ 4-6: Основная транзакция с блокировкой
            async with self.db.begin():
                res_app = await self.db.execute(
                    select(Application).where(Application.id == app_id).with_for_update()
                )
                app = res_app.scalar_one_or_none()
                if not app or app.status != ApplicationStatus.DRAFT.value:
                    raise HTTPException(
                        status_code=409, detail="INVALID_STATUS_TRANSITION"
                    )
                if app.revision != revision:
                    raise HTTPException(
                        status_code=409,
                        detail="REVISION_CONFLICT",
                        headers={"X-Current-Revision": str(app.revision)},
                    )

                res_prod = await self.db.execute(
                    select(CreditProduct).where(CreditProduct.id == app.product_id)
                )
                prod_db = res_prod.scalar_one_or_none()
                if not prod_db:
                    raise HTTPException(status_code=422, detail="PRODUCT_NOT_FOUND")

                product = Product(
                    id=prod_db.id,
                    annual_rate_pct=prod_db.annual_rate_pct,
                    min_amount_rub=prod_db.min_amount_rub,
                    max_amount_rub=prod_db.max_amount_rub,
                    min_term_months=prod_db.min_term_months,
                    max_term_months=prod_db.max_term_months,
                )

                # Категоризация и признаки
                txs = [
                    StatementTransaction(
                        external_id=t.external_id,
                        booked_at=t.booked_at,
                        direction=t.direction,
                        amount_rub=Decimal(t.amount_rub),
                        counterparty_inn=t.counterparty.inn,
                        counterparty_is_bank=t.counterparty.is_bank,
                        purpose=t.purpose,
                    )
                    for t in ext_data.statement.transactions
                ]

                categorized = categorize(
                    txs, self.rules, company_inn=company_inn, director_inn=director_inn
                )
                features = build_features(
                    transactions=categorized,
                    as_of=date.today(),
                    registered_at=ext_data.registry.registered_at,
                    bki_monthly_payments_rub=Decimal(
                        ext_data.bki.monthly_payments_total_rub
                    ),
                )

                risk = (
                    assess(
                        product=product,
                        amount=Decimal(app.requested_amount_rub),
                        term=app.term_months,
                        features=features,
                        bki_status=ext_data.bki.summary_status,
                    )
                    if features.calculation_status.name == "OK"
                    else None
                )

                blocking = stop_factors(
                    registry_status=ext_data.registry.status,
                    applicant_authorized=True,  # TODO: из JWT (#5)
                    bankruptcy=ext_data.fns.bankruptcy,
                    active_account_blocks=ext_data.fns.active_account_blocks,
                    features=features,
                )
                proposal = evaluate(
                    blocking_codes=blocking,
                    bki_status=ext_data.bki.summary_status,
                    risk=risk,
                )

                # ШАГ 6: Атомарная запись
                scoring_id = uuid.uuid4()

                # external_snapshots (по company_id)
                for src, payload in [
                    ("FNS", ext_data.fns),
                    ("BKI", ext_data.bki),
                    ("BANK", ext_data.statement),
                ]:
                    self.db.add(
                        ExternalSnapshot(
                            company_id=company_id,
                            provider=src,
                            response_json=payload.model_dump(),
                        )
                    )

                # account_transactions (upsert)
                for tx, cat in zip(txs, categorized):
                    await self.db.execute(
                        insert(AccountTransaction)
                        .values(
                            company_id=company_id,
                            external_id=tx.external_id,
                            booked_at=tx.booked_at,
                            amount_rub=tx.amount_rub,
                            direction=tx.direction,
                            counterparty_inn=tx.counterparty_inn,
                            counterparty_name=tx.counterparty_name
                            if hasattr(tx, "counterparty_name")
                            else "",
                            is_bank=tx.counterparty_is_bank,
                            purpose_text=tx.purpose,
                            category=cat.category.value,
                            rule_id=cat.rule_id,
                        )
                        .on_conflict_do_update(
                            index_elements=["company_id", "external_id"],
                            set_=dict(
                                booked_at=tx.booked_at,
                                amount_rub=tx.amount_rub,
                                direction=tx.direction,
                                counterparty_inn=tx.counterparty_inn,
                                category=cat.category.value,
                                rule_id=cat.rule_id,
                            ),
                        )
                    )

                # scoring_results
                self.db.add(
                    ScoringResult(
                        id=scoring_id,
                        application_id=app_id,
                        kind="SUBMISSION",
                        inputs_json={"amount": app.requested_amount_rub, "term": app.term_months},
                        inputs_hash=inputs_hash(
                            {"amount": app.requested_amount_rub, "term": app.term_months}
                        ),
                        engine_version=ENGINE_VERSION,
                        calculation_status=features.calculation_status.value,
                        monthly_payment_rub=risk.monthly_payment_rub if risk else None,
                        dscr=risk.dscr if risk else None,
                        score=risk.score if risk else None,
                        factor_points_json=risk.factor_points if risk else None,
                        risk_level=risk.risk_level.value if risk else None,
                        reason_codes=[c.value for c in risk.reason_codes] if risk else [],
                        positive_codes=[c.value for c in risk.positive_codes] if risk else [],
                        limit_rub=risk.limit_rub if risk else None,
                    )
                )

                # decision_proposals (1:1 со scoring)
                self.db.add(
                    DecisionProposal(
                        scoring_result_id=scoring_id,
                        policy_version=POLICY_VERSION,
                        blocking_codes=[b.value for b in blocking],
                        suggested_action=proposal.suggested_action.value,
                        rule_trace_json=[
                            {"rule": r.rule, "matched": r.matched, "detail": r.detail}
                            for r in proposal.rule_trace
                        ],
                    )
                )

                # ai_reports (PENDING)
                gen_id = uuid.uuid4()
                self.db.add(
                    AiReport(
                        application_id=app_id,
                        scoring_result_id=scoring_id,
                        status="PENDING",
                        llm_mode="disabled",  # MVP
                        prompt_version="v1",
                        context_hash=hashlib.sha256(str(scoring_id).encode()).hexdigest(),
                        generation_id=gen_id,
                    )
                )

                # Обновление Application
                app.status = ApplicationStatus.UNDER_REVIEW.value
                app.revision += 1
                app.submitted_at = datetime.utcnow()
                app.current_scoring_id = scoring_id
                app.updated_at = datetime.utcnow()

                self.db.add(
                    ApplicationEvent(
                        application_id=app_id,
                        actor_user_id=user_id,
                        from_status=ApplicationStatus.DRAFT.value,
                        to_status=ApplicationStatus.UNDER_REVIEW.value,
                    )
                )

                payload = {
                    "id": str(app.id),
                    "status": app.status,
                    "revision": app.revision,
                    "suggested_action": proposal.suggested_action.value,
                }

                # Обновление идемпотентности
                existing.status = "COMPLETED"
                existing.status_code = 200
                existing.response_json = payload

            # COMMIT здесь

            # ШАГ 7: Фоновая задача
            background_tasks.add_task(self._trigger_ai, app_id, gen_id)
            return payload

        except Exception as e:
            await self.db.execute(
                delete(IdempotencyKey).where(
                    IdempotencyKey.user_id == user_id,
                    IdempotencyKey.key == idempotency_key,
                )
            )
            await self.db.commit()
            raise e

    async def make_decision(
        self,
        app_id: uuid.UUID,
        revision: int,
        action: str,
        user_id: uuid.UUID,
        amount_rub: int | None,
        term_months: int | None,
        comment: str | None,
    ) -> dict[str, Any]:
        async with self.db.begin():
            res_app = await self.db.execute(
                select(Application).where(Application.id == app_id).with_for_update()
            )
            app = res_app.scalar_one_or_none()
            if not app or app.revision != revision:
                raise HTTPException(status_code=409, detail="REVISION_CONFLICT")

            # Получаем последний proposal
            res_prop = await self.db.execute(
                select(DecisionProposal)
                .join(ScoringResult, DecisionProposal.scoring_result_id == ScoringResult.id)
                .where(ScoringResult.application_id == app_id)
                .order_by(DecisionProposal.created_at.desc())
                .limit(1)
            )
            prop = res_prop.scalar_one_or_none()
            if not prop:
                raise HTTPException(status_code=422, detail="NO_PROPOSAL_FOUND")

            res_score = await self.db.execute(
                select(ScoringResult).where(ScoringResult.id == prop.scoring_result_id)
            )
            score = res_score.scalar_one()

            allowed = allowed_actions(
                blocking_codes=prop.blocking_codes,
                limit_rub=score.limit_rub,
            )
            if action not in allowed:
                raise HTTPException(status_code=422, detail="ACTION_NOT_ALLOWED")

            target_status = {
                "APPROVE": ApplicationStatus.APPROVED,
                "REJECT": ApplicationStatus.REJECTED,
                "COUNTER_OFFER": ApplicationStatus.COUNTER_OFFER,
                "REQUEST_INFO": ApplicationStatus.NEED_INFO,
            }.get(action)

            validate_transition(ApplicationStatus(app.status), target_status)

            decision_id = uuid.uuid4()
            self.db.add(
                CreditDecision(
                    id=decision_id,
                    application_id=app_id,
                    proposal_id=prop.id,
                    manager_user_id=user_id,
                    action=action,
                    comment=comment,
                )
            )

            if action == "COUNTER_OFFER" and amount_rub and term_months:
                # Валидация оффера
                res_prod = await self.db.execute(
                    select(CreditProduct).where(CreditProduct.id == app.product_id)
                )
                prod = res_prod.scalar_one()
                prod_obj = Product(
                    id=prod.id,
                    annual_rate_pct=prod.annual_rate_pct,
                    min_amount_rub=prod.min_amount_rub,
                    max_amount_rub=prod.max_amount_rub,
                    min_term_months=prod.min_term_months,
                    max_term_months=prod.max_term_months,
                )

                if not (prod_obj.min_term_months <= term_months <= prod_obj.max_term_months):
                    raise HTTPException(status_code=422, detail="TERM_OUT_OF_PRODUCT")

                limit = limit_for_term(
                    prod_obj, score.dscr or Decimal(0), score.monthly_payment_rub or Decimal(0), term_months
                )
                if limit and amount_rub > limit:
                    raise HTTPException(status_code=422, detail="AMOUNT_ABOVE_LIMIT")

                # Создаем scoring для оффера
                offer_scoring_id = uuid.uuid4()
                self.db.add(
                    ScoringResult(
                        id=offer_scoring_id,
                        application_id=app_id,
                        kind="COUNTER_OFFER",
                        inputs_json={"amount": amount_rub, "term": term_months},
                        inputs_hash=inputs_hash({"amount": amount_rub, "term": term_months}),
                        engine_version=ENGINE_VERSION,
                        calculation_status=score.calculation_status,
                        monthly_payment_rub=score.monthly_payment_rub,
                        dscr=score.dscr,
                        score=score.score,
                        risk_level=score.risk_level,
                        limit_rub=limit,
                    )
                )

                offer_id = uuid.uuid4()
                self.db.add(
                    Offer(
                        id=offer_id,
                        decision_id=decision_id,
                        amount_rub=Decimal(amount_rub),
                        term_months=term_months,
                        product_id=app.product_id,
                        annual_rate_pct=prod.annual_rate_pct,
                        monthly_payment_rub=score.monthly_payment_rub or Decimal(0),
                        offer_scoring_id=offer_scoring_id,
                        status="OPEN",
                    )
                )
                app.current_offer_id = offer_id

            app.status = target_status.value
            app.revision += 1
            app.current_decision_id = decision_id
            app.updated_at = datetime.utcnow()

            self.db.add(
                ApplicationEvent(
                    application_id=app_id,
                    actor_user_id=user_id,
                    from_status=app.status,
                    to_status=target_status.value,
                )
            )

            return {
                "id": str(app.id),
                "status": app.status,
                "revision": app.revision,
            }

    async def _trigger_ai(self, app_id: uuid.UUID, gen_id: uuid.UUID):
        """Заглушка для #8."""
        pass
