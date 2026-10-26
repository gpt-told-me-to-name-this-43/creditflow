import { type ErrorComponentProps, Link, useRouter } from '@tanstack/react-router'
import { isApiError } from '@/api/errors.ts'
import { Button } from '@/components/ui/button.tsx'
import { EmptyState } from '@/components/ui/empty-state.tsx'
import { ErrorState } from '@/components/ui/error-state.tsx'
import { Skeleton } from '@/components/ui/skeleton.tsx'
import { pageErrors } from '@/content/errors.ts'

/** Экран грузится: заголовок и блоки-заглушки вместо пустой страницы. */
export function PagePending() {
  return (
    <div className="grid gap-6" aria-busy="true" aria-label={pageErrors.loading}>
      <Skeleton className="h-9 w-72" />
      <Skeleton className="h-28 w-full" />
      <div className="grid grid-cols-[minmax(0,1fr)_22rem] gap-6">
        <Skeleton className="h-80" />
        <Skeleton className="h-80" />
      </div>
    </div>
  )
}

/** 404 — то же, что для несуществующей страницы. */
export function PageNotFound() {
  return (
    <EmptyState
      title={pageErrors.notFound.title}
      description={pageErrors.notFound.description}
      action={
        <Button asChild variant="outline">
          <Link to="/">{pageErrors.notFound.action}</Link>
        </Button>
      }
    />
  )
}

/**
 * Ошибка загрузки экрана внутри общего каркаса: чужая или удалённая заявка — 404,
 * завершённая сессия — вход заново (401 уводит на /login и query-client), остальное — повтор.
 */
export function PageError({ error, reset }: ErrorComponentProps) {
  const router = useRouter()
  if (isApiError(error, 'NOT_FOUND')) return <PageNotFound />
  if (isApiError(error, 'UNAUTHORIZED')) {
    return (
      <EmptyState
        title={pageErrors.unauthorized.title}
        description={pageErrors.unauthorized.description}
        action={
          <Button asChild>
            <Link to="/login">{pageErrors.unauthorized.action}</Link>
          </Button>
        }
      />
    )
  }
  return (
    <ErrorState
      onRetry={() => {
        reset()
        void router.invalidate()
      }}
    />
  )
}
