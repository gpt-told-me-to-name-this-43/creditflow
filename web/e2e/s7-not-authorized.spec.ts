import { expect, test } from './fixtures.ts'
import { OnboardingPage } from './pages/client.ts'
import { accountantBakery, companies } from './support/companies.ts'

test.beforeEach(async ({ resetDb }) => {
  await resetDb('clean')
})

test('s7: бухгалтер не может привязать «Пекарню» — нужен руководитель', async ({ clientPage }) => {
  const page = await clientPage(accountantBakery)
  const onboarding = new OnboardingPage(page)
  await onboarding.goto()
  await onboarding.submitInn(companies.C2.inn)
  await expect(page.getByRole('main')).toContainText(
    'Подать заявку может только руководитель компании или сам ИП',
  )
  await expect(page.getByRole('heading', { name: 'Мы нашли вашу компанию' })).toBeHidden()
})
