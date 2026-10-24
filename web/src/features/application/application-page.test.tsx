import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { applyDecision, NEED_INFO_QUESTION } from '@/mocks/db.ts'
import { renderApp } from '@/test/render.tsx'
import { submittedApplication } from '@/test/session.ts'

async function openApplication(id: string) {
  const user = userEvent.setup()
  const app = renderApp(`/client/applications/${id}`)
  await screen.findByRole('heading', { name: 'Оборудование', level: 1 })
  return { user, ...app }
}

describe('страница заявки', () => {
  it('на рассмотрении: статус, что дальше, что проверяем и история', async () => {
    const application = await submittedApplication()
    await openApplication(application.id)
    expect(screen.getByText('На рассмотрении')).toBeInTheDocument()
    expect(screen.getByText(/обновлять её не нужно/)).toBeInTheDocument()
    expect(screen.getByText('Что мы проверяем')).toBeInTheDocument()
    const history = screen.getByRole('region', { name: 'История заявки' })
    expect(
      within(history)
        .getAllByRole('listitem')
        .map((item) => item.textContent),
    ).toEqual([
      expect.stringContaining('Заявка отправлена на рассмотрение'),
      expect.stringContaining('Заявка создана'),
    ])
  })

  it('решение менеджера приходит опросом — тост и новый блок', async () => {
    const application = await submittedApplication()
    const { queryClient } = await openApplication(application.id)
    applyDecision(application, { action: 'REJECT', client_reason_code: 'HIGH_DEBT_LOAD' })
    await queryClient.refetchQueries({ queryKey: ['applications', application.id] })
    expect(await screen.findByText('Статус заявки: Отказ')).toBeInTheDocument()
    expect(screen.getByText('Почему банк отказал')).toBeInTheDocument()
  })

  it('дозапрос: вопрос, ответ со счётчиком, снова на рассмотрении', async () => {
    const application = await submittedApplication({
      action: 'REQUEST_INFO',
      question_text: NEED_INFO_QUESTION,
    })
    const { user } = await openApplication(application.id)
    expect(screen.getByText(NEED_INFO_QUESTION)).toBeInTheDocument()

    const answer = screen.getByLabelText('Ваш ответ')
    await user.click(screen.getByRole('button', { name: 'Отправить ответ' }))
    expect(answer).toHaveAccessibleDescription(/Напишите ответ/)

    await user.type(answer, 'Счёт приложу на почту')
    expect(screen.getByText('21 / 2000')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Отправить ответ' }))

    expect(await screen.findByText('Ваш ответ менеджеру')).toBeInTheDocument()
    expect(screen.getByText('Счёт приложу на почту')).toBeInTheDocument()
    expect(application.status).toBe('UNDER_REVIEW')
  })

  it('встречное предложение: отличия подсвечены, итог в одну фразу', async () => {
    const application = await submittedApplication({
      action: 'COUNTER_OFFER',
      amount_rub: '2000000.00',
      term_months: 54,
    })
    await openApplication(application.id)
    expect(screen.getByText('Банк предлагает другие условия')).toBeInTheDocument()

    const rows = screen.getAllByRole('row').filter((row) => row.dataset.changed !== undefined)
    const changed = rows.filter((row) => row.dataset.changed === 'true')
    expect(changed.map((row) => within(row).getByRole('rowheader').textContent)).toEqual([
      'Срок',
      'Платёж в месяц',
      'Переплата за весь срок',
    ])
    expect(screen.getByText(/^Платёж меньше на .+, переплата больше на .+ ₽$/)).toBeInTheDocument()
  })

  it('принять предложение — через диалог, дальше договор', async () => {
    const application = await submittedApplication({
      action: 'COUNTER_OFFER',
      amount_rub: '1560000.00',
      term_months: 36,
    })
    const { user } = await openApplication(application.id)
    await user.click(screen.getByRole('button', { name: 'Принять предложение' }))
    const dialog = await screen.findByRole('dialog', { name: 'Принять предложение банка?' })
    await user.click(within(dialog).getByRole('button', { name: 'Да, принять' }))

    expect(await screen.findByRole('heading', { name: 'Кредит одобрен' })).toBeInTheDocument()
    expect(await screen.findByText(/Договор №/)).toBeInTheDocument()
    expect(application.status).toBe('APPROVED')
  })

  it('отказаться от предложения — «Вы отказались» и новая заявка', async () => {
    const application = await submittedApplication({
      action: 'COUNTER_OFFER',
      amount_rub: '1560000.00',
      term_months: 36,
    })
    const { user } = await openApplication(application.id)
    await user.click(screen.getByRole('button', { name: 'Отказаться' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Да, отказаться' }))

    expect(
      await screen.findByRole('heading', { name: 'Вы отказались от предложения банка' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Подать новую заявку' })).toBeInTheDocument()
  })

  it('отказ: причина простыми словами и что делать', async () => {
    const application = await submittedApplication({
      action: 'REJECT',
      client_reason_code: 'INSUFFICIENT_DATA',
    })
    await openApplication(application.id)
    expect(screen.getByText('По счёту пока мало операций, чтобы оценить бизнес')).toBeVisible()
    expect(screen.getByText(/накопится хотя бы полгода/)).toBeVisible()
  })

  it('черновик открывается в мастере', async () => {
    const application = await submittedApplication()
    application.status = 'DRAFT'
    const { router } = renderApp(`/client/applications/${application.id}`)
    await screen.findByRole('heading', { name: 'Новая заявка' })
    await waitFor(() => expect(router.state.location.pathname).toBe('/client/applications/new'))
  })
})
