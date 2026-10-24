import { MutationCache, QueryCache, QueryClient, type QueryKey } from '@tanstack/react-query'
import { toast } from 'sonner'
import { errorMessage, isApiError, isStaleSession, isUnauthorized } from '@/api/errors.ts'

declare module '@tanstack/react-query' {
  interface Register {
    mutationMeta: {
      /** Ключи, которые инвалидируются после успеха и после 409 REVISION_CONFLICT. */
      invalidates?: readonly QueryKey[]
      /** false — экран показывает ошибку сам (например, 422 под полем). */
      errorToast?: boolean
    }
  }
}

/** Повторяем только сбои сервера, и не больше двух раз. */
export function shouldRetry(failureCount: number, error: unknown) {
  return isApiError(error) && error.status >= 500 && failureCount < 2
}

export function createQueryClient({ onUnauthorized }: { onUnauthorized: () => void }) {
  const invalidate = (keys: readonly QueryKey[] = []) =>
    Promise.all(keys.map((queryKey) => queryClient.invalidateQueries({ queryKey })))

  const queryClient: QueryClient = new QueryClient({
    queryCache: new QueryCache({
      onError(error, query) {
        // Ответ для прошлого пользователя: его кэш уже очищен, показывать нечего.
        if (isStaleSession(error)) return
        if (isUnauthorized(error)) return onUnauthorized()
        // Первая загрузка падает в errorComponent экрана; тост — когда данные уже на экране.
        if (query.state.data !== undefined) toast.error(errorMessage(error))
      },
    }),
    mutationCache: new MutationCache({
      onSuccess: (_data, _variables, _result, mutation) => invalidate(mutation.meta?.invalidates),
      onError(error, _variables, _result, mutation) {
        if (isStaleSession(error)) return
        if (isUnauthorized(error)) return onUnauthorized()
        const conflict = isApiError(error, 'REVISION_CONFLICT')
        if (conflict || mutation.meta?.errorToast !== false) toast.error(errorMessage(error))
        // Данные обновляются, а введённое в форме остаётся: форма не сбрасывается из кэша.
        if (conflict) return invalidate(mutation.meta?.invalidates)
      },
    }),
    defaultOptions: {
      queries: { retry: shouldRetry },
      mutations: { retry: false },
    },
  })
  return queryClient
}
