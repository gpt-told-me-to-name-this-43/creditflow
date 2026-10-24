# API v1 — Design 2.5

Контракт: [openapi.json](openapi.json), экспорт `make openapi`. Пути включают `/api/v1`;
base URL клиента — origin, без повторного `/api/v1`. Swagger — `/api/docs`.
HTTP-эталон поддерживается вручную в `api/contract/http_matrix.yaml`, независимо от OpenAPI.
[api-matrix.md](api-matrix.md) генерируется `make api-matrix`; тесты и CI проверяют совпадение.
[Frontend handoff](frontend-handoff.md) содержит команды и сценарии MSW.

Design 2.5 утверждён как целевая спецификация. Старое правило Issue #6 «шесть статусов
на каждый endpoint» заменено применимостью ошибок. Запись решения в GitHub и Lead review
выполняются перед merge; это не повторное обсуждение принятой HTTP-политики.
Тег `contract-v1` ещё не выпущен. Правила будущих изменений: [api-changelog.md](api-changelog.md).

## Формат и коды ошибок

```json
{"error":{"code":"APPLICATION_INCOMPLETE","message":"Заполнены не все обязательные поля","details":{"missing_fields":["term_months","product_id"]}}}
```

`ErrorEnvelope.error.code` соответствует HTTP-статусу по `ERROR_STATUS`.
`error.details` — необязательный объект с именованными полями. Массив, старые
`loc/msg/type` и отдельное `error.attempts_remaining` больше не используются.
`details` типизирован отдельными строгими DTO; неизвестные поля запрещены.

| ErrorCode | HTTP | Условие и действие интерфейса |
|---|---|---|
| `UNAUTHORIZED` | 401 | Нет/невалиден Bearer; войти заново |
| `INVALID_CREDENTIALS` | 401 | Login отклоняет учётные данные, без различения логина и пароля |
| `FORBIDDEN` | 403 | Недостаточно прав роли; запретить действие |
| `APPLICANT_NOT_AUTHORIZED` | 403 | ИНН и нормализованное ФИО не совпали с руководителем/ИП |
| `NOT_FOUND` | 404 | Объект отсутствует или чужой; договор до APPROVED, AI до Submit |
| `COMPANY_NOT_BOUND` | 409 | GET /company и все клиентские /applications*: перейти на привязку |
| `COMPANY_ALREADY_BOUND` | 409 | Компания уже принадлежит другому клиенту |
| `USER_ALREADY_BOUND` | 409 | Клиент уже привязал другую компанию |
| `REVISION_CONFLICT` | 409 | Устарела revision; перечитать карточку и предложить повтор с сохранённым вводом |
| `INVALID_STATUS_TRANSITION` | 409 | Неверный статус; interpret только DRAFT, preview только UNDER_REVIEW |
| `IDEMPOTENCY_IN_PROGRESS` | 409 | Тот же ключ обрабатывается; подождать и повторить тот же запрос |
| `VALIDATION_ERROR` | 422 | Pydantic: body/query/path/header; подсветить details.fields |
| `INVALID_INN` | 422 | Формат или контрольная сумма ИНН |
| `COMPANY_NOT_IN_REGISTRY` | 422 | Реестр вернул 404; это не объектный NOT_FOUND API |
| `CONSENT_REQUIRED` | 422 | Нет актуального согласия ПД или БКИ |
| `APPLICATION_INCOMPLETE` | 422 | Submit: нет обязательных полей, подсветить missing_fields |
| `PRODUCT_NOT_ELIGIBLE` | 422 | Submit: условия не подходят продукту, показать unmet_constraints |
| `ACTION_NOT_ALLOWED` | 422 | Менеджерское действие отсутствует в allowed_actions |
| `AMOUNT_ABOVE_LIMIT` | 422 | Решение COUNTER_OFFER превышает limit_for_term |
| `SIGN_CODE_INVALID` | 422 | Первая/вторая неверная попытка; показать remaining_attempts |
| `SIGN_CHALLENGE_EXPIRED` | 422 | Challenge неизвестен, чужой, просрочен, использован или заменён; запросить новый |
| `IDEMPOTENCY_KEY_REUSED` | 422 | Ключ использован с другим запросом; создать новый для изменённого действия |
| `TOO_MANY_ATTEMPTS` | 429 | LOGIN/CHALLENGE_ISSUE: ждать Retry-After; SIGN_ATTEMPTS: новый challenge |
| `BAD_REQUEST` | 400 | HTTP 4xx без предусмотренного кода; неизвестный 4xx нормализуется в 400 |
| `METHOD_NOT_ALLOWED` | 405 | Неверный метод; сохраняется Allow |
| `INTERNAL_ERROR` | 500 | Необработанная ошибка/неизвестный 5xx; подробности только в логе |
| `SERVICE_UNAVAILABLE` | 503 | Предусмотренный инфраструктурный отказ, например БД |
| `PROVIDER_UNAVAILABLE` | 503 | ext-sim при company-binding/Submit; повторить позже |

