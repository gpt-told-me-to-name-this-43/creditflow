import { expect, test } from './fixtures.ts'
import { ClientApplicationPage } from './pages/client.ts'
import { CardPage } from './pages/manager.ts'
import { ClientApi } from './support/api.ts'
import { companies, managers } from './support/companies.ts'

const C3 = companies.C3
const ANSWER = 'Просрочка 2024 года закрыта, справка из банка приложена к заявке в офисе.'

test.beforeEach(async ({ resetDb }) => {
  await resetDb('clean')
})

test('s5: C3 — вопрос из AI-заключения, ответ клиента, одобрение', async ({
  clientPage,
  managerPage,
}) => {
  const api = await ClientApi.as(C3.login)
  const { id } = await api.submitted(C3)
  await api.dispose()

  const manager = await managerPage(managers.anna)
  const card = new CardPage(manager)
  await card.goto(id, C3.name)
  // Заключение готовится в фоне — карточка работает и до него.
  const use = card.ai.getByRole('button', { name: 'Использовать в дозапросе' }).first()
  await expect(use).toBeVisible({ timeout: 30_000 })
  const question = (await use.locator('xpath=..').locator('span').first().textContent()) ?? ''
  expect(question).not.toBe('')
  await use.click()
  const dialog = card.dialog('Вопрос клиенту')
  await expect(dialog.getByLabel('Вопрос')).toHaveValue(question)
  await dialog.getByRole('button', { name: 'Отправить вопрос' }).click()
  await card.expectDone('Вопрос отправлен клиенту')

  const application = new ClientApplicationPage(await clientPage(C3.login))
  await application.goto(id)
  await application.expectStatus('Нужно уточнение')
  await expect(application.page.getByRole('main')).toContainText(question)
  await application.answer(ANSWER)
  await application.expectStatus('На рассмотрении')

  // Менеджер видит ответ в истории и одобряет (рекомендация — ручное рассмотрение).
  await manager.reload()
  await card.expectLoaded(C3.name)
  await expect(manager.getByRole('region', { name: 'История' })).toContainText(ANSWER)
  const approve = await card.approve('Просрочка закрыта, ответ клиента подтверждает')
  await expect(approve).toBeHidden()
  await card.expectDone('Заявка одобрена')
})
