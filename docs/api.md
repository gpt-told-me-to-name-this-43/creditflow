# API Error Codes

| code | HTTP | Когда | Текст для пользователя |
|---|---|---|---|
| UNAUTHORIZED | 401 | Нет/invalid токен | Требуется авторизация |
| FORBIDDEN | 403 | Недостаточно прав | Действие запрещено |
| NOT_FOUND | 404 | Объект не найден или чужой | Объект не найден |
| REVISION_CONFLICT | 409 | concurrency | Заявка изменена, обновите страницу |
| INVALID_STATUS_TRANSITION | 409 | FSM | Переход в этот статус невозможен |
| ACTION_NOT_ALLOWED | 422 | DecisionPolicy | Действие не разрешено для этой заявки |
| CONSENT_REQUIRED | 422 | Нет согласия БКИ/ПД | Требуется согласие |
| VALIDATION_ERROR | 422 | Pydantic | Ошибка валидации |
| PROVIDER_UNAVAILABLE | 503 | ext-sim timeout | Внешний сервис недоступен, повторите позже |