| ErrorCode | Типизированный details |
|---|---|
| VALIDATION_ERROR | `fields: [{field: string, code: string, message: string}]` |
| APPLICATION_INCOMPLETE | `missing_fields: string[]` |
| PRODUCT_NOT_ELIGIBLE | `product_id: string, unmet_constraints: ProductConstraint[]` |
| REVISION_CONFLICT | `current_revision: int` |
| SIGN_CODE_INVALID | `remaining_attempts: int` (0–2) |
| TOO_MANY_ATTEMPTS | `scope: LOGIN / SIGN_ATTEMPTS / CHALLENGE_ISSUE`, `retry_after_seconds?: int` |

Валидационные пути: `body.requested_amount_rub`, `body.items.0.code`, `query.amount`,
`path.application_id`, `header.Idempotency-Key`. Индексы с нуля, разделитель — точка.
Коды Pydantic переводятся в uppercase; ограничения gt/ge/lt/le — `OUT_OF_RANGE`.
`input` и `ctx` не отправляются клиенту, чтобы не раскрывать пароли и содержимое запроса.

`Allow`, `WWW-Authenticate`, `Retry-After` сохраняются обработчиками. `Retry-After` —
целые секунды. Третья неверная попытка подписания: 429, `scope=SIGN_ATTEMPTS`, без
`Retry-After` и `retry_after_seconds`; challenge недействителен, новый можно запросить сразу.
LOGIN и CHALLENGE_ISSUE используют задержку и Retry-After. Прокси может вернуть не-JSON;
это транспортная ошибка, её нельзя распознавать как ErrorEnvelope без проверки ответа.

## Доступ и пределы реализации

