"""Примеры запросов и ответов в OpenAPI для стабов контракта v1 (issue #6: «Все эндпоинты
в Swagger с примерами»).

- Пример запроса берётся из `REQUEST_EXAMPLES` и при старте валидируется своей моделью:
  невалидный пример роняет импорт, а не попадает к фронту.
- Пример ответа — то, что стаб реально возвращает: стаб вызывается один раз с примером
  запроса. Поэтому пример всегда проходит `response_model` и совпадает с моком.
- Всё кладётся в `route.openapi_extra`, который FastAPI сливает с операцией, не трогая
  сгенерированные схемы.
"""

import inspect
from copy import deepcopy
from typing import Any
from uuid import UUID

from fastapi import APIRouter, FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.routing import APIRoute
from pydantic import BaseModel, TypeAdapter

from app.core.config import Settings
from app.schemas.auth import CompanyBindingRequest, LoginRequest
from app.schemas.client import (
    ApplicationCreate,
    ApplicationPatch,
    ContractView,
    InfoResponseRequest,
    InterpretRequest,
    RevisionRequest,
    SignRequest,
    SubmitRequest,
)
from app.schemas.manager import (
    AiFeedbackRequest,
    DecisionRequest,
    ManagerApplicationView,
    OfferPreviewRequest,
    OfferPreviewResponse,
)

EXAMPLE_ID = "7f3e2a10-0000-4000-8000-000000000001"

# Значения — из сценария «Пекарни Плюс» (C2, docs/design.md §5), чтобы примеры читались вместе.
REQUEST_EXAMPLES: dict[Any, dict[str, Any]] = {
    LoginRequest: {"login": "director.bakery@creditflow.demo", "password": "creditflow-demo"},
    CompanyBindingRequest: {"inn": "0099020010", "pd_consent_version": "pd-v1"},
    ApplicationCreate: {"purpose_text": "Купить печь за 3 млн на 3 года"},
    ApplicationPatch: {
        "revision": 1,
        "purpose_code": "EQUIPMENT",
        "requested_amount_rub": 3_000_000,
        "term_months": 36,
        "product_id": "investment",
        "terms_field_sources": {
            "purpose_code": "RULES",
            "requested_amount_rub": "RULES",
            "term_months": "MANUAL",
        },
    },
    InterpretRequest: {"purpose_text": "Купить печь за 3 млн на 3 года"},
    SubmitRequest: {"revision": 2, "bki_consent_version": "bki-v1"},
    InfoResponseRequest: {"revision": 3, "answer_text": "Прикладываю договор поставки печи"},
    RevisionRequest: {"revision": 3},
    SignRequest: {"revision": 4, "challenge_id": EXAMPLE_ID, "code": "123456"},
    DecisionRequest: {
        "revision": 2,
        "action": "COUNTER_OFFER",
        "amount_rub": 2_340_000,
        "term_months": 36,
        "client_reason_code": "HIGH_DEBT_LOAD",
        "comment": "DSCR 1.10 < 1.25 на запрошенной сумме; лимит на 36 мес. — 2 340 000",
    },
    OfferPreviewRequest: {"amount_rub": 2_340_000, "term_months": 36},
    AiFeedbackRequest: {"ai_report_id": EXAMPLE_ID, "verdict": "UP", "comment": None},
}


def _call_stub(route: APIRoute, body: BaseModel | None) -> Any:
    """Стабы не ждут ничего асинхронного: корутина завершается на первом шаге.
    Без asyncio.run — модуль может импортироваться внутри уже запущенного цикла (uvicorn)."""
    kwargs: dict[str, Any] = {}
    for name, param in inspect.signature(route.endpoint).parameters.items():
        if name == "body":
            kwargs[name] = body
        elif name == "application_id":
            kwargs[name] = UUID(EXAMPLE_ID)
        elif name == "settings":
            kwargs[name] = Settings(demo_auth_enabled=True)
        else:
            kwargs[name] = None if param.default is inspect.Parameter.empty else param.default
    coro = route.endpoint(**kwargs)
    try:
        coro.send(None)
    except StopIteration as done:
        return done.value
    coro.close()
    raise RuntimeError(f"стаб {route.path} не должен ничего ждать")


