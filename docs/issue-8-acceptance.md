# Issue #8: финальная инженерная проверка

Дата: 2026-10-26. Ветка: `feat/8-ai-assist`, база `origin/master` = `9e894ee`.
Реализация продолжена с незакоммиченного состояния предыдущей сессии; платные eval
повторно не запускались. Полные результаты исходных измерений — [ai-eval](ai-eval.md).

| Критерий | Статус | Подтверждение |
|---|---|---|
| OpenAI-compatible SDK, replay, disabled | PASS | `app/llm/client.py`, `tests/llm/test_client.py` |
| json_schema/json_object/prompt, reasoning | PASS | Mocked HTTP во всех форматах, финальный контент после reasoning |
| Retry 429/5xx/timeout, Retry-After, concurrency, breaker | PASS | `tests/llm/test_client.py`, SLO-тест interpret |
| URL/config, X-Request-ID, логи и health без вызова LLM | PASS | Client/health tests; HTTP Docker health |
| CLI check и диагностика ошибок | PASS | `tests/llm/test_cli.py`: 200/401/404/503, выбранный формат, закрытие клиента; make replay/disabled |
| Промпты, untrusted user block, версии/hash | PASS | `tests/llm/test_prompts_pii.py`, каталоги prompts и replay |
| Схема, reason codes, плейсхолдеры, числа, стоп-фразы, длины | PASS | `tests/llm/test_explain.py`, `test_ai_reports.py` |
| Fallback проходит те же валидаторы | PASS | Перебор шаблонов; disabled/unavailable/invalid/timeout |
| Submit → PENDING → READY/FALLBACK, после COMMIT | PASS | Интеграционные tests с PostgreSQL; Docker demo |
| Regenerate и параллельные POST | PASS | Блокировка строки; один запуск при пяти параллельных POST |
| generation_id, stale results, recovery, cancellation, deadline | PASS | `tests/applications/test_ai_reports.py`, startup recovery |
| API/RBAC, отсутствие записи при interpret | PASS | Access matrix, HTTP policy, `test_interpret_api.py` |
| Не меняются FSM, allowed_actions, решение и расчёт | PASS | Injection-набор, числа побайтно из блока расчёта |
| Минимизация данных | PASS | Перехват HTTP; известные ФИО/компании и 10+ цифр, Unicode/разделители, числовые hints; границы ниже |
| C1–C7 READY в replay без провайдера | PASS | `test_ai_replay.py`; 12 READY в полном Docker demo |
| 10 injection-кейсов | PASS | По 20 интеграционных проверок в replay и disabled; live не повторялся |
| Rules/merge и 40 фраз с происхождением | PASS | `tests/llm`, `tests/eval/intent.jsonl`, source/author |
| Правила: сумма и срок ≥85% | PASS | Офлайн eval: по 92%, все чистые фразы распознаны |
| Eval трёх моделей ≤120B и выбор | PASS | Сохранённые первичные markdown-отчёты в `docs/evals`, ADR |
| Feedback upsert и агрегация | PASS | Повтор заменяет оценку; регенерация очищает старые оценки под блокировкой |
| Make check/record/eval-intent/eval-injection | PASS | Офлайн запуск; record требует opt-in/БД, не перезаписывает fixtures |
| Docker prompts/replay/environment/non-root | PASS | UID 10001, 4 prompt-файла, 46 replay; `.env` отсутствует в образе |
| CI без платного LLM | PASS | LLM_MODE=replay, LLM_RECORD/LIVE=0, rules-only eval с порогом; существующие jobs сохранены |
| Контракт v1 и frontend | PASS | Схемы и структура API не менялись; OpenAPI экспорт и TS generation; frontend проверки |
| README, ADR, происхождение и лицензии | PASS | README, ai-eval, ADR 0001, THIRD_PARTY_NOTICES.md со ссылками HF |
| Минимум два реальных провайдера: cloud + local | UNVERIFIED | OpenRouter ранее проверен; работающего локального runtime/весов нет |

## Верификация

