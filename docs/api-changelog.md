# История изменений API v1

Источник истины контракта — `docs/openapi.json`. Он экспортируется командой `make openapi`
(`scripts/export_openapi.py`) и вручную не редактируется. Коды ошибок описаны в
`docs/api.md`, демо-данные и эталоны — в `docs/demo-data.md`.

## Правила изменения контракта

После тега `contract-v1` фронт генерирует клиент из `docs/openapi.json` и работает на
моках. Поэтому любое изменение контракта:

1. делается отдельным PR с label **`contract-change`**;
2. добавляет запись в этот файл (раздел «Не выпущено»): что изменилось, почему,
   совместимо ли изменение и что делать фронту;
3. содержит перегенерированный `docs/openapi.json`. CI проверяет, что экспорт совпадает
   с закоммиченным (`git diff --exit-code docs/`);
4. для несовместимого изменения требует ревью владельца фронтенда и обновления
   моков в том же PR.

**Несовместимые** изменения (только через `contract-change` и согласование):

- удаление или переименование пути, метода, поля, значения enum или кода ошибки;
- смена типа поля, формата (`Money` — строка `^-?\d+\.\d{2}$`) или nullable → not null
  в ответе;
- новое обязательное поле или ужесточение ограничения во входе (`maxLength`, `gt`,
  `pattern`);
- смена HTTP-статуса или `code` для существующей ситуации;
- новые требования к заголовкам (`Authorization`, `Idempotency-Key`) у существующего
  маршрута;
- появление в клиентских схемах полей, которые клиент видеть не должен (score, DSCR,
  лимит, коды, рекомендация, AI, комментарий менеджера). Это запрещено всегда.

**Совместимые** изменения (запись в changelog и label `contract-change` также
обязательны):

- новый путь или метод;
- новое необязательное поле во входе или новое поле в ответе;
- новое значение enum в ответе — только если фронт обрабатывает неизвестные значения;
- новые примеры и описания.

Реализация стабов в #5/#7/#8 контракт не меняет. Если она требует изменения, оно
проходит по правилам выше.

## Не выпущено — финализация Design 2.5 (2026-10-23)

Design 2.3–2.5 принят как целевая спецификация; тег contract-v1 ещё не создан.
Lead фиксирует уточнение acceptance criteria в Issue #6 перед merge. Политика ошибок
окончательная: только применимые статусы, общие инфраструктурные ошибки отдельно,
health с собственным HealthResponse. Готовая запись: [issue-6-acceptance.md](issue-6-acceptance.md).

### Изменения относительно прежнего локального контракта

Это согласованная финализация до первого тега, включая несовместимые изменения.
Frontend должен перегенерировать типы и обновить MSW, прежде чем считать freeze принятым.

- Новые ErrorCode: COMPANY_NOT_BOUND (409), APPLICATION_INCOMPLETE,
  PRODUCT_NOT_ELIGIBLE, SIGN_CHALLENGE_EXPIRED (422).
- **Breaking:** error.details теперь объект типизированных полей, а не массив
  loc/msg/type. VALIDATION_ERROR.details.fields использует field/code/message;
  REVISION_CONFLICT — current_revision; ошибки Submit — missing_fields либо
  product_id/unmet_constraints; SIGN_CODE_INVALID — remaining_attempts.
  Старое error.attempts_remaining удалено. TOO_MANY_ATTEMPTS имеет scope и опциональный retry_after_seconds.
- Канонический ProductConstraint общий для каталога и PRODUCT_NOT_ELIGIBLE;
  unmet_constraints — массив строк enum, не объектов.
- ManagerApplicationView.offer_constraints — **обязательное nullable поле** строгого
  OfferConstraints (min/max_amount_rub, min/max_term_months), не null только при COUNTER_OFFER.
  Денежный pattern в нём положительный без знака, с двумя десятичными знаками.
- GET /company и все /applications* имеют 409 COMPANY_NOT_BOUND. Catalog и manager
  не зависят от привязки текущего пользователя. У GET нет REVISION_CONFLICT.
- POST /applications декларирует 201 создания и 200 существующего DRAFT без изменения тела;
  конкурентное хранение и частичный индекс остаются #7, стаб всегда показывает создание.