Публичны login, demo-accounts, consents/texts, health. Login имеет собственный 401,
но не фиктивный 403. `/auth/me` требует Bearer и доступен обеим ролям.
Остальные операции требуют Bearer, CLIENT либо MANAGER согласно YAML.
Чужие клиентские объекты маскируются 404, а не 403 (реализация #5/#7).

Без привязанной компании разрешены auth, consents/texts, company-binding, credit-products,
health; защищённые из них всё равно требуют Bearer. GET /company и клиентские
/applications* декларируют 409 COMPANY_NOT_BOUND, включая GET. Менеджеру компания не нужна.

В #6 стабы проверяют только наличие Bearer, не JWT/роль/ownership и не сохраняют состояние.
Они не являются безопасным backend. В production зарегистрирован только health; тестовые
флаги блокируют запуск production. Полные проверки — #5; FSM/БД — #7; AI — #8.
`/_test/reset` доступен только local/test + TEST_RESET_ENABLED с X-Test-Reset-Token ≥32 байт;
сравнение constant time, отказ — 404. Без флага маршрут отсутствует; в обычный экспорт не входит.

Привязка: формат/контрольная сумма ИНН → версия ПД → реестр → ИНН и нормализованное ФИО
(NFC, ё→е, lowercase, пробелы) → уникальность. Повтор той же компании тем же клиентом — 200.
Ликвидация не блокирует привязку; стоп-факторы проверяются Submit.

## Заявка, конфликты и продукты

POST /applications: 201 новый DRAFT, 200 существующий DRAFT без применения тела.
Изменения — только PATCH; purpose_text необязателен и ≤1000 символов во всех входных DTO.
Стаб всегда показывает создание, не имитирует конкурентное хранение.
В #7 добавить частичный уникальный индекс `uq_applications_one_draft` на реальную таблицу
`applications(owner_user_id) WHERE status='DRAFT'`; затем INSERT ON CONFLICT по этому
предикату DO NOTHING + SELECT. В текущей базовой миграции такого индекса ещё нет.

PATCH пропускает отсутствующие поля и очищает явно переданные null. Frontend передаёт
terms_field_sources; terms_source вычисляет backend (LLM_CONFIRMED → RULES_CONFIRMED → MANUAL
по наличию источников). Отправка terms_source клиентом запрещена extra=forbid.
allowed_actions — разрешения API на действия; валидация обязательных полей формы остаётся нужна.

Revision передают PATCH, submit, info-response, offer accept/decline, sign/challenge, sign,
manager decisions. Interpret не пишет и не требует revision, но допускается только в DRAFT.
Preview не пишет и не требует revision, но вне UNDER_REVIEW даёт 409.
AI report/feedback не требуют и не меняют revision. GET не получает REVISION_CONFLICT;
COMPANY_NOT_BOUND — самостоятельный предусмотренный конфликт состояния привязки.

Idempotency-Key обязателен у submit, info-response, offer accept/decline, sign, decisions.
Новый UUID на действие, тот же ключ и неизменное тело на сетевой повтор. Ответы 4xx/5xx
не кешируются; при изменении ввода использовать новый ключ. После REVISION_CONFLICT
перечитать заявку и предложить повтор, не перезаписывая пользовательский ввод молча.

Submit требует purpose_code, requested_amount_rub, term_months, product_id.
purpose_text не обязателен. Заполненность → APPLICATION_INCOMPLETE; пригодность продукта →
PRODUCT_NOT_ELIGIBLE; версия БКИ → CONSENT_REQUIRED. ext-sim отказ → PROVIDER_UNAVAILABLE,
заявка остаётся DRAFT. Финансовый конвейер реализует #7.

ProductConstraint един для каталога и details продукта: PURPOSE_NOT_ALLOWED,
AMOUNT_BELOW_PRODUCT_MIN, AMOUNT_ABOVE_PRODUCT_MAX, TERM_BELOW_PRODUCT_MIN,
TERM_ABOVE_PRODUCT_MAX. unmet_constraints — строки enum, не объекты; пределы есть в CreditProduct.
Каталог C2 возвращает оба продукта: investment suitable=true; working_capital=false с
PURPOSE_NOT_ALLOWED и TERM_ABOVE_PRODUCT_MAX. Платёж только для подходящего продукта.

Деньги в ответах — строки с двумя знаками; входные суммы — положительные целые рубли.
Money допускает знак для финансовых рядов; MoneyStr в OfferConstraints — `^\d+\.\d{2}$`.
Frontend форматирует строки, не выводит кредитные решения, DSCR или лимит самостоятельно.

## Менеджер и основной C2

ManagerApplicationView.offer_constraints — обязательное nullable поле строгого OfferConstraints:
min_amount_rub, max_amount_rub, min_term_months, max_term_months. Оно не null ровно тогда,
когда COUNTER_OFFER есть в allowed_actions. Пределы продукта — границы формы; проверка
конкретного оффера выполняется backend preview, а не вычисляется frontend.

Offer preview: вне UNDER_REVIEW — 409; невалидная структура — 422; бизнес-нарушение —
200 valid=false и violations. При OK рассчитанные метрики доступны даже при valid=false;
при SKIPPED метрики null. Предпросмотр не пишет БД.

Главный C2: исходные 3 000 000 / 36 / 24% сохраняются после accept. Оффер и договор —
2 340 000 / 36, платёж 91804.88, переплата 964975.43. Текущий scoring после accept —
расчёт оффера. 3 000 000 / 54 (M11) — отдельный пример, не основной C2.
Клиентские monthly_payment/overpayment описывают исходный запрос; принятые условия —
в offer и contract. Формулы ядра и инвестиционные эталоны не менялись. Каталог products-v2 по Design 2.5:
investment 24%, working_capital 25%; исправлены зависимые эталоны C3/C5/C6, см. demo-data.md.

QueueItem содержит ИНН и product_id. Карточка компании типизирует форму, ОКВЭД, дату регистрации;
scoring.account_history_months — h. Имена авторов доступны в истории без отдельного lookup.
AI-статистика имеет ai_feedback_groups с total/up_count/up_share, группировка по prompt/model/source;
при total<5 интерфейс показывает «Недостаточно оценок». total=0 → up_share=null.
Старое ai_feedback_up_share сохранено. Распределение рекомендаций относится к UNDER_REVIEW;
время до первого решения — от submitted_at; доля совпадений считается по решениям с рекомендацией
их proposal, не по изменяемому текущему scoring. Отсутствие наблюдений → null, не 0%.

## Подписание, AI и инфраструктура

Challenge: TTL 5 минут, новый отменяет предыдущий, ≤5 на заявку за 15 минут.
Выдача сверх лимита — 429 CHALLENGE_ISSUE с Retry-After. demo_code опционален и присутствует только в демо-режиме.
Для sign использовать revision из challenge; неуспешная попытка revision не меняет.
Первые две неверные попытки — 422 SIGN_CODE_INVALID; третья — 429 SIGN_ATTEMPTS без Retry-After.
Просроченный/заменённый/использованный/неизвестный/чужой challenge — SIGN_CHALLENGE_EXPIRED.
Успех — SIGNED, затем ISSUED через 3–5 секунд и восстановление зависших операций (#7).
Стабы не хранят OTP, не ограничивают частоту и не защищают от перебора.

POST ai-report: существующий READY/FALLBACK без regenerate — 200; свежий PENDING — 200
даже с regenerate=true; зависший PENDING — 202; остальные regenerate — 202.
Новая генерация возвращает типизированный PENDING. Порог зависания — deadline+15 секунд;
202 запускает polling GET (3 секунды). Свежий PENDING из 200 тоже нужно опрашивать.
READY/FALLBACK останавливают polling AI. Фоновая реализация и generation_id — #8.
Feedback — UPSERT; comment ≤1000; не влияет на решение и revision.

PROVIDER_UNAVAILABLE только у company-binding/Submit. Реальные вызовы ext-sim в #6 есть в health
и отдельно проверенном адаптере; вызовы бизнес-операций появятся в #5/#7.
Interpret при отказе LLM — 200 RULES/UNAVAILABLE; AI — FALLBACK, не HTTP 503.
Общие 400/405/500 и 503 SERVICE_UNAVAILABLE — отдельная инфраструктурная политика.

GET /api/v1/health использует HealthResponse: БД недоступна → 503; только ext-sim/LLM
недоступны → 200 degraded. ErrorEnvelope не подменяет health 503.