Последний полный backend-прогон: **1763 passed, 0 failed, 0 skipped**, 2 предупреждения
библиотек, 138.96 с. Ruff/format/mypy успешны (163 source files). Последняя проверка с
coverage до дополнительной регрессии privacy: 1762 passed, 219.43 с; финансовое ядро
после неё не менялось. Тестовые данные очищались только в отдельном контейнере
`cf8-testdb` на `127.0.0.1:55432` (cf8test; отдельная cf8finalcli для make-сценариев).
Docker smoke запускался отдельными compose-проектами с собственными томами PostgreSQL.

- Backend: Ruff, format, mypy по app/tests/alembic/contract/scripts; весь pytest suite.
- Scoring coverage: 99.18% строк / 96.53% ветвей (пороги 95% / 90%).
- Frontend: lint, typecheck, 520 тестов в 27 файлах, production build и проверка отсутствия MSW.
- ext-sim: Ruff, format, mypy, 60 passed.
- Make: check replay/disabled, intent replay/rules-only/disabled; injection replay/disabled
  по 20 passed; запись существующего набора с недоступным endpoint — 28 passed,
  новых intent fixtures 0. Это проверка защиты записи без платных вызовов.
- Docker: сборка всех трёх образов и healthy стек; HTTP web/docs/reset/login/manager queue;
  все 12 отчётов READY в replay, FALLBACK/DISABLED в disabled,
  FALLBACK/UNAVAILABLE при недоступном endpoint; health.status=ok во всех трёх режимах.
- OpenAPI: unit проверяет детерминизм и актуальность; отдельное структурное сравнение
  с origin/master подтверждает неизменные schemas/paths/параметры/статусы.
  Генераторы er/api-matrix/state-machine/demo-accounts/Bruno/demo-data воспроизводимы.

## Исправлено в финальном проходе

1. Make-заглушки заменены существующим CLI; replay/disabled не требуют внешней модели.
2. RecordingClient дополняет набор без перезаписи, включая конкурентное создание файла.
3. CLI корректно возвращает ошибку при нерабочем выбранном формате, ошибке провайдера,
   падении rules threshold; не печатает тела ошибок. Клиент закрывается в finally.
4. Нулевые значения (temperature/seed) сохраняются при запуске сценариев CLI.
5. Зависимость httpx[socks] и lockfile: SOCKS_PROXY окружения больше не ломает startup.
6. Unicode-цифры, zero-width/bidi, смешение алфавитов в стоп-фразах, одиночный Markdown
   и ответы на других письменностях проходят проверку или дают fallback.
7. Repair не повторяет произвольные коды, placeholders и имена лишних JSON-полей модели.
8. PII-маскирование учитывает Unicode, пробелы/переносы, известные имена, ИП и компании
   в кавычках. Числовая подсказка правил не возвращает скрытый длинный идентификатор.
9. Невалидная вложенная цель LLM обнуляет только это поле; остальные поля сохраняются.
10. Оценки заменённого текста очищаются при regenerate; feedback использует ту же
    блокировку, исключая неверную атрибуцию старого UP новой модели.
11. Docker включает prompts и replay; CI выполняет rules threshold и replay без ключа.
12. README/API/health/changelog, реальные eval-результаты, лицензии и ADR обновлены.

## Ограничения и внешние проверки

Локальный provider integration не выполнен: нет Ollama/vLLM и локальных весов. Mocked
HTTP не считается полноценным тестом локального runtime. Live диагностика неверного
ключа/имени модели в этом проходе не повторялась; проверены HTTP-ошибки через respx и
реальный недоступный endpoint в Docker. Исторический live injection имел ошибку теста
языка (JSON-ключи считались прозой); корректный текущий тест пройден на replay.

Маскирование покрывает известные данные заявки и описанные формы идентификаторов,
а не произвольную NER всех третьих лиц. Демо использует синтетические данные.
Семафор/breaker относятся к процессу, а восстановление PENDING опирается на БД.
При регенерации не хранится история оценок отдельных генераций — текущая схема #6
хранит одну строку отчёта, поэтому старые оценки удаляются до запуска нового текста.
Новых миграций и изменения финансового ядра #6/#7 не потребовалось.
