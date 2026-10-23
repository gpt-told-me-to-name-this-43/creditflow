"""Примеры запросов и ответов в OpenAPI для стабов контракта v1 (issue #6: «Все эндпоинты
в Swagger с примерами»).

- Пример запроса берётся из `REQUEST_EXAMPLES` и при старте валидируется своей моделью:
  невалидный пример роняет импорт, а не попадает к фронту.
- Пример ответа строит чистая sync-функция, привязанная к маршруту через `@example_from`.
  Ту же функцию вызывает стаб, поэтому пример совпадает с моком и проходит `response_model`.
  Сам endpoint при генерации НЕ вызывается: когда #5/#7 добавят в обработчики `await`,
  БД или зависимости, экспорт контракта и импорт приложения от этого не сломаются.
- Время в примерах фиксировано (`EXAMPLE_NOW`), поэтому `docs/openapi.json` детерминирован.
- Всё кладётся в `route.openapi_extra`, который FastAPI сливает с операцией, не трогая
  сгенерированные схемы.
"""

import inspect
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
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
EXAMPLE_NOW = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)  # = APP_AS_OF_DATE, примеры стабильны
_BUILDER_ATTR = "__openapi_example_builder__"

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


def example_from[F: Callable[..., Any]](builder: Callable[..., Any]) -> Callable[[F], F]:
    """Привязывает к endpoint чистую функцию, которая строит пример его ответа."""

    def mark(endpoint: F) -> F:
        setattr(endpoint, _BUILDER_ATTR, builder)
        return endpoint

    return mark


def _example_kwargs(builder: Callable[..., Any], body: BaseModel | None) -> dict[str, Any]:
    """Аргументы builder берутся из примера запроса и фиксированных значений, а не из
    запроса FastAPI: builder — обычная функция, и её параметры известны заранее."""
    known: dict[str, Any] = {
        "body": body,
        "application_id": UUID(EXAMPLE_ID),
        "now": EXAMPLE_NOW,
        "settings": Settings(demo_auth_enabled=True),
    }
    kwargs: dict[str, Any] = {}
    for name, param in inspect.signature(builder).parameters.items():
        if name in known:
            kwargs[name] = known[name]
        elif param.default is not inspect.Parameter.empty:
            kwargs[name] = param.default
        else:
            kwargs[name] = None  # query-фильтры стабов: пример — без фильтра
    return kwargs


def _build_example(route: APIRoute, body: BaseModel | None) -> Any:
    builder = getattr(route.endpoint, _BUILDER_ATTR, None)
    if builder is None:
        raise RuntimeError(f"{route.path}: нет @example_from — пример ответа не из чего строить")
    result = builder(**_example_kwargs(builder, body))
    if inspect.isawaitable(result):
        if inspect.iscoroutine(result):
            result.close()  # не оставляем неожиданную корутину висеть до GC
        raise TypeError(f"{route.path}: builder примера должен быть sync-функцией")
    return result


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
            # Запрос клиента не переписывается встречным предложением: 3 000 000 остаётся
            # в заявке, 2 340 000 — в offers[] и в договоре (design §3.5, insert-only история).
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
    view = ManagerApplicationView.model_validate(result).model_dump(mode="json")
    check_history(card, view)
    return view


def check_history(card: dict[str, Any], issued: dict[str, Any]) -> None:
    """Согласованность сценария «оффер → выдача»; нарушение роняет импорт, а не уходит фронту.

    - запрошенные условия заявки не меняются оффером;
    - договор = принятый оффер (сумма, срок, платёж);
    - timeline — непрерывная цепочка от статуса карточки до текущего статуса,
      время не убывает;
    - offers и info_requests ссылаются на существующие решения нужного типа.
    """
    problems = []
    for field in ("requested_amount_rub", "term_months", "product_id"):
        if issued[field] != card[field]:
            problems.append(f"{field}: {card[field]} → {issued[field]}")
    accepted = [o for o in issued["offers"] if o["status"] == "ACCEPTED"]
    if len(accepted) != 1:
        problems.append(f"ожидается один ACCEPTED-оффер, найдено {len(accepted)}")
    else:
        offer, contract = accepted[0], issued["contract"]
        for o_field, c_field in (
            ("amount_rub", "amount_rub"),
            ("term_months", "term_months"),
            ("monthly_payment_rub", "monthly_payment_rub"),
        ):
            if offer[o_field] != contract[c_field]:
                problems.append(f"оффер.{o_field} ≠ договор.{c_field}")
        if offer["amount_rub"] == issued["requested_amount_rub"]:
            problems.append("встречное предложение не отличается от запроса")
    timeline = issued["timeline"]
    status = card["status"]
    for event in timeline:
        if event["from_status"] != status:
            problems.append(f"разрыв timeline: {status} → {event['from_status']}")
        status = event["to_status"]
    if status != issued["status"]:
        problems.append(f"timeline заканчивается {status}, а статус {issued['status']}")
    times = [e["created_at"] for e in timeline]
    if times != sorted(times):
        problems.append("время событий timeline убывает")
    actions = {d["id"]: d["action"] for d in issued["decisions"]}
    for offer in issued["offers"]:
        if actions.get(offer["decision_id"]) != "COUNTER_OFFER":
            problems.append(f"оффер {offer['id']} без решения COUNTER_OFFER")
    for info in issued["info_requests"]:
        if actions.get(info["decision_id"]) != "REQUEST_INFO":
            problems.append(f"дозапрос {info['id']} без решения REQUEST_INFO")
    if problems:
        raise ValueError("Пример выданной заявки несогласован: " + "; ".join(problems))


def attach_examples(routers: tuple[APIRouter, ...]) -> None:
    # Договор нужен для примера «issued» карточки менеджера; без маршрута договора
    # (например, в тестовом роутере) этот пример просто не строится.
    contract = next(
        (
            jsonable_encoder(_build_example(route, None))
            for router in routers
            for route in router.routes
            if isinstance(route, APIRoute) and route.response_model is ContractView
        ),
        None,
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
                value = jsonable_encoder(_build_example(route, body))
                content: dict[str, Any] = {"example": value}
                if route.response_model is ManagerApplicationView and contract is not None:
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
