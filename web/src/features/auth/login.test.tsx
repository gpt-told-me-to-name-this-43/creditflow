import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { auth } from '@/lib/auth.ts'
import { renderApp } from '@/test/render.tsx'

describe('экран входа', () => {
  it('демо-учётка подставляет логин и пароль, вход ведёт на привязку компании', async () => {
    const user = userEvent.setup()
    const { router } = renderApp('/login')
    await user.click(await screen.findByRole('button', { name: /Кузнецова Анна Михайловна/ }))
    expect(screen.getByLabelText('Логин')).toHaveValue('director.bakery@creditflow.demo')
    expect(screen.getByLabelText('Пароль')).toHaveValue('creditflow-demo')

    await user.click(screen.getByRole('button', { name: 'Войти' }))
    await screen.findByRole('heading', { name: 'Подключите компанию' })
    expect(router.state.location.pathname).toBe('/client/onboarding')
    expect(auth.getSession()?.role).toBe('CLIENT')
  })

  it('сценарий учётки описан словами, без кодов', async () => {
    renderApp('/login')
    expect(await screen.findByText('Банк предложит другую сумму')).toBeInTheDocument()
    expect(screen.queryByText('C2')).not.toBeInTheDocument()
  })

  it('менеджер попадает в свой кабинет', async () => {
    const user = userEvent.setup()
    const { router } = renderApp('/login')
    await user.click(await screen.findByRole('button', { name: /Анна Менеджерова/ }))
    await user.click(screen.getByRole('button', { name: 'Войти' }))
    await screen.findByRole('heading', { name: 'Заявки' })
    expect(router.state.location.pathname).toBe('/manager')
  })

  it('неверный пароль — понятная ошибка, сессии нет', async () => {
    const user = userEvent.setup()
    renderApp('/login')
    await user.type(await screen.findByLabelText('Логин'), 'director.bakery@creditflow.demo')
    await user.type(screen.getByLabelText('Пароль'), 'wrong')
    await user.click(screen.getByRole('button', { name: 'Войти' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Неверный логин или пароль')
    expect(auth.getSession()).toBeNull()
  })

  it('пустые поля — ошибки после blur, связанные с полем', async () => {
    const user = userEvent.setup()
    renderApp('/login')
    await user.click(await screen.findByLabelText('Логин'))
    await user.tab()
    const login = screen.getByLabelText('Логин')
    await waitFor(() => expect(login).toHaveAttribute('aria-invalid', 'true'))
    expect(login).toHaveAccessibleDescription('Введите логин')
  })
})
