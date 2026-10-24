import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { setScenario } from '@/mocks/scenarios.ts'
import { renderApp } from '@/test/render.tsx'
import { signInAs } from '@/test/session.ts'

async function openOnboarding(login: string) {
  await signInAs(login)
  const user = userEvent.setup()
  const result = renderApp('/client/onboarding')
  await screen.findByRole('heading', { name: 'Подключите компанию' })
  return { user, ...result }
}

async function bind(user: ReturnType<typeof userEvent.setup>, inn: string) {
  await user.type(screen.getByLabelText('ИНН компании или ИП'), inn)
  await user.click(screen.getByRole('checkbox'))
  await user.click(screen.getByRole('button', { name: 'Найти компанию' }))
}

describe('привязка компании', () => {
  it('без согласия кнопка неактивна, согласие по умолчанию не отмечено', async () => {
    const { user } = await openOnboarding('director.bakery')
    expect(screen.getByRole('checkbox')).not.toBeChecked()
    expect(screen.getByText(/обработку персональных данных/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Найти компанию' })).toBeDisabled()
    await user.click(screen.getByRole('checkbox'))
    expect(screen.getByRole('button', { name: 'Найти компанию' })).toBeEnabled()
  })

  it('в поле ИНН остаются только цифры', async () => {
    const { user } = await openOnboarding('director.bakery')
    const input = screen.getByLabelText('ИНН компании или ИП')
    await user.type(input, '0099 020-010')
    expect(input).toHaveValue('0099020010')
  })

  it('ИНН с неверной контрольной цифрой — ошибка после blur', async () => {
    const { user } = await openOnboarding('director.bakery')
    const input = screen.getByLabelText('ИНН компании или ИП')
    await user.type(input, '0099020011')
    await user.tab()
    expect(input).toHaveAccessibleDescription(/Проверьте ИНН/)
  })

  it('руководитель находит компанию и переходит к заявкам', async () => {
    const { user, router } = await openOnboarding('director.bakery')
    await bind(user, '0099020010')
    expect(await screen.findByText('Мы нашли вашу компанию')).toBeInTheDocument()
    expect(screen.getByText('ООО «Пекарня Плюс»')).toBeInTheDocument()

    await user.click(screen.getByRole('link', { name: 'Перейти к заявкам' }))
    await screen.findByRole('heading', { name: 'Мои заявки' })
    expect(router.state.location.pathname).toBe('/client')
    expect(screen.getByText('Заявок пока нет')).toBeInTheDocument()
  })

  it('бухгалтер видит, почему не может подать заявку', async () => {
    const { user } = await openOnboarding('accountant.bakery')
    await bind(user, '0099020010')
    expect(await screen.findByRole('alert')).toHaveTextContent(
      /только руководитель компании или сам ИП.*попросите руководителя/,
    )
  })

  it('компании нет в реестре', async () => {
    const { user } = await openOnboarding('director.bakery')
    await bind(user, '7707083893')
    expect(await screen.findByRole('alert')).toHaveTextContent('не найдена')
  })

  it('реестр недоступен — объяснение и «Повторить»', async () => {
    setScenario('error503')
    const { user } = await openOnboarding('director.bakery')
    await bind(user, '0099020010')
    expect(await screen.findByRole('alert')).toHaveTextContent('Реестр компаний сейчас не отвечает')
    setScenario('default')
    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByText('Мы нашли вашу компанию')).toBeInTheDocument()
  })
})
