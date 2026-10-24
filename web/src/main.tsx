import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { signOut } from '@/lib/auth.ts'
import { createQueryClient } from '@/lib/query-client.ts'
import { initTheme } from '@/lib/theme.ts'
import { createAppRouter } from './router.tsx'
import './index.css'

initTheme()

// 401 в любом запросе: сессию сбрасываем, гард _auth уводит на /login с возвратом.
const queryClient = createQueryClient({
  onUnauthorized: () => void signOut({ router, queryClient }),
})
const router = createAppRouter(queryClient)

const root = document.getElementById('root')
if (!root) throw new Error('#root not found')

// Моки подключаются только динамическим импортом: без VITE_API_MOCKS=1 ветка вырезается
// при сборке, и MSW не попадает в production (проверяет scripts/check-dist.mjs).
async function enableMocks() {
  if (import.meta.env.VITE_API_MOCKS !== '1') return
  const { startMocks } = await import('./mocks/browser.ts')
  await startMocks()
}

void enableMocks().then(() => {
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </StrictMode>,
  )
})
