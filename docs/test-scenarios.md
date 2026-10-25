# Тестовые сценарии S1–S11 (issue #7)

Каждый сценарий проверяется трижды: автотестом (pytest, живой PostgreSQL), запросами Bruno
(`make bru`, папка указана) и руками по шагам ниже. Учётки и компании — [demo-data.md](demo-data.md),
раздел 0; пароль `creditflow-demo`.

**Подготовка к ручной проверке.** `cp .env.example .env`, в `.env`: `TEST_RESET_ENABLED=true`,
`TEST_RESET_TOKEN=<32+ символа>`. Затем `make dev`, `make demo-reset` (или `make clean-reset`
для пути с нуля). Пока вход и привязка компании — стабы (#5), токен выдаёт
`make -s dev-token EMAIL=<логин> INN=<ИНН>`; в Swagger (`/api/docs`) — кнопка Authorize.
`make dev` открывает api на `localhost:8000`, поэтому для make-целей укажите
`API_URL=http://localhost:8000/api/v1`, если web не поднят.

| # | Сценарий | Bruno | Автотесты |
|---|---|---|---|
| S1 | Одобрение → подписание → выдача (C1) | `approve-sign-issue` | `test_contracts.py::test_c1_full_path_to_issued` |
| S2 | Встречное предложение по сумме (C2) | `offer-amount` | `test_manager.py::test_counter_offer_accept_flow`, `test_contracts.py::test_m12_schedule_through_offer_contract` |
| S3 | Встречное предложение по сроку, M11 (C2) | `offer-term` | `test_manager.py::test_offer_preview_table_and_no_writes`, `::test_counter_offer_decisions_follow_same_table` |
| S4 | Клиент отклоняет оффер | `offer-decline` | `test_manager.py::test_counter_offer_by_term_and_decline` |
| S5 | Дозапрос и ответ без пересчёта (C3) | `request-info` | `test_manager.py::test_request_info_and_answer_without_rescoring` |
| S6 | Стоп-фактор: только REJECT (C4, C5, C6) | `stop-factor` | `test_manager.py::test_stop_factor_allows_only_reject`, `::test_reject_shows_client_reason`, `test_submit.py::test_company_lands_in_queue_with_expected_action` |
| S7 | Нет полномочий: роль, чужая заявка, смена руководителя | `not-authorized` | `test_auth.py`, `test_manager.py::test_client_cannot_use_manager_routes`, `test_submit.py::test_director_mismatch_is_stop_factor` |
| S8 | Сбой ext-sim (T1) и повтор | `provider-failure` | `test_submit.py::test_t1_provider_failure_keeps_draft_and_consent`, `::test_transient_failure_then_retry_with_same_key_succeeds` |
| S9 | Конфликт revision и гонки | `revision-conflict` | `test_drafts.py::test_stale_revision_is_409_with_current_revision`, `test_submit.py::test_parallel_submits_different_keys_one_effect`, `::test_revision_change_between_fetch_and_lock_is_conflict`, `test_manager.py::test_parallel_decisions_one_record` |
| S10 | Идемпотентность | `idempotency` | `test_idempotency.py`, `test_submit.py::test_parallel_submits_same_key_one_effect`, `test_manager.py::test_same_decision_key_replays` |
| S11 | AI-заключение, сводка, демо-состояние | `ai-interpret` | `test_submit.py::test_ai_report_is_finalized_after_commit`, `::test_stale_pending_report_is_recovered`, `test_stats.py`, `test_demo.py` |

Пути автотестов — от `api/tests/applications/`.

## S1. Одобрение → подписание → выдача

- **Цель:** полный путь без отклонений; договор, простая ЭП кодом из UI, смоделированная выдача.
- **Учётки:** `director.techservice@creditflow.demo` (C1), `manager.anna@creditflow.demo`.
- **Шаги:** черновик → PATCH investment 2 000 000 / 36 → submit → менеджер `APPROVE` →
  `GET /contract` → `sign/challenge` → `sign` с `demo_code` → через 3–5 с `GET /applications/{id}`.
- **Ожидаемо:** платёж 78 465,71; в очереди `ELIGIBLE_FOR_MANAGER_REVIEW`, DSCR 3.11, score 100;
  договор `CF-2026-NNNNNN` в статусе `DRAFT`; после кода — `SIGNED`, затем `ISSUED`, событие
  `SIGNED → ISSUED` без автора (SYSTEM). Неверный код — `422 SIGN_CODE_INVALID`, осталось 2 попытки;
  третий неверный — `429 TOO_MANY_ATTEMPTS`, нужен новый код. Повторное подписание — `409`.

## S2. Встречное предложение по сумме

- **Учётки:** `director.bakery@creditflow.demo` (C2), менеджер.
- **Шаги:** заявка 3 000 000 / 36 → submit → карточка → `offer-preview` 2 340 000 / 36 →
  `decisions COUNTER_OFFER amount_rub=2340000` → клиент `offer/accept` → `GET /contract`.
- **Ожидаемо:** `COUNTER_OFFER_CANDIDATE`, DSCR 1.10, лимит 2 340 000; предпросмотр: платёж
  91 804,88, DSCR 1.25, score 83, `valid=true`; клиент видит «Вы просили → Банк предлагает»;
  после принятия — `APPROVED`, исходный запрос 3 000 000 сохранён, договор и текущий расчёт —
  по офферу. График (M12): 35 платежей по 91 804,88, последний 91 804,63, проценты 964 975,43.

## S3. Встречное предложение по сроку (M11)

- **Шаги:** новая заявка C2 3 000 000 / 36 → предпросмотры по таблице → `COUNTER_OFFER term_months=54`.
- **Ожидаемо (предпросмотр = decisions):**

  | Оффер | Результат |
  |---|---|
  | 2 340 000 / 36 | проходит: 91 804,88, DSCR 1.25, score 83 |
  | 3 000 000 / 53 | не проходит: DSCR 1.24, `AMOUNT_ABOVE_LIMIT` |
  | 3 000 000 / 54 | проходит: 91 356,79, DSCR 1.25 |
  | 3 000 000 / 60 | проходит: 86 303,90, DSCR 1.28, лимит 3 190 000 |
  | 3 300 000 / 60 | `AMOUNT_ABOVE_LIMIT` (decisions — `422`) |

  `offer-preview` не добавляет строк в БД.

## S4. Клиент отклоняет оффер

- **Шаги:** C1 → `COUNTER_OFFER amount_rub=1500000` → клиент `offer/decline`.
- **Ожидаемо:** `DECLINED`, действий у клиента нет, оффер в истории со статусом `DECLINED`.

## S5. Дозапрос

- **Учётки:** `ip.sokolova@creditflow.demo` (C3) — после `make demo-reset` вопрос уже задан.
- **Шаги:** `REQUEST_INFO` → клиент видит вопрос → `info-response` (≤ 2000 символов).
- **Ожидаемо:** `NEED_INFO` → `UNDER_REVIEW`; новых `scoring_results` нет (без пересчёта);
  менеджеру снова доступны действия; текст длиннее 2000 — `422`.

## S6. Стоп-фактор

- **Учётки:** C4 (короткая история), C5 (ликвидация), C6 (блокировки ФНС).
- **Ожидаемо:** `BLOCKED_BY_RULE`, `allowed_actions = [REJECT]`, `offer_constraints = null`;
  `APPROVE` → `422 ACTION_NOT_ALLOWED`; после `REJECT` клиент видит `client_reason_code`
  (`INSUFFICIENT_DATA`, `COMPANY_STATUS`, `TAX_AUTHORITY_RESTRICTIONS`). У C4 расчёт `SKIPPED`.

## S7. Нет полномочий

- **Ожидаемо:** без токена — `401`; клиент в кабинете менеджера и менеджер в клиентских
  маршрутах — `403`; чужая заявка — `404`; клиент без компании — `409 COMPANY_NOT_BOUND`;
  руководитель сменился после привязки — при Submit стоп-фактор `APPLICANT_NOT_AUTHORIZED`.
  Отказ привязки бухгалтеру (`403 APPLICANT_NOT_AUTHORIZED`) — вместе с #5.

## S8. Сбой ext-sim

- **Шаги:** T1 (ИНН 0099990019, БКИ не отвечает) или `docker compose stop ext-sim` → submit →
  восстановить → повтор с тем же `Idempotency-Key`.
- **Ожидаемо:** `503 PROVIDER_UNAVAILABLE`, заявка в `DRAFT`, `scoring_results` и снимков нет,
  ключ идемпотентности удалён; в `consents` одна запись `BKI_REQUEST`, повтор передаёт тот же
  `consent_id`; после восстановления повтор проходит.

## S9. Конфликт revision и гонки

- **Ожидаемо:** PATCH/submit/decisions с устаревшей `revision` — `409 REVISION_CONFLICT`,
  `details.current_revision`; два параллельных submit с разными ключами — один `200`, второй
  `409`; ровно одна `scoring_results`, одна `ai_reports`, одно событие, `revision` +1; два
  менеджера одновременно — одна запись `credit_decisions`.

## S10. Идемпотентность

- **Ожидаемо:** повтор с тем же ключом — сохранённый ответ без второго эффекта; параллельно —
  `409 IDEMPOTENCY_IN_PROGRESS` или сохранённый `200`; тот же ключ с другим телом —
  `422 IDEMPOTENCY_KEY_REUSED`; ответы-ошибки не кешируются.

## S11. AI-заключение, сводка, демо-состояние

- **Ожидаемо:** после submit — запись `ai_reports`; до LLM (#8) она сразу закрывается шаблоном
  по кодам (`FALLBACK`); зависший `PENDING` закрывает восстановление (`TIMEOUT`).
  `GET /manager/stats` совпадает с независимым SQL. После `make demo-reset` очередь (C6, C7)
  и сводка непустые, два reset подряд дают одинаковое состояние, сброс укладывается в 30 с.
  Распознавание потребности (`interpret`) — стаб до #8.
