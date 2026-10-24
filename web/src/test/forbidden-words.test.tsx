import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { CLIENT_REASON_CODES } from '@/api/enums.ts'
import { type Decision, NEED_INFO_QUESTION, setStatus, signApplication } from '@/mocks/db.ts'
import { renderApp } from './render.tsx'
import { signInAs, signInWithCompany, submittedApplication } from './session.ts'

// Клиент не видит внутренних метрик и кодов (#9): проверяем текст отрисованных экранов,
// а не только content/ — так ловятся и тексты, попавшие мимо content/.
const FORBIDDEN = [/скоринг/i, /\bscore\b/i, /dscr/i, /лимит/i]
const LATIN_CODE = /\b[A-Z][A-Z_]{2,}\b/

function expectClean() {
  const text = document.body.textContent ?? ''
  for (const word of FORBIDDEN) expect(text).not.toMatch(word)
  expect(text).not.toMatch(LATIN_CODE)
}

async function applicationScreen(decision?: Decision) {
  const application = await submittedApplication(decision)
  renderApp(`/client/applications/${application.id}`)
  await screen.findByRole('heading', { name: 'Оборудование', level: 1 })
  return application
}

describe('на клиентских экранах нет внутренних терминов и кодов', () => {
  it('вход', async () => {
    renderApp('/login')
    await screen.findByText('Демо-доступ')
    await screen.findByText('Иванов Пётр Сергеевич')
    expectClean()
  })

  it('привязка компании', async () => {
    await signInAs('director.bakery')
    renderApp('/client/onboarding')
    await screen.findByRole('heading', { name: 'Подключите компанию' })
    expectClean()
  })

  it('мастер: все шаги', async () => {
    await signInWithCompany('director.techservice', '0099010012')
    const user = userEvent.setup()
    renderApp('/client/applications/new')
    await user.type(
      await screen.findByLabelText('Что нужно бизнесу'),
      'Нужно 2 млн на 3 года на печь',
    )
    await user.click(screen.getByRole('button', { name: 'Распознать' }))
    await screen.findByText('Вот что мы поняли из вашего текста')
    expectClean()
    await user.click(screen.getByRole('button', { name: 'Дальше' }))
    await screen.findByRole('heading', { name: 'Проверьте параметры кредита' })
    expectClean()
    await user.click(screen.getByRole('button', { name: 'Подтвердить параметры' }))
    await screen.findByRole('heading', { name: 'Выберите кредит' })
    expectClean()
    await user.click(screen.getByRole('button', { name: 'Выбрать: Инвестиционный кредит' }))
    await screen.findByRole('heading', { name: 'Проверьте заявку' })
    expectClean()
  })

  it.each([
    ['на рассмотрении', undefined],
    ['дозапрос', { action: 'REQUEST_INFO', question_text: NEED_INFO_QUESTION }],
    [
      'встречное предложение',
      { action: 'COUNTER_OFFER', amount_rub: '1560000.00', term_months: 54 },
    ],
    ['одобрена, договор', { action: 'APPROVE' }],
    ...CLIENT_REASON_CODES.map((code) => [
      `отказ ${code}`,
      { action: 'REJECT', client_reason_code: code },
    ]),
  ] as [string, Decision | undefined][])('заявка: %s', async (_name, decision) => {
    await applicationScreen(decision)
    expectClean()
  })

  it('заявка: вы отказались', async () => {
    const application = await submittedApplication({
      action: 'COUNTER_OFFER',
      amount_rub: '1560000.00',
      term_months: 36,
    })
    setStatus(application, 'DECLINED')
    renderApp(`/client/applications/${application.id}`)
    await screen.findByRole('heading', { name: 'Вы отказались от предложения банка' })
    expectClean()
  })

  it.each(['SIGNED', 'ISSUED'] as const)('заявка: %s', async (status) => {
    const application = await submittedApplication({ action: 'APPROVE' })
    signApplication(application)
    if (status === 'ISSUED') {
      application.issued_at = new Date().toISOString()
      setStatus(application, 'ISSUED')
    }
    renderApp(`/client/applications/${application.id}`)
    await screen.findByText(/Договор №/)
    expectClean()
  })

  it('мои заявки', async () => {
    await submittedApplication({ action: 'REJECT', client_reason_code: 'LOW_SCORE' })
    renderApp('/client')
    await screen.findByRole('list', { name: 'Заявки' })
    expectClean()
  })
})
