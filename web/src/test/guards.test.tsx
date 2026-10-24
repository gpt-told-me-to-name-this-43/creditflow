import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { auth } from '@/lib/auth.ts'
import { renderApp } from './render.tsx'
import { signInAs, signInWithCompany } from './session.ts'

const clientWithCompany = () => signInWithCompany('director.techservice', '0099010012')

describe('гарды роутов', () => {
  it('без сессии кабинет уводит на /login и запоминает, куда шли', async () => {
    const { router } = renderApp('/client')
    await screen.findByRole('heading', { name: 'Вход в кабинет' })
    expect(router.state.location.pathname).toBe('/login')
    expect(router.state.location.search).toEqual({ redirect: '/client' })
  })

  it('клиент с компанией попадает в свои заявки', async () => {
    await clientWithCompany()
    renderApp('/client')
    expect(await screen.findByRole('heading', { name: 'Мои заявки' })).toBeInTheDocument()
  })

  it('клиент без компании попадает на привязку', async () => {
    await signInAs('director.bakery')
    const { router } = renderApp('/client')
    await screen.findByRole('heading', { name: 'Подключите компанию' })
    expect(router.state.location.pathname).toBe('/client/onboarding')
  })

  it('с компанией привязка не нужна', async () => {
    await clientWithCompany()
    const { router } = renderApp('/client/onboarding')
    await screen.findByRole('heading', { name: 'Мои заявки' })
    expect(router.state.location.pathname).toBe('/client')
  })

  it('клиента не пускает в кабинет менеджера', async () => {
    await clientWithCompany()
    const { router } = renderApp('/manager')
    await screen.findByRole('heading', { name: 'Мои заявки' })
    expect(router.state.location.pathname).toBe('/client')
  })

  it('менеджера не пускает в кабинет клиента', async () => {
    await signInAs('manager.anna')
    const { router } = renderApp('/client')
    await screen.findByRole('heading', { name: 'Заявки' })
    expect(router.state.location.pathname).toBe('/manager')
  })

  it('корень ведёт в кабинет по роли', async () => {
    await signInAs('manager.anna')
    const { router } = renderApp('/')
    await screen.findByRole('heading', { name: 'Заявки' })
    expect(router.state.location.pathname).toBe('/manager')
  })

  it('с сессией /login возвращает на redirect', async () => {
    await clientWithCompany()
    const { router } = renderApp('/login?redirect=%2Fclient')
    await screen.findByRole('heading', { name: 'Мои заявки' })
    expect(router.state.location.pathname).toBe('/client')
  })

  it('внешний redirect отбрасывается', async () => {
    const { router } = renderApp('/login?redirect=%2F%2Fevil.example')
    await screen.findByRole('heading', { name: 'Вход в кабинет' })
    expect(router.state.location.search).toEqual({})
  })

  it('устаревший токен: 401 сбрасывает сессию и ведёт на вход', async () => {
    auth.setSession({ token: 'expired', role: 'CLIENT' })
    const { router } = renderApp('/client')
    await screen.findByRole('heading', { name: 'Вход в кабинет' })
    expect(router.state.location.pathname).toBe('/login')
    expect(auth.getSession()).toBeNull()
  })

  it('неизвестный адрес показывает «Страница не найдена»', async () => {
    renderApp('/nope')
    expect(await screen.findByRole('heading', { name: 'Страница не найдена' })).toBeInTheDocument()
  })
})
