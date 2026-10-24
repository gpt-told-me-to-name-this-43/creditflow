import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { components } from '@/api/schema.d.ts'
import { formatMoney, sumMoney } from '@/lib/money.ts'
import { toContract } from '@/mocks/views.ts'
import { renderApp } from '@/test/render.tsx'
import { server } from '@/test/server.ts'
import { submittedApplication } from '@/test/session.ts'

async function openApproved() {
  const application = await submittedApplication({ action: 'APPROVE' })
  const user = userEvent.setup()
  const app = renderApp(`/client/applications/${application.id}`)
  await screen.findByRole('heading', { name: 'Подписание договора' })
  return { user, application, ...app }
}

/** Код из демо-баннера: интерфейс показывает его только из `demo_code` ответа. */
function demoCode() {
  const banner = screen.getByText(/^Демо: вместо SMS — код \d{6}$/)
  return (banner.textContent ?? '').slice(-6)
}

describe('договор', () => {
  it('условия, ключевые положения и график: три строки, весь график, итог до копейки', async () => {
    const { user, application } = await openApproved()
    const contract = toContract(application)

    expect(screen.getByText(`Договор № ${contract.number}`)).toBeInTheDocument()
    expect(screen.getByText('Ожидает подписания')).toBeInTheDocument()
    expect(screen.getByText('Ключевые условия договора')).toBeInTheDocument()

    const table = screen.getByRole('table', { name: 'График платежей' })
    const bodyRows = () => within(table).getAllByRole('row').slice(1, -1)
    expect(bodyRows()).toHaveLength(3)

    await user.click(screen.getByRole('button', { name: 'Показать весь график (36 платежей)' }))
    expect(bodyRows()).toHaveLength(36)

    // Итог — сумма строк графика: основной долг равен сумме кредита, проценты — переплате.
    const total = within(table).getAllByRole('row').at(-1) as HTMLElement
    const [payment, principal, interest] = within(total)
      .getAllByRole('cell')
      .map((cell) => cell.textContent)
    expect(principal).toBe(formatMoney(contract.amount_rub))
    expect(interest).toBe(formatMoney(contract.overpayment_rub))
    expect(payment).toBe(formatMoney(sumMoney([contract.amount_rub, contract.overpayment_rub])))
  })
})

