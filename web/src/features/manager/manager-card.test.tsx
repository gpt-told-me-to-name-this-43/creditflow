import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { http } from 'msw'
import { db, seedManagerQueue } from '@/mocks/db.ts'
import { apiError } from '@/mocks/handlers.ts'
import { setScenario } from '@/mocks/scenarios.ts'
import { renderApp } from '@/test/render.tsx'
import { server } from '@/test/server.ts'
import { demoUser, signInAs } from '@/test/session.ts'

/** Очередь C1–C7 и вход менеджером; заявка — по логину её владельца. */
async function managerWithQueue() {
  seedManagerQueue()
  await signInAs('manager.anna')
}

function applicationOf(login: string) {
  const owner = demoUser(login)
  const application = db.listApplications().find((item) => item.owner_user_id === owner.id)
  if (!application) throw new Error(`Нет заявки у ${login}`)
  return application
}

async function openCard(login: string, company: string) {
  const user = userEvent.setup()
  const application = applicationOf(login)
  const app = renderApp(`/manager/applications/${application.id}`)
  await screen.findByRole('heading', { name: company, level: 1 })
  return { user, application, ...app }
}

describe('кабинет менеджера', () => {
  it('очередь: все заявки на рассмотрении, старые сверху, с рекомендацией', async () => {
    await managerWithQueue()
    renderApp('/manager')
    const table = await screen.findByRole('table', { name: 'Очередь заявок' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(7)
    expect(rows[0]).toHaveTextContent('ООО «ТехСервис»')
    expect(rows[0]).toHaveTextContent('Можно одобрять')
    expect(rows[1]).toHaveTextContent('Встречное предложение')
  })

  it('карточка: проверки, выписка, расчёт, правила и AI-заключение', async () => {
    await managerWithQueue()
    await openCard('director.techservice', 'ООО «ТехСервис»')
    const checks = screen.getByRole('region', { name: 'Внешние проверки' })
    expect(checks).toHaveTextContent('ЕГРЮЛ')
    // Поля снимков подписаны по-русски, обязательства БКИ — текстом, без сырых ключей.
    expect(checks).toHaveTextContent('Счёт40702')
    expect(checks).toHaveTextContent('АО «Демо-Банк»: остаток')
    expect(checks).not.toHaveTextContent('account_masked')
    expect(checks).not.toHaveTextContent('[object Object]')
    expect(screen.getByRole('region', { name: 'Выписка за 12 месяцев' })).toBeInTheDocument()
    const calculation = screen.getByRole('region', { name: 'Расчёт' })
    expect(within(calculation).getByText('Не ниже порога')).toBeInTheDocument()
    expect(
      screen.getByRole('region', { name: 'Как система пришла к рекомендации' }),
    ).toHaveTextContent('первое сработавшее')
    const ai = screen.getByRole('region', { name: 'AI-заключение' })
    expect(ai).toHaveTextContent('ООО «ТехСервис» просит 2 000 000 ₽ на 36 мес.')
    expect(ai).toHaveTextContent('Заключение ИИ-помощника. Не является решением')
    expect(ai).toHaveTextContent('Модель:')
    expect(ai).not.toHaveTextContent('Шаблон')
  })

  it('AI-заключение: шаблон показывает причину', async () => {
    await managerWithQueue()
    setScenario('unavailable')
    await openCard('director.techservice', 'ООО «ТехСервис»')
    const ai = screen.getByRole('region', { name: 'AI-заключение' })
    expect(ai).toHaveTextContent('Шаблон')
    expect(ai).toHaveTextContent('Модель недоступна — показан шаблон по расчёту')
  })

  it('AI-заключение: обновление только после подтверждения', async () => {
    await managerWithQueue()
    const { user } = await openCard('director.techservice', 'ООО «ТехСервис»')
    const ai = screen.getByRole('region', { name: 'AI-заключение' })
    await user.click(within(ai).getByRole('button', { name: 'Обновить заключение' }))
    const dialog = await screen.findByRole('dialog', { name: 'Обновить AI-заключение?' })
    await user.click(within(dialog).getByRole('button', { name: 'Отмена' }))
    expect(ai).toHaveTextContent('ООО «ТехСервис» просит')

    await user.click(within(ai).getByRole('button', { name: 'Обновить заключение' }))
    const again = await screen.findByRole('dialog', { name: 'Обновить AI-заключение?' })
    await user.click(within(again).getByRole('button', { name: 'Обновить' }))
    expect(await within(ai).findByText('Готовим заключение…')).toBeInTheDocument()
  })

  it('AI-заключение: оценка видна сразу и откатывается при ошибке', async () => {
    await managerWithQueue()
    const { user } = await openCard('director.techservice', 'ООО «ТехСервис»')
    const ai = screen.getByRole('region', { name: 'AI-заключение' })
    server.use(
      http.post('*/api/v1/manager/applications/:id/ai-feedback', () =>
        apiError(503, 'SERVICE_UNAVAILABLE'),
      ),
    )
    const up = within(ai).getByRole('button', { name: 'Полезно' })
    await user.click(up)
    await waitFor(() => expect(up).toHaveAttribute('aria-pressed', 'false'))
  })

  it('одобрение: решение уходит, действия пропадают, клиент получает договор', async () => {
    await managerWithQueue()
    const { user, application } = await openCard('director.techservice', 'ООО «ТехСервис»')
    await user.click(screen.getByRole('button', { name: 'Одобрить' }))
    const dialog = await screen.findByRole('dialog', { name: 'Одобрить заявку' })
    await user.click(within(dialog).getByRole('button', { name: 'Одобрить' }))

    expect(await screen.findByText('Заявка одобрена')).toBeInTheDocument()
    expect(
      await screen.findByText('Действий нет: решение по заявке уже принято'),
    ).toBeInTheDocument()
    expect(application.status).toBe('APPROVED')
    expect(application.contract?.amount_rub).toBe('2000000.00')
  })

  it('встречное предложение: лимит подставлен, предпросмотр проверяет условия', async () => {
    await managerWithQueue()
    const { user, application } = await openCard('director.bakery', 'ООО «Пекарня Плюс»')
    await user.click(screen.getByRole('button', { name: 'Предложить другие условия' }))
    const dialog = await screen.findByRole('dialog', { name: 'Встречное предложение' })
    const amount = within(dialog).getByLabelText('Сумма')
    expect(amount).toHaveValue('2\u00A0340\u00A0000')
    expect(await within(dialog).findByText('Условия проходят проверку')).toBeInTheDocument()

    // Больше лимита — бэк не пропустит, кнопка неактивна.
    await user.clear(amount)
    await user.type(amount, '2900000')
    expect(await within(dialog).findByText('Сумма больше лимита на этот срок')).toBeInTheDocument()
    const submit = within(dialog).getByRole('button', { name: 'Отправить предложение' })
    expect(submit).toBeDisabled()

    await user.click(within(dialog).getByRole('button', { name: /Взять лимит/ }))
    expect(await within(dialog).findByText('Условия проходят проверку')).toBeInTheDocument()
    await user.type(within(dialog).getByLabelText('Комментарий'), 'DSCR 1.10, даём по лимиту')
    await waitFor(() => expect(submit).toBeEnabled())
    await user.click(submit)

    expect(await screen.findByText('Встречное предложение отправлено клиенту')).toBeInTheDocument()
    expect(application.status).toBe('COUNTER_OFFER')
    expect(application.offer).toMatchObject({ amount_rub: '2340000.00', term_months: 36 })
  })

  it('встречное предложение: «та же сумма, найти срок» для Пекарни — 54 мес.', async () => {
    await managerWithQueue()
    const { user } = await openCard('director.bakery', 'ООО «Пекарня Плюс»')
    await user.click(screen.getByRole('button', { name: 'Предложить другие условия' }))
    const dialog = await screen.findByRole('dialog', { name: 'Встречное предложение' })
    await user.click(within(dialog).getByRole('button', { name: 'Та же сумма, найти срок' }))
    expect(await within(dialog).findByText('3 000 000 ₽ проходит на 54 мес.')).toBeInTheDocument()
    expect(within(dialog).getByLabelText('Срок, мес.')).toHaveValue('54')
    expect(within(dialog).getByLabelText('Сумма')).toHaveValue('3\u00A0000\u00A0000')
    expect(await within(dialog).findByText('Условия проходят проверку')).toBeInTheDocument()
  })

  it('решение: 409 — сообщение о другом менеджере, комментарий остаётся', async () => {
    await managerWithQueue()
    const { user } = await openCard('director.techservice', 'ООО «ТехСервис»')
    server.use(
      http.post('*/api/v1/manager/applications/:id/decisions', () =>
        apiError(409, 'REVISION_CONFLICT', 'conflict', { details: { current_revision: 99 } }),
      ),
    )
    await user.click(screen.getByRole('button', { name: 'Одобрить' }))
    const dialog = await screen.findByRole('dialog', { name: 'Одобрить заявку' })
    expect(dialog).toHaveTextContent('Клиент увидит: Заявка одобрена')
    await user.type(within(dialog).getByLabelText('Комментарий'), 'Всё сходится')
    await user.click(within(dialog).getByRole('button', { name: 'Одобрить' }))
    expect(
      await within(dialog).findByText(/Заявку уже обработал другой менеджер/),
    ).toBeInTheDocument()
    expect(within(dialog).getByLabelText('Комментарий')).toHaveValue('Всё сходится')
    expect(within(dialog).getByRole('button', { name: 'Обновить' })).toBeInTheDocument()
  })

  it('чужая или несуществующая заявка — экран 404 внутри каркаса', async () => {
    await managerWithQueue()
    renderApp('/manager/applications/00000000-0000-4000-8000-000000000000')
    expect(await screen.findByText('Страница не найдена')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'На главную' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'CreditFlow' })).toBeInTheDocument()
  })

  it('стоп-фактор: только отказ, причина подсказана, без комментария не уходит', async () => {
    await managerWithQueue()
    const { user, application } = await openCard('director.vector', 'ООО «Вектор»')
    const summary = screen.getByRole('region', { name: 'Рекомендация системы' })
    expect(
      within(summary)
        .getAllByRole('button')
        .map((button) => button.textContent),
    ).toEqual(['Стоп-фактор', 'Отказать'])
    await user.click(within(summary).getByRole('button', { name: 'Отказать' }))
    const dialog = await screen.findByRole('dialog', { name: 'Отказать в кредите' })
    expect(within(dialog).getByRole('radio', { name: /не числится действующей/ })).toBeChecked()
    expect(within(dialog).getByText('Клиент увидит:')).toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: 'Отказать' }))
    expect(within(dialog).getByLabelText('Комментарий')).toHaveAccessibleDescription(
      /Напишите комментарий/,
    )
    await user.type(within(dialog).getByLabelText('Комментарий'), 'Компания в ликвидации')
    await user.click(within(dialog).getByRole('button', { name: 'Отказать' }))

    expect(await screen.findByText('Отказ отправлен клиенту')).toBeInTheDocument()
    expect(application.status).toBe('REJECTED')
    expect(application.client_reason_code).toBe('COMPANY_STATUS')
  })

  it('вопрос клиенту: подсказка из AI-заключения подставляется в поле', async () => {
    await managerWithQueue()
    const { user, application } = await openCard('ip.sokolova', 'ИП Соколова Алёна Викторовна')
    await user.click(screen.getByRole('button', { name: 'Запросить информацию' }))
    const dialog = await screen.findByRole('dialog', { name: 'Вопрос клиенту' })
    await user.click(
      within(dialog).getByRole('button', { name: /Чем вызваны просрочки в кредитной истории/ }),
    )
    expect(within(dialog).getByLabelText('Вопрос')).toHaveValue(
      'Чем вызваны просрочки в кредитной истории и погашены ли они сейчас?',
    )
    await user.click(within(dialog).getByRole('button', { name: 'Отправить вопрос' }))

    expect(await screen.findByText('Вопрос отправлен клиенту')).toBeInTheDocument()
    expect(application.status).toBe('NEED_INFO')
    expect(application.info_request?.question_text).toMatch(/просрочки/)
  })

  it('AI-заключение: «Использовать в дозапросе» открывает вопрос с текстом', async () => {
    await managerWithQueue()
    const { user } = await openCard('director.techservice', 'ООО «ТехСервис»')
    const ai = screen.getByRole('region', { name: 'AI-заключение' })
    const [use] = within(ai).getAllByRole('button', { name: 'Использовать в дозапросе' })
    if (!use) throw new Error('Нет вопросов в заключении')
    const question = use.closest('li')?.querySelector('span')?.textContent ?? ''
    expect(question).not.toBe('')
    await user.click(use)
    const dialog = await screen.findByRole('dialog', { name: 'Вопрос клиенту' })
    expect(within(dialog).getByLabelText('Вопрос')).toHaveValue(question)
  })

  it('оценка AI-заключения сохраняется и попадает в сводку', async () => {
    await managerWithQueue()
    const { user } = await openCard('director.techservice', 'ООО «ТехСервис»')
    const ai = screen.getByRole('region', { name: 'AI-заключение' })
    await user.click(within(ai).getByRole('button', { name: 'Полезно' }))
    expect(await within(ai).findByText('Спасибо, оценка учтена')).toBeInTheDocument()
    expect(within(ai).getByRole('button', { name: 'Полезно' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(db.listFeedback()).toEqual([
      expect.objectContaining({ verdict: 'UP', source: 'replay', comment: null }),
    ])
  })
})
