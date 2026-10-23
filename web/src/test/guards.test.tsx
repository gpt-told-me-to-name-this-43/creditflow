import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { auth, type Role } from '@/lib/auth.ts'
import { createAppRouter } from '@/router.tsx'

function renderAt(path: string) {
  const queryClient = new QueryClient()
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [path] }))
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

const loginAs = (role: Role) => auth.setSession({ token: 't', role })

describe('гарды роутов', () => {
  it('без сессии кабинет уводит на /login и запоминает, куда шли', async () => {
    const router = renderAt('/client')
    await screen.findByRole('heading', { name: 'Вход в кабинет' })
    expect(router.state.location.pathname).toBe('/login')
    expect(router.state.location.search).toEqual({ redirect: '/client' })
  })

  it('клиент попадает в свой кабинет', async () => {
    loginAs('CLIENT')
    renderAt('/client')
    expect(await screen.findByRole('heading', { name: 'Мои заявки' })).toBeInTheDocument()
  })

  it('клиента не пускает в кабинет менеджера', async () => {
    loginAs('CLIENT')
    const router = renderAt('/manager')
    await screen.findByRole('heading', { name: 'Мои заявки' })
    expect(router.state.location.pathname).toBe('/client')
  })

  it('менеджера не пускает в кабинет клиента', async () => {
    loginAs('MANAGER')
    const router = renderAt('/client')
    await screen.findByRole('heading', { name: 'Заявки' })
    expect(router.state.location.pathname).toBe('/manager')
  })

  it('корень ведёт в кабинет по роли', async () => {
    loginAs('MANAGER')
    const router = renderAt('/')
    await screen.findByRole('heading', { name: 'Заявки' })
    expect(router.state.location.pathname).toBe('/manager')
  })

  it('с сессией /login возвращает на redirect', async () => {
    loginAs('CLIENT')
    const router = renderAt('/login?redirect=%2Fclient')
    await screen.findByRole('heading', { name: 'Мои заявки' })
    expect(router.state.location.pathname).toBe('/client')
  })

  it('внешний redirect отбрасывается', async () => {
    const router = renderAt('/login?redirect=%2F%2Fevil.example')
    await screen.findByRole('heading', { name: 'Вход в кабинет' })
    expect(router.state.location.search).toEqual({})
  })

  it('неизвестный адрес показывает «Страница не найдена»', async () => {
    renderAt('/nope')
    expect(await screen.findByRole('heading', { name: 'Страница не найдена' })).toBeInTheDocument()
  })
})