- POST manager ai-report декларирует 200 существующего READY/FALLBACK/свежего PENDING
  и 202 новой генерации. Свежий PENDING возвращается 200 даже с regenerate.
- Preview снова декларирует 409 INVALID_STATUS_TRANSITION вне UNDER_REVIEW;
  бизнес-нарушения по-прежнему 200 valid=false.
- Sign/challenge декларирует 429 CHALLENGE_ISSUE и Retry-After (5 challenge за 15 минут).
  Sign: первые две ошибки 422 SIGN_CODE_INVALID, третья 429 SIGN_ATTEMPTS без Retry-After;
  неизвестный/чужой/просроченный/заменённый/использованный challenge — SIGN_CHALLENGE_EXPIRED.
  demo_code теперь опционален и отсутствует в JSON вне демо-режима (вместо null).
- **Breaking:** purpose_text во входных create/PATCH/interpret сокращён с 2000 до 1000 символов.
  Непосредственная запись terms_source клиентом запрещена, вычисляет backend.
- Основной C2 сохраняет исходный запрос 3 000 000 / 36 при accept; оффер и договор
  2 340 000 / 36. Исправлен прежний пример, переписывавший requested_amount_rub.
  3 000 000 / 54 — отдельный M11. Формулы ядра и инвестиционные эталоны не изменялись.
- **Изменение данных каталога:** Design 2.5 уже задавал working_capital 25%, но seed и
  эталоны ещё использовали 24%. В products-v2 исправлены seed, каталог OpenAPI и тестовые
  входы. Независимая формула с Decimal prec=50 подтвердила: C3 платёж 76035.36,
  DSCR 3.94, лимит 2520000; C5 платёж 95044.20; C6 платёж 100787.72.
  Ветки/score/стоп-факторы не меняются. Миграция 0002 обновляет только working_capital
  с прежней ставкой 24 до 25; исторические scoring snapshots не изменяет.
  Downgrade возвращает 24. MSW C3/C5/C6 нужно обновить. Формулы/пороги/ENGINE_VERSION прежние.
- Поля handoff: QueueItem.company_inn/product_id; карточка legal_form/okved_main/registered_at;
  scoring.account_history_months; manager_full_name/actor_full_name в истории;
  ContractView.key_terms_markdown; ManagerStats.ai_feedback_groups с total/up_count/up_share.
  Все новые поля ответов обязательны (некоторые nullable): типизированные фикстуры нужно дополнить.
  Старое ai_feedback_up_share сохранено. Группы — данные API, frontend не высчитывает решения.
- Сохранены локальные расширения #9: ClientAction/allowed_actions, финансовые строки
  клиентской карточки, revision/attempts_remaining в SignChallenge, пароль DemoAccount.
  demo-accounts теперь показывает все 10 seed-учёток, тексты согласий не содержат заглушку «…».
- Независимая матрица api/contract/http_matrix.yaml — единственный ручной эталон;
  test_http_policy.py сверяет OpenAPI, docs/api-matrix.md генерируется и проверяется CI.
- Добавлены TypeScript generation, openapi-fetch client, MSW 2 smoke и compile-time
  проверки статусов/DTO. Инструкция: [frontend-handoff.md](frontend-handoff.md).

Пути, методы, operationId, enum состояний/действий, revision и Idempotency-Key сохранены.
Клиентские DTO не содержат scoring/DSCR/лимит/менеджерские комментарии.
Стабы не реализуют auth, OTP, rate limit, FSM, AI или БД; production содержит только health.

## Выпуск contract-v1

1. Lead фиксирует принятое уточнение Issue #6.
2. Публикуется проверенная ветка обычным push, без переписывания истории.
3. CI проходит на новом HEAD, frontend подтверждает generation/typecheck и MSW.
4. Review/approve PR #12 → merge master → CI master.
5. Аннотированный contract-v1 создаётся на проверенном merge-коммите.
6. Frontend получает тег и frontend-handoff.md.

До выполнения этих шагов тег и официальный release не объявляются выпущенными.
Если master менялся параллельно, сверяются согласованные API-артефакты, а не пустота
полного diff feature и merge-коммита. Новая процедура breaking-api не вводится:
действует существующий contract-change и frontend review для несовместимых изменений.
