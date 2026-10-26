import { expect, test } from './fixtures.ts'
import { OnboardingPage, WizardPage } from './pages/client.ts'
import { CardPage } from './pages/manager.ts'
import { companies, managers } from './support/companies.ts'
import { amountValue } from './support/money.ts'

const C2 = companies.C2
const EXAMPLE = '3 млн на 36 месяцев на оборудование для цеха'

test.beforeEach(async ({ resetDb }) => {
  await resetDb('clean')
})

test('s8: подсказка → распознавание → предзаполнение с метками → подтверждение', async ({
  clientPage,
  managerPage,
}) => {
  const client = await clientPage(C2.login)
  await new OnboardingPage(client).goto()
  await new OnboardingPage(client).bind(C2.inn)
  const wizard = new WizardPage(client)
  await wizard.start()
  await wizard.useExample(EXAMPLE)
  const understood = await wizard.recognize()
  await expect(understood).toContainText('Оборудование')
  await expect(understood).toContainText('3 000 000 ₽')
  await expect(understood).toContainText('36 мес.')
  await expect(understood.getByRole('button', { name: 'Распознано автоматически' })).toHaveCount(3)

  await wizard.next()
  // Предзаполнено распознанным, у каждого поля — метка источника.
  await expect(client.getByLabel('Сумма')).toHaveValue(amountValue('3000000'))
  await expect(client.getByLabel('Срок, месяцев')).toHaveValue('36')
  await expect(client.getByRole('radio', { name: /^Оборудование/ })).toBeChecked()
  await expect(client.getByRole('button', { name: 'Распознано автоматически' })).toHaveCount(3)
  await wizard.confirmParams()
  await wizard.chooseProduct('Инвестиционный кредит')
  await wizard.consentAndSubmit()
  await expect(client.getByText('На рассмотрении', { exact: true }).first()).toBeVisible()
  const id = /applications\/([0-9a-f-]{36})/.exec(client.url())?.[1] ?? ''

  // Менеджер видит, откуда условия: распознаны из текста клиента.
  const card = new CardPage(await managerPage(managers.anna))
  await card.goto(id, C2.name)
  await expect(card.page.getByRole('main')).toContainText(EXAMPLE)
  await expect(card.page.getByRole('main')).not.toContainText('Источник условийВведено клиентом')
})
