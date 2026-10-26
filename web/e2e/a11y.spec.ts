import AxeBuilder from '@axe-core/playwright'
import type { Page } from '@playwright/test'
import { expect, test } from './fixtures.ts'
import { CardPage, QueuePage } from './pages/manager.ts'
import { ClientApi } from './support/api.ts'
import { companies, managers } from './support/companies.ts'

/**
 * axe без serious и critical на ключевых страницах в обеих темах. Тема применяется
 * перезагрузкой, поэтому открытые диалоги и прочее состояние готовит `prepare`.
 */
async function expectAccessible(page: Page, label: string, prepare?: () => Promise<unknown>) {
  for (const theme of ['light', 'dark'] as const) {
    // Тема — как у пользователя: сохранённый выбор и перезагрузка (src/lib/theme.ts).
    await page.evaluate((value) => localStorage.setItem('creditflow.theme', value), theme)
    await page.reload()
    await page.waitForLoadState('networkidle')
    await expect(page.locator('html')).toHaveClass(theme === 'dark' ? /dark/ : /^(?!.*dark)/)
    await prepare?.()
    const result = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .analyze()
    const blocking = result.violations
      .filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')
      .map((violation) => ({
        id: violation.id,
        impact: violation.impact,
        targets: violation.nodes.slice(0, 5).map((node) => node.target.join(' ')),
      }))
    expect(blocking, `${label} (${theme})`).toEqual([])
  }
}

test.beforeEach(async ({ resetDb }) => {
  await resetDb('demo')
})

test('a11y: вход', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: 'Вход в кабинет' })).toBeVisible()
  await expectAccessible(page, 'вход')
})

test('a11y: клиент — список заявок и мастер', async ({ clientPage }) => {
  const page = await clientPage(companies.C1.login)
  await page.goto('/client')
  await expect(page.getByRole('heading', { name: 'Мои заявки' })).toBeVisible()
  await expectAccessible(page, 'список заявок')
  await page.getByRole('link', { name: 'Подать заявку' }).first().click()
  await expect(page.getByRole('heading', { name: 'Новая заявка' })).toBeVisible()
  await expectAccessible(page, 'мастер')
})

test('a11y: менеджер — очередь и карточка', async ({ managerPage }) => {
  const page = await managerPage(managers.anna)
  const queue = new QueuePage(page)
  await queue.goto()
  await expect(queue.table).toBeVisible()
  await expectAccessible(page, 'очередь')
  await queue.open('ООО «Склад-М»')
  await expectAccessible(page, 'карточка')
})

test('a11y: карточка «Пекарни» с расчётом и оффером', async ({ managerPage, resetDb }) => {
  await resetDb('clean')
  const api = await ClientApi.as(companies.C2.login)
  const { id } = await api.submitted(companies.C2)
  await api.dispose()
  const card = new CardPage(await managerPage(managers.anna))
  await card.goto(id, companies.C2.name)
  await expectAccessible(card.page, 'карточка C2')
  await expectAccessible(card.page, 'диалог оффера', async () => {
    const dialog = await card.openCounterOffer()
    await card.expectOfferValid(dialog)
  })
})
