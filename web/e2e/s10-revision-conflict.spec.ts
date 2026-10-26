import { expect, test } from './fixtures.ts'
import { CardPage } from './pages/manager.ts'
import { ClientApi, ManagerApi } from './support/api.ts'
import { companies, managers } from './support/companies.ts'

const C1 = companies.C1
const COMMENT = 'Проверил выписку — согласен с рекомендацией'

test.beforeEach(async ({ resetDb }) => {
  await resetDb('clean')
})

test('s10: два менеджера — второй видит 409, комментарий сохранён', async ({ managerPage }) => {
  const api = await ClientApi.as(C1.login)
  const { id } = await api.submitted(C1)
  await api.dispose()

  const anna = new CardPage(await managerPage(managers.anna))
  const oleg = new CardPage(await managerPage(managers.oleg))
  await anna.goto(id, C1.name)
  await oleg.goto(id, C1.name)

  // Олег открыл форму и пишет комментарий, Анна в это время одобряет.
  const olegDialog = await oleg.openDecision('Одобрить', 'Одобрить заявку')
  await olegDialog.getByLabel('Комментарий').fill(COMMENT)
  await anna.approve()
  await anna.expectDone('Заявка одобрена')

  await olegDialog.getByRole('button', { name: 'Одобрить', exact: true }).click()
  await expect(olegDialog.getByText(/Заявку уже обработал другой менеджер/)).toBeVisible()
  await expect(olegDialog.getByLabel('Комментарий')).toHaveValue(COMMENT)
  await olegDialog.getByRole('button', { name: 'Обновить' }).click()
  await expect(olegDialog.getByLabel('Комментарий')).toHaveValue(COMMENT)

  const manager = await ManagerApi.as(managers.anna)
  try {
    const application = await manager.application(id)
    expect(application.status).toBe('APPROVED')
    expect(application.decisions).toHaveLength(1)
  } finally {
    await manager.dispose()
  }
})
