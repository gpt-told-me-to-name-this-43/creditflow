import { expect, type Locator, type Page } from '@playwright/test'

/** Очередь и сводка (/manager). */
export class QueuePage {
  constructor(readonly page: Page) {}

  async goto(status = 'UNDER_REVIEW') {
    await this.page.goto(`/manager?status=${status}`)
    await expect(this.page.getByRole('heading', { name: 'Заявки', level: 1 })).toBeVisible()
  }

  get table() {
    return this.page.getByRole('table', { name: 'Очередь заявок' })
  }

  get stats() {
    return this.page.getByRole('region', { name: 'Сводка' })
  }

  row(company: string) {
    return this.table.getByRole('row').filter({ hasText: company })
  }

  async open(company: string) {
    await this.row(company).getByRole('link', { name: company }).click()
    const card = new CardPage(this.page)
    await card.expectLoaded(company)
    return card
  }
}

/** Карточка заявки (/manager/applications/$id). */
export class CardPage {
  constructor(readonly page: Page) {}

  async goto(id: string, company: string) {
    await this.page.goto(`/manager/applications/${id}`)
    await this.expectLoaded(company)
  }

  async expectLoaded(company: string) {
    await expect(this.page.getByRole('heading', { name: company, level: 1 })).toBeVisible()
  }

  get panel() {
    return this.page.getByRole('region', { name: 'Рекомендация системы' })
  }

  get calculation() {
    return this.page.getByRole('region', { name: 'Расчёт' })
  }

  get ai() {
    return this.page.getByRole('region', { name: 'AI-заключение' })
  }

  /** Кнопки решений — только то, что пришло в `allowed_actions`. */
  actionButtons(): Locator {
    return this.panel
      .getByRole('button')
      .filter({ hasText: /^(Одобрить|Предложить другие условия|Запросить информацию|Отказать)$/ })
  }

  dialog(name: string) {
    return this.page.getByRole('dialog', { name })
  }

  async openDecision(button: string, dialog: string) {
    await this.panel.getByRole('button', { name: button, exact: true }).click()
    const opened = this.dialog(dialog)
    await expect(opened).toBeVisible()
    return opened
  }

  async approve(comment?: string) {
    const dialog = await this.openDecision('Одобрить', 'Одобрить заявку')
    if (comment) await dialog.getByLabel('Комментарий').fill(comment)
    await dialog.getByRole('button', { name: 'Одобрить', exact: true }).click()
    return dialog
  }

  async reject(reason: string, comment: string) {
    const dialog = await this.openDecision('Отказать', 'Отказать в кредите')
    await dialog.getByText(reason, { exact: true }).click()
    await dialog.getByLabel('Комментарий').fill(comment)
    await dialog.getByRole('button', { name: 'Отказать', exact: true }).click()
    return dialog
  }

  async openCounterOffer() {
    return this.openDecision('Предложить другие условия', 'Встречное предложение')
  }

  /** Предпросмотр оффера считается на бэке через 400 мс после ввода — ждём итог проверки. */
  async expectOfferValid(dialog: Locator) {
    await expect(dialog.getByText('Условия проходят проверку')).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Отправить предложение' })).toBeEnabled()
  }

  async expectDone(toast: string) {
    await expect(this.page.getByText(toast)).toBeVisible()
    await expect(this.panel.getByText('Действий нет: решение по заявке уже принято')).toBeVisible()
  }
}
