import { expect, test } from './fixtures.ts'
import { ClientApplicationPage } from './pages/client.ts'
import { CardPage } from './pages/manager.ts'
import { ClientApi, ManagerApi } from './support/api.ts'
import { companies, managers } from './support/companies.ts'

const C2 = companies.C2

test.beforeEach(async ({ resetDb }) => {
  await resetDb('clean')
})

test('s4: C2 — клиент отказывается от оффера → DECLINED', async ({ clientPage, managerPage }) => {
  const api = await ClientApi.as(C2.login)
  const { id } = await api.submitted(C2)
  await api.dispose()

  const card = new CardPage(await managerPage(managers.anna))
  await card.goto(id, C2.name)
  const dialog = await card.openCounterOffer()
  await card.expectOfferValid(dialog)
  await dialog.getByLabel('Комментарий').fill('Даём по лимиту')
  await dialog.getByRole('button', { name: 'Отправить предложение' }).click()
  await card.expectDone('Встречное предложение отправлено клиенту')

  const application = new ClientApplicationPage(await clientPage(C2.login))
  await application.goto(id)
  await application.expectStatus('Новое предложение')
  await application.declineOffer()
  await application.expectStatus('Вы отказались')

  const manager = await ManagerApi.as(managers.anna)
  try {
    expect((await manager.application(id)).status).toBe('DECLINED')
  } finally {
    await manager.dispose()
  }
})
