import type { ErrorCode } from '@/api/contract-draft.ts'

// Тексты для пользователя по `code` из docs/api.md. Тексты привязки — из #9.
// Экран может уточнить текст под контекст (например, 503 на отправке заявки).
export const errorMessages = {
  UNAUTHORIZED: 'Сессия завершилась. Войдите заново',
  INVALID_CREDENTIALS: 'Неверный логин или пароль',
  FORBIDDEN: 'Этот раздел вам недоступен',
  APPLICANT_NOT_AUTHORIZED:
    'Подать заявку может только руководитель компании или сам ИП. Если вы бухгалтер или сотрудник — попросите руководителя войти в кабинет',
  NOT_FOUND: 'Не нашли такую страницу или заявку',
  REVISION_CONFLICT:
    'Заявка изменилась, пока вы её заполняли. Мы обновили данные — проверьте и повторите',
  INVALID_STATUS_TRANSITION: 'Это действие сейчас недоступно: статус заявки уже изменился',
  IDEMPOTENCY_IN_PROGRESS: 'Запрос уже обрабатывается, подождите несколько секунд',
  COMPANY_ALREADY_BOUND: 'Эта компания уже подключена другим пользователем',
  USER_ALREADY_BOUND: 'К вашему кабинету уже подключена компания',
  VALIDATION_ERROR: 'Проверьте введённые данные',
  INVALID_INN: 'Проверьте ИНН: 10 цифр для организации или 12 для ИП',
  COMPANY_NOT_IN_REGISTRY: 'Компания с таким ИНН не найдена в ЕГРЮЛ/ЕГРИП',
  CONSENT_REQUIRED: 'Чтобы продолжить, подтвердите согласие',
  ACTION_NOT_ALLOWED: 'Это действие недоступно для заявки',
  AMOUNT_ABOVE_LIMIT: 'Сумма больше доступной на этот срок',
  SIGN_CODE_INVALID: 'Неверный код подтверждения',
  IDEMPOTENCY_KEY_REUSED: 'Не удалось выполнить действие. Повторите ещё раз',
  TOO_MANY_ATTEMPTS: 'Слишком много попыток. Попробуйте немного позже',
  PROVIDER_UNAVAILABLE: 'Сервис временно недоступен. Повторите через минуту',
} as const satisfies Record<ErrorCode, string>

export const networkErrorMessage = 'Нет связи с сервером. Проверьте интернет и повторите'
export const unknownErrorMessage = 'Что-то пошло не так. Повторите ещё раз'

// Тексты экранов ошибок (errorComponent, notFoundComponent).
export const pageErrors = {
  unexpected: {
    title: 'Что-то пошло не так',
    description: 'Попробуйте ещё раз. Если ошибка повторится, зайдите немного позже.',
    action: 'Повторить',
  },
  notFound: {
    title: 'Страница не найдена',
    description: 'Возможно, ссылка устарела или в ней опечатка.',
    action: 'На главную',
  },
} as const