describe('подписание', () => {
  it('без согласия код не запросить; верный код — подписан, затем зачисление', async () => {
    const { user, application } = await openApproved()
    const request = screen.getByRole('button', { name: 'Получить код' })
    expect(request).toBeDisabled()
    await user.click(screen.getByRole('checkbox', { name: /согласен/ }))
    await user.click(request)

    const code = await screen.findByLabelText('Код подтверждения')
    expect(code).toHaveAccessibleDescription(/Код действует ещё (5:00|4:5\d)/)
    expect(code).toHaveAccessibleDescription(/Осталось 3 попытки/)

    await user.type(code, demoCode())
    await user.click(screen.getByRole('button', { name: 'Подписать договор' }))

    expect(await screen.findByRole('heading', { name: 'Зачисляем средства…' })).toBeInTheDocument()
    expect(application.status).toBe('SIGNED')
  })

  it('неверный код — ошибка и остаток попыток, после трёх — нужен новый код', async () => {
    const { user } = await openApproved()
    await user.click(screen.getByRole('checkbox', { name: /согласен/ }))
    await user.click(screen.getByRole('button', { name: 'Получить код' }))
    const code = await screen.findByLabelText('Код подтверждения')
    const wrong = demoCode() === '000000' ? '111111' : '000000'

    await user.type(code, wrong)
    await user.click(screen.getByRole('button', { name: 'Подписать договор' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Неверный код. Осталось 2 попытки')
    expect(code).toHaveValue('')

    await user.type(code, wrong)
    await user.click(screen.getByRole('button', { name: 'Подписать договор' }))
    expect(await screen.findByText('Неверный код. Осталось 1 попытка')).toBeInTheDocument()

    await user.type(code, wrong)
    await user.click(screen.getByRole('button', { name: 'Подписать договор' }))
    expect(await screen.findByText(/слишком много раз/)).toBeInTheDocument()
    expect(code).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Получить новый код' }))
    await waitFor(() => expect(code).toBeEnabled())
    expect(code).toHaveAccessibleDescription(/Осталось 3 попытки/)
  })

  it('вставка кода оставляет только шесть цифр', async () => {
    const { user } = await openApproved()
    await user.click(screen.getByRole('checkbox', { name: /согласен/ }))
    await user.click(screen.getByRole('button', { name: 'Получить код' }))
    const code = await screen.findByLabelText('Код подтверждения')
    await user.click(code)
    await user.paste('Ваш код: 12 34-56 7')
    expect(code).toHaveValue('123456')
  })

  it('код истёк — поле недоступно, можно получить новый', async () => {
    const { user, application } = await openApproved()
    server.use(
      http.post('/api/v1/applications/:id/sign/challenge', () =>
        HttpResponse.json({
          challenge_id: '00000000-0000-4000-8000-000000009999',
          expires_at: new Date(Date.now() + 1000).toISOString(),
          attempts_remaining: 3,
          revision: application.revision,
          demo_code: '123456',
        } satisfies components['schemas']['SignChallenge']),
      ),
    )
    await user.click(screen.getByRole('checkbox', { name: /согласен/ }))
    await user.click(screen.getByRole('button', { name: 'Получить код' }))
    const code = await screen.findByLabelText('Код подтверждения')
    await waitFor(() => expect(code).toBeDisabled(), { timeout: 3000 })
    expect(code).toHaveAccessibleDescription('Код больше не действует. Получите новый')
    expect(screen.getByRole('button', { name: 'Подписать договор' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Получить новый код' })).toBeEnabled()
  })

  it('деньги зачислены: сумма, счёт, первый платёж', async () => {
    const { user, application, queryClient } = await openApproved()
    await user.click(screen.getByRole('checkbox', { name: /согласен/ }))
    await user.click(screen.getByRole('button', { name: 'Получить код' }))
    await user.type(await screen.findByLabelText('Код подтверждения'), demoCode())
    await user.click(screen.getByRole('button', { name: 'Подписать договор' }))
    await screen.findByRole('heading', { name: 'Зачисляем средства…' })

    // Выдача в моках — через 3 с; ждём её и следующий опрос.
    await waitFor(() => expect(application.status).toBe('ISSUED'), { timeout: 4000 })
    await queryClient.refetchQueries({ queryKey: ['applications', application.id] })
    expect(await screen.findByRole('heading', { name: 'Средства зачислены' })).toBeInTheDocument()
    expect(screen.getAllByText('40702 •••• 4821')).not.toHaveLength(0)
    expect(screen.getByText('Первый платёж')).toBeInTheDocument()
    expect(await screen.findByText(/^Деньги зачислены \d/)).toBeInTheDocument()
  }, 8000)
})

/** Задерживает запросы на `path`, пока не вызван `release()`; затем отвечает обычный мок. */
function hold(path: string) {
  let release = () => {}
  const gate = new Promise<void>((resolve) => (release = resolve))
  let arrived = () => {}
  const started = new Promise<void>((resolve) => (arrived = resolve))
  server.use(
    http.post(`*/api/v1/applications/:applicationId/${path}`, async () => {
      arrived()
      await gate
    }),
  )
  return { started, release }
}

describe('подписание: пересекающиеся запросы', () => {
  it('пока идёт подписание, новый код не запросить; ответ старого кода не гасит текущий', async () => {
    const { user } = await openApproved()
    await user.click(screen.getByRole('checkbox', { name: /согласен/ }))
    await user.click(screen.getByRole('button', { name: 'Получить код' }))
    const code = await screen.findByLabelText('Код подтверждения')
    const first = demoCode()

    const signing = hold('sign')
    await user.type(code, first === '000000' ? '111111' : '000000')
    await user.click(screen.getByRole('button', { name: 'Подписать договор' }))
    await signing.started

    const newCode = screen.getByRole('button', { name: 'Получить новый код' })
    expect(newCode).toBeDisabled()
    await user.click(newCode)
    signing.release()

    expect(await screen.findByRole('alert')).toHaveTextContent(/Неверный код/)
    expect(screen.getByLabelText('Код подтверждения')).toBeEnabled()
    expect(demoCode()).toBe(first)
  })

  it('пока запрашивается новый код, подписать нельзя', async () => {
    const { user } = await openApproved()
    await user.click(screen.getByRole('checkbox', { name: /согласен/ }))
    await user.click(screen.getByRole('button', { name: 'Получить код' }))
    const code = await screen.findByLabelText('Код подтверждения')
    await user.type(code, demoCode())

    const issuing = hold('sign/challenge')
    await user.click(screen.getByRole('button', { name: 'Получить новый код' }))
    await issuing.started
    expect(screen.getByRole('button', { name: 'Подписать договор' })).toBeDisabled()
    issuing.release()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Получить новый код' })).toBeEnabled(),
    )
  })
})
