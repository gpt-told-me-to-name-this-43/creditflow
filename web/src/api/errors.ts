import { errorMessages, networkErrorMessage, unknownErrorMessage } from '@/content/errors.ts'
import type { ErrorCode } from './enums.ts'

// Сеть недоступна или ответ не дошёл: HTTP-статуса нет.
export const NETWORK_ERROR = 'NETWORK_ERROR'

/** Ошибка запроса к api: конверт `{error: {code, message, details?}}` (docs/api.md). */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }

  static fromBody(status: number, body: unknown): ApiError {
    const error = (body as { error?: { code?: unknown; message?: unknown; details?: unknown } })
      ?.error
    const code = typeof error?.code === 'string' ? error.code : `HTTP_${status}`
    const message = typeof error?.message === 'string' ? error.message : `HTTP ${status}`
    return new ApiError(status, code, message, error?.details)
  }

  get isNetwork() {
    return this.code === NETWORK_ERROR
  }
}

export function isApiError(error: unknown, code?: ErrorCode): error is ApiError {
  return error instanceof ApiError && (code === undefined || error.code === code)
}

/** Сессия недействительна. 401 на входе (неверный пароль) сюда не относится. */
export function isUnauthorized(error: unknown) {
  return isApiError(error) && error.status === 401 && error.code !== 'INVALID_CREDENTIALS'
}

/** Текст для пользователя: по `code` из content/errors, а не `message` бэка. */
export function errorMessage(error: unknown): string {
  if (!isApiError(error)) return unknownErrorMessage
  if (error.isNetwork) return networkErrorMessage
  return errorMessages[error.code as ErrorCode] ?? unknownErrorMessage
}
