# Frontend handoff — API Contract v1 / Design 2.5

## A. Версия контракта

Целевая спецификация — Design 2.5. Контракт подготовлен в ветке
`feat/6_findemo_and_test_data` (PR #12). Артефакты одной версии:

- `docs/openapi.json` — HTTP-контракт и примеры DTO;
- `api/contract/http_matrix.yaml` — эталон применимых HTTP-ответов;
- `web/src/api/schema.d.ts` — сгенерированные типы;
- `web/package.json` и `web/pnpm-lock.yaml` — зависимости и команды генерации;
- этот документ — правила интеграции и сценарии проверки.

Артефакты используются из одного коммита; его SHA определяется командой
`git rev-parse HEAD`. Локальные проверки генерации, TypeScript и MSW выполнены
2026-10-23. Перед merge требуются CI на опубликованном коммите и ревью frontend/Lead.

Тег `contract-v1` ещё не создан. Его публикация предусмотрена после merge PR #12
и успешного CI master: аннотированный тег ставится на проверенный merge-коммит.
После перехода на тег генерация типов выполняется повторно. При параллельных изменениях
master сравниваются API-артефакты; полный diff feature-ветки и master может содержать
изменения, не относящиеся к контракту.

## B. Стек и установленные зависимости

Целевой стек #9/#10: React, TypeScript strict, Vite; TanStack Router/Query/Form/Table;
Tailwind и shadcn/ui; openapi-typescript, openapi-fetch, MSW 2.

В `web` установлены React, Vite, TypeScript strict, Vitest, ESLint и Prettier.
API-слой использует openapi-typescript, openapi-fetch и MSW 2; версии закреплены
в lockfile. TanStack, Tailwind и shadcn подключаются в #9/#10 при разработке экранов.
`pnpm-workspace.yaml` отключает install-script MSW: тесты Node/Vitest используют
`setupServer` и не требуют browser worker.
Для браузерных моков в #9: `pnpm exec msw init public --save`, подключение
`setupWorker` и завершение `worker.start()` до первого API-запроса.

## C. Проверенные команды

Node 22+ и pnpm версии из packageManager (11.27.0):

```bash
cd web
pnpm install --frozen-lockfile
pnpm generate:api
pnpm typecheck
pnpm test
pnpm lint
pnpm exec vite build
```

`generate:api` вызывает `openapi-typescript ../docs/openapi.json -o src/api/schema.d.ts`.
Сгенерированный файл не редактируется и не форматируется вручную. CI повторяет генерацию
и проверяет отсутствие diff. Проверки типов — `src/api/contract-smoke.ts`, MSW-тесты —
`src/api/client.test.ts`. Проверены оба ответа создания 200/201 и AI 200/202, типы details,
ProductConstraint, nullable OfferConstraints и отсутствие внутренних полей клиента.
openapi-typescript 7.13 декларирует peer dependency TypeScript ^5.x; в репозитории
установлен TypeScript 6.0.3. Генерация и строгая проверка типов этой комбинации выполнены;
предупреждение о peer dependency сохраняется.

## D. Типизированный API client

Точка входа API-слоя — `src/api/client.ts`. Пути включают `/api/v1`; `baseUrl` — origin
(`''` для браузерного same-origin). Для отдельного dev API указывается origin с портом.
В production SPA и API за nginx на одном origin. Токен — sessionStorage, не localStorage.
Middleware читает его на каждом запросе; login/consents доступны без токена.

```ts
import { createApiClient, newIdempotencyKey } from './api/client'

const api = createApiClient()
const actionKey = newIdempotencyKey() // сохранить до завершения этого действия
const result = await api.POST('/api/v1/applications/{application_id}/submit', {
  params: {
    path: { application_id: application.id },
    header: { 'Idempotency-Key': actionKey },
  },
  body: { revision: application.revision, bki_consent_version: consent.version },
})
if (result.error) {
  // result.error.error.code/message/details; HTTP — result.response.status
}
```

Ключ обязателен submit/info-response/offer accept/decline/sign/manager decisions.
Сетевой повтор использует тот же ключ и тело; изменённое действие — новый ключ.
После `REVISION_CONFLICT` карточка обновляется с сохранением ввода. Повтор операции
с новой `revision` требует явного действия пользователя.
Ответы 4xx/5xx не кешируются. Ответ feedback со статусом 204 не содержит JSON-тела.

Деньги в ответах — строки с двумя знаками; входные суммы — положительные целые рубли.
Проценты/DSCR также строки. Не рассчитывайте финансовые решения, лимит или DSCR в JS.
Даты — ISO/UTC, отображение — Europe/Moscow. `key_terms_markdown` отображается с отключённым raw HTML.

## E. Обработка ошибок

`ErrorEnvelope = {error: {code, message, details?}}`; details — объект, не массив.
Общий тип details — union именованных DTO. Доступ к полям требует проверки `error.code`
и сужения типа, например `details && 'missing_fields' in details`. Пример приведён
в `contract-smoke.ts`. Поля `loc/msg/type` и `error.attempts_remaining` в текущем контракте отсутствуют.

| Код | Действие UI |
|---|---|
| COMPANY_NOT_BOUND | Открыть привязку компании, сохранив маршрут возврата |
| APPLICATION_INCOMPLETE | details.missing_fields → поля формы |
| PRODUCT_NOT_ELIGIBLE | product_id и unmet_constraints → нарушения продукта |
| VALIDATION_ERROR | details.fields: field/code/message; префиксы body/query/path/header |
| REVISION_CONFLICT | Обновить карточку, показать current_revision, предложить повтор |
| TOO_MANY_ATTEMPTS | LOGIN/CHALLENGE_ISSUE → ждать Retry-After (целые секунды) |
| TOO_MANY_ATTEMPTS, SIGN_ATTEMPTS | Без Retry-After: challenge недействителен, предложить новый |
| SIGN_CODE_INVALID | details.remaining_attempts → оставшиеся попытки |
| SIGN_CHALLENGE_EXPIRED | Запросить новый код |
| PROVIDER_UNAVAILABLE | Временный отказ ext-sim; Submit остаётся DRAFT |
| UNAUTHORIZED | Очистить устаревший токен, перейти на вход |
| FORBIDDEN / NOT_FOUND | Экран недостаточных прав / ресурс недоступен |
| INVALID_STATUS_TRANSITION | Перечитать карточку и доступные действия |

У health 503 — HealthResponse, не ErrorEnvelope. Не-JSON ответ прокси и сетевой сбой
обрабатывайте отдельно. LLM fallback не даёт PROVIDER_UNAVAILABLE: interpret возвращает
RULES/UNAVAILABLE, manager AI — FALLBACK.

## F. MSW: минимальные сценарии

Источники фикстур: `content.examples` в OpenAPI и финансовые эталоны в `docs/demo-data.md`.
Обработчики MSW типизируются через `components`/`paths`; клиентские ответы содержат только
публичные DTO. Текущие интеграционные тесты используют MSW 2 `setupServer` и openapi-fetch
и проверяют HTTP-клиент. Состояния бизнес-процесса реализуются отдельными сценариями MSW.

| Сценарий | Минимальная последовательность/проверка |
|---|---|
| C1 | DRAFT → UNDER_REVIEW → APPROVED → SIGNED → ISSUED; 2 000 000 / 36 |
| C2 основной | Запрос 3 000 000 / 36; оффер 2 340 000 / 36 → accept → договор тех же условий; запрос сохраняется |
| M11 отдельно | Оффер 3 000 000 / 54; не подменять им основной C2 |
| C3 | NEED_INFO с вопросом → info-response → UNDER_REVIEW, без нового расчёта |
| C4–C6 | Недостаточная история/ликвидация/ФНС; manager allowed_actions=[REJECT] |
| C7 | Высокий долг, limit=null, MANUAL_REVIEW; без автоматического отказа |
| Auth | Демо-учётки, login 200 / 401 INVALID_CREDENTIALS / 429 LOGIN |
| Онбординг | COMPANY_NOT_BOUND → binding; INVALID_INN/CONSENT_REQUIRED/APPLICANT_NOT_AUTHORIZED/уникальность |
| Создание | 201 новый DRAFT; 200 существующий без изменения полей от повторного тела |
| Конкуренция | 409 REVISION_CONFLICT с current_revision; форма не теряет ввод |
| Продукт | PRODUCT_NOT_ELIGIBLE с массивом канонических enum-строк |
| Submit | APPLICATION_INCOMPLETE, CONSENT_REQUIRED, PROVIDER_UNAVAILABLE, IDEMPOTENCY_IN_PROGRESS/KEY_REUSED |
| Подписание | TTL 5 минут, 2 ошибки 422, третья 429 без Retry-After, истечение/замена 422, успех |
| Challenge rate | Шестой challenge за 15 минут → 429 CHALLENGE_ISSUE + Retry-After |
| AI | PENDING/READY/FALLBACK; POST 200 существующий / 202 генерация; regenerate свежего PENDING →200 |
| Preview | 200 valid=true / valid=false+violations / SKIPPED+null; 409 вне UNDER_REVIEW |
| Решения | APPROVE/COUNTER_OFFER/REQUEST_INFO/REJECT; required comment/allowed_actions/revision |

Менеджерские фикстуры должны всегда содержать offer_constraints: объект, когда разрешён
COUNTER_OFFER, иначе null. У объекта все четыре поля обязательны, extra запрещены.
Пределы берутся из продукта, а не из текущего лимита расчёта. Preview проверяет пару сумма/срок.
PRODUCT_NOT_ELIGIBLE.unmet_constraints — тот же ProductConstraint, что в каталоге.
Каталог products-v2: investment 24%, working_capital 25%. Используйте исправленные
значения C3/C5/C6 из demo-data.md: C3 платёж 76035.36, DSCR 3.94, лимит 2520000;
C5 платёж 95044.20, C6 платёж 100787.72. Ветки сценариев и C2 остались прежними.
Новые required поля очереди, компании, истории, сводки и договора перечислены в changelog.

## G. Polling

- Статус заявки: каждые 5 секунд.
- SIGNED: каждые 2 секунды до ISSUED; выдача целевая 3–5 секунд, recovery — backend #7.
- AI PENDING: каждые 3 секунды, в том числе при POST 200 с PENDING; READY/FALLBACK — остановить AI polling.
- ISSUED/REJECTED/DECLINED — остановить polling заявки.
- 401/404 — остановить запросы соответствующего недоступного ресурса; transient errors не выдавать за конечный статус.

TanStack Query получает эти интервалы из текущего типизированного ответа. GET не меняет состояние.

## H. Безопасность UI

Клиент использует только ClientApplicationView, ClientOffer, ContractView и публичные DTO.
Ему не показываются score, DSCR, лимит, blocking/reason codes расчёта, внутреннее предложение,
AI-заключение менеджера и комментарии менеджеров. client_reason_code — разрешённый
клиентский шаблон причины; не заменяйте его внутренними кодами скоринга.
Кнопки — по allowed_actions; границы формы менеджера — по offer_constraints;
финансовые расчёты и решения — только backend/типизированные сценарные фикстуры.

## I. Граница следующих задач

#5: JWT, роли, ownership, реальная привязка и согласия. #7: БД/FSM/Submit/решения/договор,
конкурентность, идемпотентность и выдача. #8: rules/LLM/replay, фоновые AI-отчёты/feedback.
OTP-хранение, реальный rate limit и восстановление выдачи относятся к реализации процесса.
#9/#10: экраны, маршруты, Query/Form/Table, browser MSW, сценарии и E2E.

Текущий backend в local/test возвращает фиксированные ответы. Хранение состояния,
проверка JWT, защита от перебора и переходы бизнес-процесса относятся к #5/#7/#8.
В production стабы не монтируются. До реализации этих задач frontend использует
типизированный контракт и сценарии MSW.
