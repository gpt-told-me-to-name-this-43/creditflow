import type { QueryClient } from '@tanstack/react-query'
import { createRouter, type RouterHistory } from '@tanstack/react-router'
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
  })
}

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof createAppRouter>
  }
}
