import { execFileSync } from 'node:child_process'
import { request } from '@playwright/test'
import { expect, test } from './fixtures.ts'
import { OnboardingPage, WizardPage } from './pages/client.ts'
import { companies } from './support/companies.ts'
import { API, baseURL } from './support/env.ts'

const C1 = companies.C1
// Команда compose того же стека (make e2e задаёт пути к docker-compose.yml и .e2e.yml).
const COMPOSE = (process.env.E2E_COMPOSE ?? 'docker compose').split(' ')

/** ext-sim недоступен на шаге Submit: так же, как T1 (БКИ не отвечает), — design.md §3.4. */
function extSim(action: 'stop' | 'start') {
  const [bin = 'docker', ...args] = COMPOSE
  execFileSync(bin, [...args, action, 'ext-sim'], { stdio: 'inherit' })
}

/** ext-sim снова отвечает: health api видит его без деградации. */
async function waitForExtSim() {
  const api = await request.newContext({ baseURL: baseURL() })
  try {
    await expect
      .poll(
        async () =>
          ((await (await api.get(`${API}/health`)).json()) as { ext_sim?: string }).ext_sim,
        {
          timeout: 60_000,
        },
      )
      .toBe('ok')
  } finally {
    await api.dispose()
  }
}

test.beforeEach(async ({ resetDb }) => {
  await resetDb('clean')
})

test.afterEach(async () => {
  extSim('start')
  await waitForExtSim()
})

test('s9: сбой источника при отправке — баннер, черновик и данные формы на месте', async ({
  clientPage,
}) => {
  const client = await clientPage(C1.login)
  await new OnboardingPage(client).goto()
  await new OnboardingPage(client).bind(C1.inn)
  const wizard = new WizardPage(client)
  await wizard.start()
  await wizard.chooseManually()
  await client.getByRole('button', { name: 'Дальше' }).click()
  await wizard.fillParams({ purpose: 'Оборудование', amount: '2000000', term: '36' })
  await wizard.confirmParams()
  await wizard.chooseProduct('Инвестиционный кредит')

  extSim('stop')
  await wizard.consentAndSubmit()
  const banner = client
    .getByRole('alert')
    .filter({ hasText: 'Заявка сохранена, но отправить её не удалось' })
  await expect(banner).toBeVisible({ timeout: 30_000 })
  // Остались на шаге проверки, условия не потерялись.
  await expect(client.getByRole('heading', { name: 'Проверьте заявку' })).toBeVisible()
  await expect(client.getByRole('main')).toContainText('2 000 000 ₽')
  await expect(client.getByRole('main')).toContainText('36 мес.')

  // Черновик сохранён: он в списке заявок.
  await client.goto('/client')
  await expect(client.getByRole('list', { name: 'Заявки' })).toContainText('Черновик')

  // После восстановления источника тот же черновик отправляется.
  extSim('start')
  await waitForExtSim()
  await client.getByRole('link', { name: 'Продолжить' }).click()
  await expect(client.getByRole('heading', { name: 'Проверьте заявку' })).toBeVisible()
  await wizard.consentAndSubmit()
  await expect(client.getByText('На рассмотрении', { exact: true }).first()).toBeVisible({
    timeout: 30_000,
  })
})
