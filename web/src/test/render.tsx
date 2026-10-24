import { QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'
import { render } from '@testing-library/react'
import { signOut } from '@/lib/auth.ts'
import { createQueryClient } from '@/lib/query-client.ts'
import { createAppRouter } from '@/router.tsx'

/** Приложение целиком на адресе `path`: роутер, гарды, QueryClient как в main.tsx, API — MSW. */
export function renderApp(path: string) {
  const queryClient = createQueryClient({
    onUnauthorized: () => void signOut({ router, queryClient }),
  })
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [path] }))
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { router, queryClient }
}
