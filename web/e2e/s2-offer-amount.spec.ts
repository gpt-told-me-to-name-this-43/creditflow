import { expect, test } from './fixtures.ts'
import { ClientApplicationPage } from './pages/client.ts'
import { CardPage } from './pages/manager.ts'
import { ClientApi } from './support/api.ts'
import { companies, managers } from './support/companies.ts'
import { amountValue } from './support/money.ts'

const C2 = companies.C2

test.beforeEach(async ({ resetDb }) => {
  await resetDb('clean')
})

test('s2: C2 — оффер на лимит, клиент принимает и подписывает', async ({
  clientPage,
  managerPage,
}) => {
  const api = await ClientApi.as(C2.login)
  const { id } = await api.submitted(C2)
  await api.dispose()

  const manager = await managerPage(managers.anna)
  const card = new CardPage(manager)
  await card.goto(id, C2.name)
  // Эталоны «Пекарни» — docs/demo-data.md: DSCR 1.10 ниже порога, лимит 2 340 000 ₽.
  await expect(card.calculation).toContainText('1.10')
  await expect(card.calculation).toContainText('Ниже порога')
  await expect(card.calculation).toContainText('2 340 000 ₽')

  const dialog = await card.openCounterOffer()
  await expect(dialog.getByLabel('Сумма')).toHaveValue(amountValue('2340000'))
  await card.expectOfferValid(dialog)
  await dialog.getByLabel('Комментарий').fill('DSCR 1.10 ниже порога — даём по лимиту')
  await dialog.getByRole('button', { name: 'Отправить предложение' }).click()
  await card.expectDone('Встречное предложение отправлено клиенту')

  const client = await clientPage(C2.login)
  const application = new ClientApplicationPage(client)
  await application.goto(id)
  await application.expectStatus('Новое предложение')
  await expect(client.getByRole('main')).toContainText('2 340 000')
  await application.acceptOffer()
  await application.expectStatus('Одобрена')
  await application.sign()
  await application.expectStatus('Договор подписан')
})
