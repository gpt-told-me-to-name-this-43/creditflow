import { useMutation, type UseMutationOptions } from '@tanstack/react-query'
import { useRef } from 'react'
import { isApiError } from '@/api/errors.ts'

export function newIdempotencyKey(): string {
  return crypto.randomUUID()
}

// Повтор с тем же ключом безопасен: бэк вернёт сохранённый ответ или выполнит запрос
// заново, если прошлый не дошёл (design §3.7). После 4xx действие считается новым.
function keepsKey(error: unknown) {
  return (
    isApiError(error) &&
    (error.isNetwork || error.status >= 500 || error.code === 'IDEMPOTENCY_IN_PROGRESS')
  )
}

type IdempotentMutationOptions<TData, TVariables> = Omit<
  UseMutationOptions<TData, Error, TVariables>,
  'mutationFn'
> & {
  /** `idempotencyKey` передаётся в заголовок `Idempotency-Key`. */
  mutationFn: (variables: TVariables, idempotencyKey: string) => Promise<TData>
}

/**
 * Действие пользователя (отправить, принять оффер, подписать): новый ключ на каждое
 * действие, повтор после сетевой ошибки или 5xx — с тем же ключом, пока не изменились
 * данные. Кнопку блокируем по `isPending`.
 */
export function useIdempotentMutation<TData, TVariables = void>({
  mutationFn,
  onSuccess,
  onError,
  ...options
}: IdempotentMutationOptions<TData, TVariables>) {
  const pending = useRef<{ key: string; fingerprint: string } | null>(null)

  return useMutation<TData, Error, TVariables>({
    ...options,
    mutationFn: (variables) => {
      const fingerprint = JSON.stringify(variables ?? null)
      if (pending.current?.fingerprint !== fingerprint) {
        pending.current = { key: newIdempotencyKey(), fingerprint }
      }
      return mutationFn(variables, pending.current.key)
    },
    onSuccess: (...args) => {
      pending.current = null
      return onSuccess?.(...args)
    },
    onError: (...args) => {
      if (!keepsKey(args[0])) pending.current = null
      return onError?.(...args)
    },
  })
}
