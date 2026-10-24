import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { db, submitApplication } from '@/mocks/db.ts'
import { renderApp } from '@/test/render.tsx'
import { signInWithCompany } from '@/test/session.ts'

describe('Мои заявки', () => {
  it('пусто — предложение подать заявку', async () => {
    await signInWithCompany('director.bakery', '0099020010')
    renderApp('/client')
    expect(await screen.findByText('Заявок пока нет')).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Подать заявку' })[0]).toHaveAttribute(
      'href',
      '/client/applications/new',
    )
  })

  it('статус, что дальше и действие по каждой заявке', async () => {
    const user = await signInWithCompany('director.bakery', '0099020010')
    const sent = Object.assign(db.createApplication(user), {
      purpose_code: 'EQUIPMENT',
      requested_amount_rub: '3000000.00',
      term_months: 36,
      product_id: 'investment',
    } as const)
    submitApplication(sent)
    const draft = db.createApplication(user)

    renderApp('/client')
    const items = within(await screen.findByRole('list', { name: 'Заявки' })).getAllByRole(
      'listitem',
    )
    expect(items).toHaveLength(2)

    const [first, second] = items as [HTMLElement, HTMLElement]
    expect(first).toHaveTextContent('Цель пока не указана')
    expect(first).toHaveTextContent('Черновик')
    expect(within(first).getByRole('link', { name: 'Продолжить' })).toHaveAttribute(
      'href',
      `/client/applications/new?applicationId=${draft.id}`,
    )

    expect(second).toHaveTextContent('Оборудование')
    expect(second).toHaveTextContent('3 000 000 ₽ на 36 мес.')
    expect(second).toHaveTextContent('На рассмотрении')
    expect(second).toHaveTextContent('обновлять её не нужно')
    expect(within(second).getByRole('link', { name: 'Подробнее' })).toHaveAttribute(
      'href',
      `/client/applications/${sent.id}`,
    )
  })
})
