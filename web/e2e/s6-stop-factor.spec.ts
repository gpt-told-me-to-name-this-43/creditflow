import { expect, test } from './fixtures.ts'
import { ClientApplicationPage } from './pages/client.ts'
import { CardPage } from './pages/manager.ts'
import { ClientApi } from './support/api.ts'
import { companies, managers } from './support/companies.ts'

const C4 = companies.C4

test.beforeEach(async ({ resetDb }) => {
  await resetDb('clean')
})

test('s6: C4 — стоп-фактор, только «Отказать», причина видна клиенту', async ({
  clientPage,
  managerPage,
}) => {
  const api = await ClientApi.as(C4.login)
  const { id } = await api.submitted(C4)
  await api.dispose()

  const card = new CardPage(await managerPage(managers.anna))
  await card.goto(id, C4.name)
  // Вместо расчёта — объяснение; из действий — только отказ.
  await expect(card.calculation).toContainText('Недостаточно истории по счёту')
  await expect(card.actionButtons()).toHaveCount(1)
  await expect(card.actionButtons()).toHaveText('Отказать')
  await expect(card.panel).toContainText('доступен только отказ')

  const dialog = await card.openDecision('Отказать', 'Отказать в кредите')
  // Причина для клиента подставлена по стоп-фактору.
  const clientSees = dialog.getByText(/^Клиент увидит:/)
  await expect(clientSees).toBeVisible()
  const seen = ((await clientSees.textContent()) ?? '').replace('Клиент увидит:', '').trim()
  await dialog.getByLabel('Комментарий').fill('История по счёту 4 мес. — стоп-фактор')
  await dialog.getByRole('button', { name: 'Отказать', exact: true }).click()
  await card.expectDone('Отказ отправлен клиенту')

  const application = new ClientApplicationPage(await clientPage(C4.login))
  await application.goto(id)
  await application.expectStatus('Отказ')
  await expect(application.page.getByRole('main')).toContainText(seen.split('.')[0] ?? seen)
})
