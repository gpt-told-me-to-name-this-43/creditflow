import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { db } from '@/mocks/db.ts'
import { setScenario } from '@/mocks/scenarios.ts'
import { renderApp } from '@/test/render.tsx'
import { signInWithCompany } from '@/test/session.ts'

const nbsp = (s: string) => s.replaceAll(' ', '\u00a0')

async function openWizard(path = '/client/applications/new') {
  const client = await signInWithCompany('director.techservice', '0099010012')
  const user = userEvent.setup()
  const app = renderApp(path)
  await screen.findByRole('heading', { name: 'Новая заявка' })
  return { user, client, ...app }
}

function draftOf(clientId: string) {
  const draft = db.findDraft(clientId)
  if (!draft) throw new Error('Черновик не создан')
  return draft
}

async function interpretText(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.type(screen.getByLabelText('Что нужно бизнесу'), text)
  await user.click(screen.getByRole('button', { name: 'Распознать' }))
  return screen.findByText('Вот что мы поняли из вашего текста')
}

describe('мастер заявки', () => {
  it('создаёт черновик и кладёт его id и шаг в адрес', async () => {
    const { client, router } = await openWizard()
    const draft = draftOf(client.id)
    await waitFor(() =>
      expect(router.state.location.search).toEqual({ applicationId: draft.id, step: 1 }),
    )
    expect(screen.getByRole('heading', { name: 'Расскажите, на что нужны деньги' })).toBeVisible()
  })

  it('«2 млн на 3 года на печь» заполняет поля с метками, но ничего не сохраняет', async () => {
    const { user, client } = await openWizard()
    await interpretText(user, 'Нужно 2 млн на 3 года на новую печь')

    const result = screen.getByRole('status')
    expect(result).toHaveTextContent('Оборудование')
    expect(result).toHaveTextContent('2 000 000 ₽')
    expect(result).toHaveTextContent('36 мес.')
    expect(within(result).getByText('Предложено ИИ')).toBeInTheDocument()
    expect(within(result).getAllByText('Распознано автоматически')).toHaveLength(2)

    await user.click(screen.getByRole('button', { name: 'Дальше' }))
    await screen.findByRole('heading', { name: 'Проверьте параметры кредита' })
    expect(screen.getByLabelText('Сумма')).toHaveValue(nbsp('2 000 000'))
    expect(screen.getByLabelText('Срок, месяцев')).toHaveValue('36')
    expect(screen.getByRole('radio', { name: /Оборудование/ })).toBeChecked()

    // Сохранён только текст: распознанные значения ждут подтверждения.
    const draft = draftOf(client.id)
    expect(draft.purpose_text).toBe('Нужно 2 млн на 3 года на новую печь')
    expect(draft.purpose_code).toBeNull()
    expect(draft.requested_amount_rub).toBeNull()
    expect(draft.term_months).toBeNull()
  })

  it('подтверждение сохраняет источники, правка снимает метку и ставит MANUAL', async () => {
    const { user, client } = await openWizard()
    await interpretText(user, 'Нужно 2 млн на 3 года на новую печь')
    await user.click(screen.getByRole('button', { name: 'Дальше' }))
    await screen.findByRole('heading', { name: 'Проверьте параметры кредита' })

    expect(screen.getAllByText('Распознано автоматически')).toHaveLength(2)
    const term = screen.getByLabelText('Срок, месяцев')
    await user.clear(term)
    await user.type(term, '24')
    expect(screen.getAllByText('Распознано автоматически')).toHaveLength(1)
    expect(screen.getByText('Предложено ИИ')).toBeInTheDocument()
    expect(screen.getByText('Часть параметров предложил ИИ — проверьте их')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Подтвердить параметры' }))
    await screen.findByRole('heading', { name: 'Выберите кредит' })

    const draft = draftOf(client.id)
    expect(draft.purpose_code).toBe('EQUIPMENT')
    expect(draft.requested_amount_rub).toBe('2000000.00')
    expect(draft.term_months).toBe(24)
    expect(draft.terms_field_sources).toEqual({
      purpose_code: 'LLM',
      requested_amount_rub: 'RULES',
      term_months: 'MANUAL',
    })
  })

  it('ИИ недоступен — объяснение, правила работают, ручная форма доступна', async () => {
    setScenario('unavailable')
    const { user } = await openWizard()
    await user.type(screen.getByLabelText('Что нужно бизнесу'), 'Нужно 2 млн на 3 года на печь')
    await user.click(screen.getByRole('button', { name: 'Распознать' }))
    expect(await screen.findByText(/Помощник сейчас недоступен/)).toBeInTheDocument()
    expect(screen.queryByText('Предложено ИИ')).not.toBeInTheDocument()
    expect(screen.getAllByText('Распознано автоматически')).toHaveLength(3)
  })

  it('не хватает данных — уточняющий вопрос', async () => {
    const { user } = await openWizard()
    await user.type(screen.getByLabelText('Что нужно бизнесу'), 'Хочу купить печь')
    await user.click(screen.getByRole('button', { name: 'Распознать' }))
    expect(await screen.findByText('Какая сумма и на какой срок вам нужна?')).toBeInTheDocument()
  })

  it('ручной путь до отправки: цель, параметры, кредит, согласие', async () => {
    const { user, client, router } = await openWizard()
    await user.click(screen.getByRole('button', { name: 'Выберу сам' }))
    await user.click(screen.getByRole('radio', { name: /Закупка товара/ }))
    await user.click(screen.getByRole('button', { name: 'Дальше' }))
    await screen.findByRole('heading', { name: 'Проверьте параметры кредита' })
    expect(draftOf(client.id).terms_field_sources).toEqual({ purpose_code: 'MANUAL' })

    // Пустые поля — ошибки под полями, запроса нет.
    await user.click(screen.getByRole('button', { name: 'Подтвердить параметры' }))
    expect(screen.getByLabelText('Сумма')).toHaveAccessibleDescription(/Укажите сумму/)
    expect(draftOf(client.id).requested_amount_rub).toBeNull()

    await user.type(screen.getByLabelText('Сумма'), '800000')
    await user.type(screen.getByLabelText('Срок, месяцев'), '12')
    expect(screen.queryByText('Распознано автоматически')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Подтвердить параметры' }))
    await screen.findByRole('heading', { name: 'Выберите кредит' })

    const suitable = screen.getByRole('list', { name: 'Подходят' })
    expect(suitable).toHaveTextContent('Оборотный кредит')
    const unsuitable = screen.getByRole('list', { name: 'Не подходят под ваши параметры' })
    expect(unsuitable).toHaveTextContent('Инвестиционный кредит')
    expect(unsuitable).toHaveTextContent('Не выдаётся на эту цель')
    expect(screen.getByText(/не является решением банка/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Выбрать: Оборотный кредит' }))
    await screen.findByRole('heading', { name: 'Проверьте заявку' })
    expect(screen.getByText('800 000 ₽')).toBeInTheDocument()

    const submit = screen.getByRole('button', { name: 'Отправить заявку' })
    expect(screen.getByRole('checkbox')).not.toBeChecked()
    expect(submit).toBeDisabled()
    const { id } = draftOf(client.id)
    await user.click(screen.getByRole('checkbox'))
    await user.click(submit)

    await waitFor(() => expect(router.state.location.pathname).toBe(`/client/applications/${id}`))
    expect(db.findApplication(id)?.status).toBe('UNDER_REVIEW')
  })

  it('перезагрузка на шаге восстанавливает сохранённые данные', async () => {
    const { user, client } = await openWizard()
    await interpretText(user, 'Нужно 2 млн на 3 года на новую печь')
    await user.click(screen.getByRole('button', { name: 'Дальше' }))
    await screen.findByRole('heading', { name: 'Проверьте параметры кредита' })
    await user.click(screen.getByRole('button', { name: 'Подтвердить параметры' }))
    await screen.findByRole('heading', { name: 'Выберите кредит' })
    const draft = draftOf(client.id)

    // «Перезагрузка» — новое приложение на том же адресе.
    cleanup()
    renderApp(`/client/applications/new?applicationId=${draft.id}&step=3`)
    expect(await screen.findByRole('heading', { name: 'Выберите кредит' })).toBeInTheDocument()

    const [changeTerms] = screen.getAllByRole('button', { name: 'Изменить параметры' })
    await user.click(changeTerms as HTMLElement)
    await screen.findByRole('heading', { name: 'Проверьте параметры кредита' })
    expect(screen.getByLabelText('Сумма')).toHaveValue(nbsp('2 000 000'))
    expect(screen.getByText('Предложено ИИ')).toBeInTheDocument()
  })

  it('шаг дальше сохранённого в адресе — возвращаем на доступный', async () => {
    const client = await signInWithCompany('director.techservice', '0099010012')
    const draft = db.createApplication(client)
    const { router } = renderApp(`/client/applications/new?applicationId=${draft.id}&step=4`)
    await screen.findByRole('heading', { name: 'Проверьте параметры кредита' })
    expect(router.state.location.search).toEqual({ applicationId: draft.id, step: 2 })
  })

  it('отправка при недоступном сервисе — заявка сохранена, можно повторить', async () => {
    const client = await signInWithCompany('director.techservice', '0099010012')
    const user = userEvent.setup()
    const draft = Object.assign(db.createApplication(client), {
      purpose_code: 'EQUIPMENT',
      requested_amount_rub: '2000000.00',
      term_months: 36,
      product_id: 'investment',
    } as const)
    setScenario('error503')
    renderApp(`/client/applications/new?applicationId=${draft.id}&step=4`)
    await screen.findByRole('heading', { name: 'Проверьте заявку' })
    await user.click(screen.getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: 'Отправить заявку' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Заявка сохранена')
    expect(draft.status).toBe('DRAFT')

    setScenario('default')
    await user.click(screen.getByRole('button', { name: 'Отправить заявку' }))
    await screen.findByRole('heading', { name: 'Заявка' })
    expect(draft.status).toBe('UNDER_REVIEW')
  })
})
