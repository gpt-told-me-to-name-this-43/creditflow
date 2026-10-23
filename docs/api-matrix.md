# HTTP-матрица API v1 — Design 2.5

Генерируется `make api-matrix` из `api/contract/http_matrix.yaml`. Не редактировать вручную.
Ожидания независимы от OpenAPI; `test_http_policy.py` сверяет операции, статусы, схемы, коды и security.
Все маршруты контракта, кроме health, — стабы local/test; production предоставляет только health.
`/_test/reset` дополнительно требует TEST_RESET_ENABLED и отдельный токен; не входит в экспорт по умолчанию.
500 INTERNAL_ERROR / 503 SERVICE_UNAVAILABLE — общая инфраструктура, не вызов ext-sim.

| Метод | Путь | Доступ | Статус | Модель | ErrorCode |
|---|---|---|---|---|---|
| POST | `/api/v1/auth/login` | public | 200 | TokenResponse | — |
| POST | `/api/v1/auth/login` | public | 401 | ErrorEnvelope | INVALID_CREDENTIALS |
| POST | `/api/v1/auth/login` | public | 422 | ErrorEnvelope | VALIDATION_ERROR |
| POST | `/api/v1/auth/login` | public | 429 | ErrorEnvelope | TOO_MANY_ATTEMPTS |
| POST | `/api/v1/auth/login` | public | 500 | ErrorEnvelope | INTERNAL_ERROR |
| POST | `/api/v1/auth/login` | public | 503 | ErrorEnvelope | SERVICE_UNAVAILABLE |
| GET | `/api/v1/auth/me` | Bearer | 200 | Me | — |
| GET | `/api/v1/auth/me` | Bearer | 401 | ErrorEnvelope | UNAUTHORIZED |
| GET | `/api/v1/auth/me` | Bearer | 500 | ErrorEnvelope | INTERNAL_ERROR |
| GET | `/api/v1/auth/me` | Bearer | 503 | ErrorEnvelope | SERVICE_UNAVAILABLE |
| GET | `/api/v1/auth/demo-accounts` | public | 200 | list[DemoAccount] | — |
| GET | `/api/v1/auth/demo-accounts` | public | 404 | ErrorEnvelope | NOT_FOUND |
| GET | `/api/v1/auth/demo-accounts` | public | 500 | ErrorEnvelope | INTERNAL_ERROR |
| GET | `/api/v1/auth/demo-accounts` | public | 503 | ErrorEnvelope | SERVICE_UNAVAILABLE |
| GET | `/api/v1/consents/texts` | public | 200 | list[ConsentText] | — |
| GET | `/api/v1/consents/texts` | public | 500 | ErrorEnvelope | INTERNAL_ERROR |
| GET | `/api/v1/consents/texts` | public | 503 | ErrorEnvelope | SERVICE_UNAVAILABLE |
| POST | `/api/v1/onboarding/company-binding` | CLIENT | 200 | Company | — |
| POST | `/api/v1/onboarding/company-binding` | CLIENT | 401 | ErrorEnvelope | UNAUTHORIZED |
| POST | `/api/v1/onboarding/company-binding` | CLIENT | 403 | ErrorEnvelope | APPLICANT_NOT_AUTHORIZED, FORBIDDEN |
| POST | `/api/v1/onboarding/company-binding` | CLIENT | 409 | ErrorEnvelope | COMPANY_ALREADY_BOUND, USER_ALREADY_BOUND |
| POST | `/api/v1/onboarding/company-binding` | CLIENT | 422 | ErrorEnvelope | COMPANY_NOT_IN_REGISTRY, CONSENT_REQUIRED, INVALID_INN, VALIDATION_ERROR |
| POST | `/api/v1/onboarding/company-binding` | CLIENT | 500 | ErrorEnvelope | INTERNAL_ERROR |
| POST | `/api/v1/onboarding/company-binding` | CLIENT | 503 | ErrorEnvelope | PROVIDER_UNAVAILABLE, SERVICE_UNAVAILABLE |
| GET | `/api/v1/company` | CLIENT | 200 | Company | — |
| GET | `/api/v1/company` | CLIENT | 401 | ErrorEnvelope | UNAUTHORIZED |
| GET | `/api/v1/company` | CLIENT | 403 | ErrorEnvelope | FORBIDDEN |
| GET | `/api/v1/company` | CLIENT | 409 | ErrorEnvelope | COMPANY_NOT_BOUND |
| GET | `/api/v1/company` | CLIENT | 500 | ErrorEnvelope | INTERNAL_ERROR |
| GET | `/api/v1/company` | CLIENT | 503 | ErrorEnvelope | SERVICE_UNAVAILABLE |
| GET | `/api/v1/credit-products` | CLIENT | 200 | list[CreditProduct] | — |
| GET | `/api/v1/credit-products` | CLIENT | 401 | ErrorEnvelope | UNAUTHORIZED |
| GET | `/api/v1/credit-products` | CLIENT | 403 | ErrorEnvelope | FORBIDDEN |
| GET | `/api/v1/credit-products` | CLIENT | 422 | ErrorEnvelope | VALIDATION_ERROR |
| GET | `/api/v1/credit-products` | CLIENT | 500 | ErrorEnvelope | INTERNAL_ERROR |
| GET | `/api/v1/credit-products` | CLIENT | 503 | ErrorEnvelope | SERVICE_UNAVAILABLE |
| POST | `/api/v1/applications` | CLIENT | 200 | ClientApplicationView | — |
| POST | `/api/v1/applications` | CLIENT | 201 | ClientApplicationView | — |
| POST | `/api/v1/applications` | CLIENT | 401 | ErrorEnvelope | UNAUTHORIZED |
| POST | `/api/v1/applications` | CLIENT | 403 | ErrorEnvelope | FORBIDDEN |
| POST | `/api/v1/applications` | CLIENT | 409 | ErrorEnvelope | COMPANY_NOT_BOUND |
| POST | `/api/v1/applications` | CLIENT | 422 | ErrorEnvelope | VALIDATION_ERROR |
| POST | `/api/v1/applications` | CLIENT | 500 | ErrorEnvelope | INTERNAL_ERROR |
| POST | `/api/v1/applications` | CLIENT | 503 | ErrorEnvelope | SERVICE_UNAVAILABLE |
| GET | `/api/v1/applications` | CLIENT | 200 | list[ClientApplicationView] | — |
| GET | `/api/v1/applications` | CLIENT | 401 | ErrorEnvelope | UNAUTHORIZED |
| GET | `/api/v1/applications` | CLIENT | 403 | ErrorEnvelope | FORBIDDEN |
| GET | `/api/v1/applications` | CLIENT | 409 | ErrorEnvelope | COMPANY_NOT_BOUND |
| GET | `/api/v1/applications` | CLIENT | 500 | ErrorEnvelope | INTERNAL_ERROR |
| GET | `/api/v1/applications` | CLIENT | 503 | ErrorEnvelope | SERVICE_UNAVAILABLE |
| GET | `/api/v1/applications/{application_id}` | CLIENT | 200 | ClientApplicationView | — |
| GET | `/api/v1/applications/{application_id}` | CLIENT | 401 | ErrorEnvelope | UNAUTHORIZED |
| GET | `/api/v1/applications/{application_id}` | CLIENT | 403 | ErrorEnvelope | FORBIDDEN |
| GET | `/api/v1/applications/{application_id}` | CLIENT | 404 | ErrorEnvelope | NOT_FOUND |
| GET | `/api/v1/applications/{application_id}` | CLIENT | 409 | ErrorEnvelope | COMPANY_NOT_BOUND |
| GET | `/api/v1/applications/{application_id}` | CLIENT | 422 | ErrorEnvelope | VALIDATION_ERROR |
| GET | `/api/v1/applications/{application_id}` | CLIENT | 500 | ErrorEnvelope | INTERNAL_ERROR |
| GET | `/api/v1/applications/{application_id}` | CLIENT | 503 | ErrorEnvelope | SERVICE_UNAVAILABLE |
| PATCH | `/api/v1/applications/{application_id}` | CLIENT | 200 | ClientApplicationView | — |
| PATCH | `/api/v1/applications/{application_id}` | CLIENT | 401 | ErrorEnvelope | UNAUTHORIZED |
| PATCH | `/api/v1/applications/{application_id}` | CLIENT | 403 | ErrorEnvelope | FORBIDDEN |
| PATCH | `/api/v1/applications/{application_id}` | CLIENT | 404 | ErrorEnvelope | NOT_FOUND |
| PATCH | `/api/v1/applications/{application_id}` | CLIENT | 409 | ErrorEnvelope | COMPANY_NOT_BOUND, INVALID_STATUS_TRANSITION, REVISION_CONFLICT |
| PATCH | `/api/v1/applications/{application_id}` | CLIENT | 422 | ErrorEnvelope | VALIDATION_ERROR |
| PATCH | `/api/v1/applications/{application_id}` | CLIENT | 500 | ErrorEnvelope | INTERNAL_ERROR |
| PATCH | `/api/v1/applications/{application_id}` | CLIENT | 503 | ErrorEnvelope | SERVICE_UNAVAILABLE |
| POST | `/api/v1/applications/{application_id}/interpret` | CLIENT | 200 | InterpretResponse | — |
| POST | `/api/v1/applications/{application_id}/interpret` | CLIENT | 401 | ErrorEnvelope | UNAUTHORIZED |
| POST | `/api/v1/applications/{application_id}/interpret` | CLIENT | 403 | ErrorEnvelope | FORBIDDEN |
| POST | `/api/v1/applications/{application_id}/interpret` | CLIENT | 404 | ErrorEnvelope | NOT_FOUND |
| POST | `/api/v1/applications/{application_id}/interpret` | CLIENT | 409 | ErrorEnvelope | COMPANY_NOT_BOUND, INVALID_STATUS_TRANSITION |
| POST | `/api/v1/applications/{application_id}/interpret` | CLIENT | 422 | ErrorEnvelope | VALIDATION_ERROR |
| POST | `/api/v1/applications/{application_id}/interpret` | CLIENT | 500 | ErrorEnvelope | INTERNAL_ERROR |
| POST | `/api/v1/applications/{application_id}/interpret` | CLIENT | 503 | ErrorEnvelope | SERVICE_UNAVAILABLE |
| POST | `/api/v1/applications/{application_id}/submit` | CLIENT | 200 | ClientApplicationView | — |
| POST | `/api/v1/applications/{application_id}/submit` | CLIENT | 401 | ErrorEnvelope | UNAUTHORIZED |
| POST | `/api/v1/applications/{application_id}/submit` | CLIENT | 403 | ErrorEnvelope | FORBIDDEN |
| POST | `/api/v1/applications/{application_id}/submit` | CLIENT | 404 | ErrorEnvelope | NOT_FOUND |
| POST | `/api/v1/applications/{application_id}/submit` | CLIENT | 409 | ErrorEnvelope | COMPANY_NOT_BOUND, IDEMPOTENCY_IN_PROGRESS, INVALID_STATUS_TRANSITION, REVISION_CONFLICT |
| POST | `/api/v1/applications/{application_id}/submit` | CLIENT | 422 | ErrorEnvelope | APPLICATION_INCOMPLETE, CONSENT_REQUIRED, IDEMPOTENCY_KEY_REUSED, PRODUCT_NOT_ELIGIBLE, VALIDATION_ERROR |
| POST | `/api/v1/applications/{application_id}/submit` | CLIENT | 500 | ErrorEnvelope | INTERNAL_ERROR |
| POST | `/api/v1/applications/{application_id}/submit` | CLIENT | 503 | ErrorEnvelope | PROVIDER_UNAVAILABLE, SERVICE_UNAVAILABLE |
| POST | `/api/v1/applications/{application_id}/info-response` | CLIENT | 200 | ClientApplicationView | — |
| POST | `/api/v1/applications/{application_id}/info-response` | CLIENT | 401 | ErrorEnvelope | UNAUTHORIZED |
| POST | `/api/v1/applications/{application_id}/info-response` | CLIENT | 403 | ErrorEnvelope | FORBIDDEN |
| POST | `/api/v1/applications/{application_id}/info-response` | CLIENT | 404 | ErrorEnvelope | NOT_FOUND |
| POST | `/api/v1/applications/{application_id}/info-response` | CLIENT | 409 | ErrorEnvelope | COMPANY_NOT_BOUND, IDEMPOTENCY_IN_PROGRESS, INVALID_STATUS_TRANSITION, REVISION_CONFLICT |
| POST | `/api/v1/applications/{application_id}/info-response` | CLIENT | 422 | ErrorEnvelope | IDEMPOTENCY_KEY_REUSED, VALIDATION_ERROR |
| POST | `/api/v1/applications/{application_id}/info-response` | CLIENT | 500 | ErrorEnvelope | INTERNAL_ERROR |
| POST | `/api/v1/applications/{application_id}/info-response` | CLIENT | 503 | ErrorEnvelope | SERVICE_UNAVAILABLE |
| POST | `/api/v1/applications/{application_id}/offer/accept` | CLIENT | 200 | ClientApplicationView | — |
| POST | `/api/v1/applications/{application_id}/offer/accept` | CLIENT | 401 | ErrorEnvelope | UNAUTHORIZED |
| POST | `/api/v1/applications/{application_id}/offer/accept` | CLIENT | 403 | ErrorEnvelope | FORBIDDEN |
| POST | `/api/v1/applications/{application_id}/offer/accept` | CLIENT | 404 | ErrorEnvelope | NOT_FOUND |
| POST | `/api/v1/applications/{application_id}/offer/accept` | CLIENT | 409 | ErrorEnvelope | COMPANY_NOT_BOUND, IDEMPOTENCY_IN_PROGRESS, INVALID_STATUS_TRANSITION, REVISION_CONFLICT |
| POST | `/api/v1/applications/{application_id}/offer/accept` | CLIENT | 422 | ErrorEnvelope | IDEMPOTENCY_KEY_REUSED, VALIDATION_ERROR |
| POST | `/api/v1/applications/{application_id}/offer/accept` | CLIENT | 500 | ErrorEnvelope | INTERNAL_ERROR |
| POST | `/api/v1/applications/{application_id}/offer/accept` | CLIENT | 503 | ErrorEnvelope | SERVICE_UNAVAILABLE |
| POST | `/api/v1/applications/{application_id}/offer/decline` | CLIENT | 200 | ClientApplicationView | — |
| POST | `/api/v1/applications/{application_id}/offer/decline` | CLIENT | 401 | ErrorEnvelope | UNAUTHORIZED |
| POST | `/api/v1/applications/{application_id}/offer/decline` | CLIENT | 403 | ErrorEnvelope | FORBIDDEN |
| POST | `/api/v1/applications/{application_id}/offer/decline` | CLIENT | 404 | ErrorEnvelope | NOT_FOUND |
| POST | `/api/v1/applications/{application_id}/offer/decline` | CLIENT | 409 | ErrorEnvelope | COMPANY_NOT_BOUND, IDEMPOTENCY_IN_PROGRESS, INVALID_STATUS_TRANSITION, REVISION_CONFLICT |
| POST | `/api/v1/applications/{application_id}/offer/decline` | CLIENT | 422 | ErrorEnvelope | IDEMPOTENCY_KEY_REUSED, VALIDATION_ERROR |
| POST | `/api/v1/applications/{application_id}/offer/decline` | CLIENT | 500 | ErrorEnvelope | INTERNAL_ERROR |
| POST | `/api/v1/applications/{application_id}/offer/decline` | CLIENT | 503 | ErrorEnvelope | SERVICE_UNAVAILABLE |
| GET | `/api/v1/applications/{application_id}/contract` | CLIENT | 200 | ContractView | — |
| GET | `/api/v1/applications/{application_id}/contract` | CLIENT | 401 | ErrorEnvelope | UNAUTHORIZED |
| GET | `/api/v1/applications/{application_id}/contract` | CLIENT | 403 | ErrorEnvelope | FORBIDDEN |
| GET | `/api/v1/applications/{application_id}/contract` | CLIENT | 404 | ErrorEnvelope | NOT_FOUND |
| GET | `/api/v1/applications/{application_id}/contract` | CLIENT | 409 | ErrorEnvelope | COMPANY_NOT_BOUND |
| GET | `/api/v1/applications/{application_id}/contract` | CLIENT | 422 | ErrorEnvelope | VALIDATION_ERROR |
| GET | `/api/v1/applications/{application_id}/contract` | CLIENT | 500 | ErrorEnvelope | INTERNAL_ERROR |
| GET | `/api/v1/applications/{application_id}/contract` | CLIENT | 503 | ErrorEnvelope | SERVICE_UNAVAILABLE |
| POST | `/api/v1/applications/{application_id}/sign/challenge` | CLIENT | 200 | SignChallenge | — |
| POST | `/api/v1/applications/{application_id}/sign/challenge` | CLIENT | 401 | ErrorEnvelope | UNAUTHORIZED |
| POST | `/api/v1/applications/{application_id}/sign/challenge` | CLIENT | 403 | ErrorEnvelope | FORBIDDEN |
| POST | `/api/v1/applications/{application_id}/sign/challenge` | CLIENT | 404 | ErrorEnvelope | NOT_FOUND |
| POST | `/api/v1/applications/{application_id}/sign/challenge` | CLIENT | 409 | ErrorEnvelope | COMPANY_NOT_BOUND, INVALID_STATUS_TRANSITION, REVISION_CONFLICT |
| POST | `/api/v1/applications/{application_id}/sign/challenge` | CLIENT | 422 | ErrorEnvelope | VALIDATION_ERROR |
| POST | `/api/v1/applications/{application_id}/sign/challenge` | CLIENT | 429 | ErrorEnvelope | TOO_MANY_ATTEMPTS |
| POST | `/api/v1/applications/{application_id}/sign/challenge` | CLIENT | 500 | ErrorEnvelope | INTERNAL_ERROR |
| POST | `/api/v1/applications/{application_id}/sign/challenge` | CLIENT | 503 | ErrorEnvelope | SERVICE_UNAVAILABLE |
| POST | `/api/v1/applications/{application_id}/sign` | CLIENT | 200 | ClientApplicationView | — |
| POST | `/api/v1/applications/{application_id}/sign` | CLIENT | 401 | ErrorEnvelope | UNAUTHORIZED |
| POST | `/api/v1/applications/{application_id}/sign` | CLIENT | 403 | ErrorEnvelope | FORBIDDEN |
| POST | `/api/v1/applications/{application_id}/sign` | CLIENT | 404 | ErrorEnvelope | NOT_FOUND |
| POST | `/api/v1/applications/{application_id}/sign` | CLIENT | 409 | ErrorEnvelope | COMPANY_NOT_BOUND, IDEMPOTENCY_IN_PROGRESS, INVALID_STATUS_TRANSITION, REVISION_CONFLICT |
| POST | `/api/v1/applications/{application_id}/sign` | CLIENT | 422 | ErrorEnvelope | IDEMPOTENCY_KEY_REUSED, SIGN_CHALLENGE_EXPIRED, SIGN_CODE_INVALID, VALIDATION_ERROR |
| POST | `/api/v1/applications/{application_id}/sign` | CLIENT | 429 | ErrorEnvelope | TOO_MANY_ATTEMPTS |
| POST | `/api/v1/applications/{application_id}/sign` | CLIENT | 500 | ErrorEnvelope | INTERNAL_ERROR |
| POST | `/api/v1/applications/{application_id}/sign` | CLIENT | 503 | ErrorEnvelope | SERVICE_UNAVAILABLE |
| GET | `/api/v1/manager/applications` | MANAGER | 200 | list[QueueItem] | — |
| GET | `/api/v1/manager/applications` | MANAGER | 401 | ErrorEnvelope | UNAUTHORIZED |
| GET | `/api/v1/manager/applications` | MANAGER | 403 | ErrorEnvelope | FORBIDDEN |
| GET | `/api/v1/manager/applications` | MANAGER | 422 | ErrorEnvelope | VALIDATION_ERROR |
| GET | `/api/v1/manager/applications` | MANAGER | 500 | ErrorEnvelope | INTERNAL_ERROR |
| GET | `/api/v1/manager/applications` | MANAGER | 503 | ErrorEnvelope | SERVICE_UNAVAILABLE |
| GET | `/api/v1/manager/applications/{application_id}` | MANAGER | 200 | ManagerApplicationView | — |
| GET | `/api/v1/manager/applications/{application_id}` | MANAGER | 401 | ErrorEnvelope | UNAUTHORIZED |
| GET | `/api/v1/manager/applications/{application_id}` | MANAGER | 403 | ErrorEnvelope | FORBIDDEN |
| GET | `/api/v1/manager/applications/{application_id}` | MANAGER | 404 | ErrorEnvelope | NOT_FOUND |
| GET | `/api/v1/manager/applications/{application_id}` | MANAGER | 422 | ErrorEnvelope | VALIDATION_ERROR |
| GET | `/api/v1/manager/applications/{application_id}` | MANAGER | 500 | ErrorEnvelope | INTERNAL_ERROR |
| GET | `/api/v1/manager/applications/{application_id}` | MANAGER | 503 | ErrorEnvelope | SERVICE_UNAVAILABLE |
| POST | `/api/v1/manager/applications/{application_id}/decisions` | MANAGER | 201 | DecisionResponse | — |
| POST | `/api/v1/manager/applications/{application_id}/decisions` | MANAGER | 401 | ErrorEnvelope | UNAUTHORIZED |
| POST | `/api/v1/manager/applications/{application_id}/decisions` | MANAGER | 403 | ErrorEnvelope | FORBIDDEN |
| POST | `/api/v1/manager/applications/{application_id}/decisions` | MANAGER | 404 | ErrorEnvelope | NOT_FOUND |
| POST | `/api/v1/manager/applications/{application_id}/decisions` | MANAGER | 409 | ErrorEnvelope | IDEMPOTENCY_IN_PROGRESS, INVALID_STATUS_TRANSITION, REVISION_CONFLICT |
| POST | `/api/v1/manager/applications/{application_id}/decisions` | MANAGER | 422 | ErrorEnvelope | ACTION_NOT_ALLOWED, AMOUNT_ABOVE_LIMIT, IDEMPOTENCY_KEY_REUSED, VALIDATION_ERROR |
| POST | `/api/v1/manager/applications/{application_id}/decisions` | MANAGER | 500 | ErrorEnvelope | INTERNAL_ERROR |
| POST | `/api/v1/manager/applications/{application_id}/decisions` | MANAGER | 503 | ErrorEnvelope | SERVICE_UNAVAILABLE |
| POST | `/api/v1/manager/applications/{application_id}/offer-preview` | MANAGER | 200 | OfferPreviewResponse | — |
| POST | `/api/v1/manager/applications/{application_id}/offer-preview` | MANAGER | 401 | ErrorEnvelope | UNAUTHORIZED |
| POST | `/api/v1/manager/applications/{application_id}/offer-preview` | MANAGER | 403 | ErrorEnvelope | FORBIDDEN |
| POST | `/api/v1/manager/applications/{application_id}/offer-preview` | MANAGER | 404 | ErrorEnvelope | NOT_FOUND |
| POST | `/api/v1/manager/applications/{application_id}/offer-preview` | MANAGER | 409 | ErrorEnvelope | INVALID_STATUS_TRANSITION |
| POST | `/api/v1/manager/applications/{application_id}/offer-preview` | MANAGER | 422 | ErrorEnvelope | VALIDATION_ERROR |
| POST | `/api/v1/manager/applications/{application_id}/offer-preview` | MANAGER | 500 | ErrorEnvelope | INTERNAL_ERROR |
| POST | `/api/v1/manager/applications/{application_id}/offer-preview` | MANAGER | 503 | ErrorEnvelope | SERVICE_UNAVAILABLE |
| GET | `/api/v1/manager/applications/{application_id}/ai-report` | MANAGER | 200 | AiReportView | — |
| GET | `/api/v1/manager/applications/{application_id}/ai-report` | MANAGER | 401 | ErrorEnvelope | UNAUTHORIZED |
| GET | `/api/v1/manager/applications/{application_id}/ai-report` | MANAGER | 403 | ErrorEnvelope | FORBIDDEN |
| GET | `/api/v1/manager/applications/{application_id}/ai-report` | MANAGER | 404 | ErrorEnvelope | NOT_FOUND |
| GET | `/api/v1/manager/applications/{application_id}/ai-report` | MANAGER | 422 | ErrorEnvelope | VALIDATION_ERROR |
| GET | `/api/v1/manager/applications/{application_id}/ai-report` | MANAGER | 500 | ErrorEnvelope | INTERNAL_ERROR |
| GET | `/api/v1/manager/applications/{application_id}/ai-report` | MANAGER | 503 | ErrorEnvelope | SERVICE_UNAVAILABLE |
| POST | `/api/v1/manager/applications/{application_id}/ai-report` | MANAGER | 200 | AiReportView | — |
| POST | `/api/v1/manager/applications/{application_id}/ai-report` | MANAGER | 202 | AiReportView | — |
| POST | `/api/v1/manager/applications/{application_id}/ai-report` | MANAGER | 401 | ErrorEnvelope | UNAUTHORIZED |
| POST | `/api/v1/manager/applications/{application_id}/ai-report` | MANAGER | 403 | ErrorEnvelope | FORBIDDEN |
| POST | `/api/v1/manager/applications/{application_id}/ai-report` | MANAGER | 404 | ErrorEnvelope | NOT_FOUND |
| POST | `/api/v1/manager/applications/{application_id}/ai-report` | MANAGER | 422 | ErrorEnvelope | VALIDATION_ERROR |
| POST | `/api/v1/manager/applications/{application_id}/ai-report` | MANAGER | 500 | ErrorEnvelope | INTERNAL_ERROR |
| POST | `/api/v1/manager/applications/{application_id}/ai-report` | MANAGER | 503 | ErrorEnvelope | SERVICE_UNAVAILABLE |
| POST | `/api/v1/manager/applications/{application_id}/ai-feedback` | MANAGER | 204 | без тела | — |
| POST | `/api/v1/manager/applications/{application_id}/ai-feedback` | MANAGER | 401 | ErrorEnvelope | UNAUTHORIZED |
| POST | `/api/v1/manager/applications/{application_id}/ai-feedback` | MANAGER | 403 | ErrorEnvelope | FORBIDDEN |
| POST | `/api/v1/manager/applications/{application_id}/ai-feedback` | MANAGER | 404 | ErrorEnvelope | NOT_FOUND |
| POST | `/api/v1/manager/applications/{application_id}/ai-feedback` | MANAGER | 422 | ErrorEnvelope | VALIDATION_ERROR |
| POST | `/api/v1/manager/applications/{application_id}/ai-feedback` | MANAGER | 500 | ErrorEnvelope | INTERNAL_ERROR |
| POST | `/api/v1/manager/applications/{application_id}/ai-feedback` | MANAGER | 503 | ErrorEnvelope | SERVICE_UNAVAILABLE |
| GET | `/api/v1/manager/stats` | MANAGER | 200 | ManagerStats | — |
| GET | `/api/v1/manager/stats` | MANAGER | 401 | ErrorEnvelope | UNAUTHORIZED |
| GET | `/api/v1/manager/stats` | MANAGER | 403 | ErrorEnvelope | FORBIDDEN |
| GET | `/api/v1/manager/stats` | MANAGER | 500 | ErrorEnvelope | INTERNAL_ERROR |
| GET | `/api/v1/manager/stats` | MANAGER | 503 | ErrorEnvelope | SERVICE_UNAVAILABLE |
| GET | `/api/v1/health` | public | 200 | HealthResponse | — |
| GET | `/api/v1/health` | public | 503 | HealthResponse | — |
| POST | `/api/v1/_test/reset` | TestResetToken | 200 | TestResetResult | — |
| POST | `/api/v1/_test/reset` | TestResetToken | 404 | ErrorEnvelope | NOT_FOUND |
| POST | `/api/v1/_test/reset` | TestResetToken | 422 | ErrorEnvelope | VALIDATION_ERROR |
| POST | `/api/v1/_test/reset` | TestResetToken | 500 | ErrorEnvelope | INTERNAL_ERROR |
| POST | `/api/v1/_test/reset` | TestResetToken | 503 | ErrorEnvelope | SERVICE_UNAVAILABLE |

Условия ошибок и формат details: [api.md](api.md).
GET /company и /applications* имеют 409 COMPANY_NOT_BOUND независимо от revision.
409 offer-preview означает статус вне UNDER_REVIEW; бизнес-нарушения возвращаются в 200 valid=false.
LLM возвращает UNAVAILABLE/FALLBACK без PROVIDER_UNAVAILABLE.
