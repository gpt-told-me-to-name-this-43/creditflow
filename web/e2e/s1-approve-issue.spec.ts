import { expect, test } from './fixtures.ts'
import { ClientApplicationPage, OnboardingPage, WizardPage } from './pages/client.ts'
import { QueuePage } from './pages/manager.ts'
import { ClientApi } from './support/api.ts'
import { companies, managers } from './support/companies.ts'
import { kopecks, rub, sumKopecks } from './support/money.ts'

const C1 = companies.C1

test.beforeEach(async ({ resetDb }) => {
  await resetDb('clean')
})

test('s1: C1 — заявка, одобрение, подписание демо-кодом, выдача', async ({
  clientPage,
  managerPage,
}) => {
  // Клиент: привязка, мастер, отправка — целиком в браузере.
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
  await wizard.consentAndSubmit()
  const application = new ClientApplicationPage(client)
  await application.expectStatus('На рассмотрении')
  const id = application.id

  // Менеджер: рекомендация «можно одобрять», одобрение без комментария.
  const manager = await managerPage(managers.anna)
  const queue = new QueuePage(manager)
  await queue.goto()
  await expect(queue.row(C1.name)).toContainText('Можно одобрять')
  const card = await queue.open(C1.name)
  await card.approve()
  await card.expectDone('Заявка одобрена')

  // Клиент видит одобрение без перезагрузки, подписывает демо-кодом, ждёт выдачи.
  await application.expectStatus('Одобрена')
  await application.sign()
  await application.expectStatus('Договор подписан')
  await application.expectStatus('Деньги зачислены', 30_000)

  // Итог графика на экране совпадает с договором из API.
  const api = await ClientApi.as(C1.login)
  try {
    const contract = await api.contract(id)
    const principal = sumKopecks(contract.schedule.map((item) => item.principal_rub))
    const payments = sumKopecks(contract.schedule.map((item) => item.payment_rub))
    expect(principal).toBe(kopecks(contract.amount_rub))
    expect(payments).toBe(kopecks(contract.amount_rub) + kopecks(contract.overpayment_rub))
    const total = client.getByRole('table', { name: 'График платежей' }).getByRole('row', {
      name: /Итого/,
    })
    await expect(total).toContainText(rub(payments))
    await expect(total).toContainText(rub(principal))
  } finally {
    await api.dispose()
  }
})
