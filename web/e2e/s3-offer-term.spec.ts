import { expect, test } from './fixtures.ts'
import { CardPage } from './pages/manager.ts'
import { ClientApi } from './support/api.ts'
import { companies, managers } from './support/companies.ts'
import { amountValue } from './support/money.ts'

const C2 = companies.C2

test.beforeEach(async ({ resetDb }) => {
  await resetDb('clean')
})

test('s3: C2 — «та же сумма, найти срок» даёт 54 мес. и платёж 91 356,79 ₽', async ({
  managerPage,
}) => {
  const api = await ClientApi.as(C2.login)
  const { id } = await api.submitted(C2)
  await api.dispose()

  const card = new CardPage(await managerPage(managers.anna))
  await card.goto(id, C2.name)
  const dialog = await card.openCounterOffer()
  await dialog.getByRole('button', { name: 'Та же сумма, найти срок' }).click()
  await expect(dialog.getByText('3 000 000 ₽ проходит на 54 мес.')).toBeVisible()
  await expect(dialog.getByLabel('Срок, мес.')).toHaveValue('54')
  await expect(dialog.getByLabel('Сумма')).toHaveValue(amountValue('3000000'))
  await card.expectOfferValid(dialog)
  await expect(dialog.getByRole('region', { name: 'Расчёт на новых условиях' })).toContainText(
    '91 356,79 ₽',
  )
})
