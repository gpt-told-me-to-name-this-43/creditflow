import type { QueryClient } from '@tanstack/react-query'
import { createRouter, type RouterHistory } from '@tanstack/react-router'
import { PageError, PagePending } from '@/components/route-states.tsx'
import { auth } from '@/lib/auth.ts'
import { routeTree } from './routeTree.gen.ts'

export function createAppRouter(queryClient: QueryClient, history?: RouterHistory) {
  return createRouter({
    routeTree,
    context: { queryClient, auth },
    history,
    defaultPreload: 'intent',
    // Свежесть данных решает TanStack Query, роутер не кэширует loader сам.
    defaultPreloadStaleTime: 0,
    scrollRestoration: true,
    // Скелетон, ошибка с действием и 404 — у каждого экрана внутри общего каркаса.
    defaultPendingComponent: PagePending,
    defaultErrorComponent: PageError,
  })
}

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof createAppRouter>
  }
}