def _issued_example(card: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    """Отдельный завершённый C2: оффер → принятие → подписание → выдача."""
    result = deepcopy(card)
    ids = [str(UUID(int=UUID(EXAMPLE_ID).int + i)) for i in range(1, 7)]
    decision_id, offer_id, manager_id, user_id, info_id, info_decision_id = ids
    offer_scoring = {
        **card["scoring"],
        "id": offer_id,
        "kind": "COUNTER_OFFER",
        "monthly_payment_rub": "91804.88",
        "dscr": "1.25",
        "score": 83,
        "factor_points": {"dscr": 30, "bki": 30, "revenue": 8, "age": 15},
        "risk_level": "LOW",
        "reason_codes": ["REVENUE_DECLINE"],
        "positive_codes": ["DSCR_MEETS_TARGET", "CLEAN_CREDIT_HISTORY", "ESTABLISHED_BUSINESS"],
    }
    result.update(
        {
            "revision": 7,
            "status": "ISSUED",
            "requested_amount_rub": "2340000.00",
            "scoring": offer_scoring,
            "ai_report": {**card["ai_report"], "scoring_result_id": offer_id},
            "allowed_actions": [],
            "decisions": [
                {
                    "id": info_decision_id,
                    "proposal_id": EXAMPLE_ID,
                    "manager_user_id": manager_id,
                    "action": "REQUEST_INFO",
                    "client_reason_code": None,
                    "comment": None,
                    "created_at": "2026-10-21T09:01:00Z",
                },
                {
                    "id": decision_id,
                    "proposal_id": EXAMPLE_ID,
                    "manager_user_id": manager_id,
                    "action": "COUNTER_OFFER",
                    "client_reason_code": "HIGH_DEBT_LOAD",
                    "comment": "Уменьшаем сумму до лимита на 36 месяцев",
                    "created_at": "2026-10-21T09:03:00Z",
                },
            ],
            "offers": [
                {
                    "id": offer_id,
                    "decision_id": decision_id,
                    "amount_rub": "2340000.00",
                    "term_months": 36,
                    "product_id": "investment",
                    "annual_rate_pct": "24.00",
                    "monthly_payment_rub": contract["monthly_payment_rub"],
                    "overpayment_rub": contract["overpayment_rub"],
                    "scoring": offer_scoring,
                    "status": "ACCEPTED",
                    "created_at": "2026-10-21T09:03:00Z",
                }
            ],
            "info_requests": [
                {
                    "id": info_id,
                    "decision_id": info_decision_id,
                    "question_text": "Подтвердите стоимость печи",
                    "answer_text": "Стоимость 3 млн рублей",
                    "answered_at": "2026-10-21T09:02:00Z",
                    "created_at": "2026-10-21T09:01:00Z",
                }
            ],
            "contract": {
                **contract,
                "id": EXAMPLE_ID,
                "status": "ISSUED",
                "signed_by_user_id": user_id,
                "signed_at": "2026-10-21T09:05:00Z",
                "issued_at": "2026-10-21T09:05:04Z",
            },
            "sign_challenges": [
                {
                    "id": EXAMPLE_ID,
                    "created_at": "2026-10-21T09:04:00Z",
                    "expires_at": "2026-10-21T09:09:00Z",
                    "attempts": 1,
                    "used_at": "2026-10-21T09:05:00Z",
                }
            ],
            "timeline": [
                {
                    "id": ids[i],
                    "actor_user_id": actor,
                    "from_status": before,
                    "to_status": after,
                    "created_at": timestamp,
                }
                for i, (actor, before, after, timestamp) in enumerate(
                    [
                        (manager_id, "UNDER_REVIEW", "NEED_INFO", "2026-10-21T09:01:00Z"),
                        (user_id, "NEED_INFO", "UNDER_REVIEW", "2026-10-21T09:02:00Z"),
                        (manager_id, "UNDER_REVIEW", "COUNTER_OFFER", "2026-10-21T09:03:00Z"),
                        (user_id, "COUNTER_OFFER", "APPROVED", "2026-10-21T09:04:00Z"),
                        (user_id, "APPROVED", "SIGNED", "2026-10-21T09:05:00Z"),
                        (None, "SIGNED", "ISSUED", "2026-10-21T09:05:04Z"),
                    ]
                )
            ],
        }
    )
    return ManagerApplicationView.model_validate(result).model_dump(mode="json")


def attach_examples(routers: tuple[APIRouter, ...]) -> None:
    contract = next(
        jsonable_encoder(_call_stub(route, None))
        for router in routers
        for route in router.routes
        if isinstance(route, APIRoute) and route.response_model is ContractView
    )
    for router in routers:
        for route in router.routes:
            if not isinstance(route, APIRoute):
                continue
            extra: dict[str, Any] = {}
            body_param = inspect.signature(route.endpoint).parameters.get("body")
            body = None
            if body_param is not None:
                model = body_param.annotation
                example = REQUEST_EXAMPLES[model]  # KeyError = забыли пример для новой модели
                body = TypeAdapter(model).validate_python(example)
                extra["requestBody"] = {"content": {"application/json": {"example": example}}}
            status = route.status_code or 200
            if status != 204:
                value = jsonable_encoder(_call_stub(route, body))
                content: dict[str, Any] = {"example": value}
                if route.response_model is ManagerApplicationView:
                    content = {
                        "examples": {
                            "under_review": {"value": value},
                            "issued": {"value": _issued_example(value, contract)},
                        }
                    }
                if route.path.endswith("/offer-preview"):
                    cases = {
                        "valid": value,
                        "above_limit": {
                            **value,
                            "monthly_payment_rub": "117698.56",
                            "dscr": "1.10",
                            "score": 63,
                            "risk_level": "MODERATE",
                            "valid": False,
                            "violations": ["AMOUNT_ABOVE_LIMIT", "OFFER_NOT_IMPROVED"],
                        },
                        "skipped": {
                            "calculation_status": "SKIPPED",
                            "valid": False,
                            "violations": ["CALCULATION_SKIPPED"],
                            "monthly_payment_rub": None,
                            "dscr": None,
                            "score": None,
                            "risk_level": None,
                            "limit_for_term_rub": None,
                        },
                    }
                    content = {
                        "examples": {
                            name: {
                                "value": TypeAdapter(OfferPreviewResponse)
                                .validate_python(case)
                                .model_dump(mode="json")
                            }
                            for name, case in cases.items()
                        }
                    }
                extra["responses"] = {str(status): {"content": {"application/json": content}}}
            route.openapi_extra = {**(route.openapi_extra or {}), **extra}


def preserve_nullable_examples(app: FastAPI, routers: tuple[APIRouter, ...], prefix: str) -> None:
    """FastAPI сериализует OpenAPI с exclude_none=True, в том числе внутри examples.

    Возвращаем исходные валидированные примеры после генерации схем: required nullable
    поля (например report в PENDING) должны присутствовать как null. Экспортёр остаётся
    обычным вызовом app.openapi(); JSON-файл вручную не корректируется.
    """
    generate = app.openapi

    def openapi() -> dict[str, Any]:
        spec = generate()
        for router in routers:
            for route in router.routes:
                if not isinstance(route, APIRoute) or not route.openapi_extra:
                    continue
                for method in route.methods or ():
                    operation = spec["paths"].get(prefix + route.path, {}).get(method.lower())
                    if operation is None:
                        continue
                    extra = route.openapi_extra
                    request = extra.get("requestBody", {}).get("content", {})
                    for media, content in request.items():
                        operation["requestBody"]["content"][media].update(deepcopy(content))
                    for status, response in extra.get("responses", {}).items():
                        for media, content in response.get("content", {}).items():
                            operation["responses"][status]["content"][media].update(
                                deepcopy(content)
                            )
        return spec

    app.openapi = openapi  # type: ignore[method-assign]
