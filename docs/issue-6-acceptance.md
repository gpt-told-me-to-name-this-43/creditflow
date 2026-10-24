# Issue #6 — запись принятого решения Design 2.5 для Lead

Целевая спецификация Design 2.5 принята. GitHub Issue автоматически не изменялся.
Перед merge Lead фиксирует следующую замену прежнего требования «шесть статусов каждому»:

> Каждый endpoint в OpenAPI документирует все применимые HTTP-статусы ошибок с конкретными
> ErrorCode, схемами ответа и условиями возникновения. Неприменимые статусы не добавляются
> искусственно. Общие инфраструктурные ошибки описываются отдельно. Health использует
> собственный контракт.

Источник ожидаемого поведения — вручную поддерживаемый api/contract/http_matrix.yaml;
тест сверяет его с OpenAPI, docs/api-matrix.md генерируется из YAML и проверяется CI.
Публичные маршруты не получают фиктивных 401/403, GET — конфликтов revision. При этом
GET /company и клиентские /applications* имеют 409 COMPANY_NOT_BOUND, preview —
409 INVALID_STATUS_TRANSITION вне UNDER_REVIEW. PROVIDER_UNAVAILABLE только у binding/Submit,
LLM деградирует без HTTP 503, health 503 возвращает HealthResponse.

Дополнения freeze: объектный типизированный error.details, новые доменные коды,
ProductConstraint, OfferConstraints, 200/201 создания и 200/202 AI report,
purpose_text ≤1000, 429 challenge, SIGN_CHALLENGE_EXPIRED и правила попыток,
основной C2 2 340 000 / 36 с сохранением исходного запроса; каталог products-v2
с working_capital 25% по Design 2.5 и независимо исправленные зависимые эталоны C3/C5/C6. Подробности — api-changelog.md.

JWT/RBAC/ownership остаются #5, FSM/Submit — #7, AI — #8; стабы выключены в production.
Просьба Lead зафиксировать это решение в Issue и подтвердить PR #12 перед выпуском тега.
