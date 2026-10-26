import { expect, test } from './fixtures.ts'
import { CardPage } from './pages/manager.ts'
import { ClientApi, ManagerApi } from './support/api.ts'
import { companies, managers } from './support/companies.ts'

const C1 = companies.C1

test.beforeEach(async ({ resetDb }) => {
  await resetDb('clean')
})

test('s11: двойной клик по «Отправить» — одно решение', async ({ managerPage }) => {
  const api = await ClientApi.as(C1.login)
  const { id } = await api.submitted(C1)
  await api.dispose()

  const card = new CardPage(await managerPage(managers.anna))
  await card.goto(id, C1.name)
  const dialog = await card.openDecision('Одобрить', 'Одобрить заявку')
  await dialog.getByRole('button', { name: 'Одобрить', exact: true }).dblclick()
  await card.expectDone('Заявка одобрена')

  const manager = await ManagerApi.as(managers.anna)
  try {
    const application = await manager.application(id)
    expect(application.status).toBe('APPROVED')
    expect(application.decisions).toHaveLength(1)
  } finally {
    await manager.dispose()
  }
})
