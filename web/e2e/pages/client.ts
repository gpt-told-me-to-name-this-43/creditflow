import { expect, type Locator, type Page } from '@playwright/test'

/** Привязка компании по ИНН (/client/onboarding). */
export class OnboardingPage {
  constructor(readonly page: Page) {}

  async goto() {
    await this.page.goto('/client/onboarding')
    await expect(this.page.getByRole('heading', { name: 'Подключите компанию' })).toBeVisible()
  }

  async submitInn(inn: string) {
    await this.page.getByLabel('ИНН компании или ИП').fill(inn)
    await this.page.getByRole('checkbox', { name: /обработку персональных данных/ }).check()
    await this.page.getByRole('button', { name: 'Найти компанию' }).click()
  }

  async bind(inn: string) {
    await this.submitInn(inn)
    await expect(this.page.getByRole('heading', { name: 'Мы нашли вашу компанию' })).toBeVisible()
  }
}

/** Мастер заявки из четырёх шагов (/client/applications/new). */
export class WizardPage {
  constructor(readonly page: Page) {}

  async start() {
    await this.page.goto('/client')
    await this.page.getByRole('link', { name: 'Подать заявку' }).first().click()
    await expect(this.page.getByRole('heading', { name: 'Новая заявка' })).toBeVisible()
  }

  get needText() {
    return this.page.getByLabel('Что нужно бизнесу')
  }

  async useExample(text: string) {
    await this.page.getByRole('button', { name: text, exact: true }).click()
    await expect(this.needText).toHaveValue(text)
  }

  async recognize() {
    await this.page.getByRole('button', { name: 'Распознать' }).click()
    return this.page.getByRole('status').filter({ hasText: 'Вот что мы поняли' })
  }

  async next() {
    await this.page.getByRole('button', { name: 'Дальше' }).click()
    await expect(
      this.page.getByRole('heading', { name: 'Проверьте параметры кредита' }),
    ).toBeVisible()
  }

  async chooseManually() {
    await this.page.getByRole('button', { name: 'Выберу сам' }).click()
  }

  /** Шаг 2: цель — радио с подписью-карточкой, поэтому клик по подписи. */
  async fillParams({
    purpose,
    amount,
    term,
  }: {
    purpose?: string
    amount?: string
    term?: string
  }) {
    if (purpose) await this.page.getByText(purpose, { exact: true }).click()
    if (amount) await this.page.getByLabel('Сумма').fill(amount)
    if (term) await this.page.getByLabel('Срок, месяцев').fill(term)
  }

  async confirmParams() {
    await this.page.getByRole('button', { name: 'Подтвердить параметры' }).click()
    await expect(this.page.getByRole('heading', { name: 'Выберите кредит' })).toBeVisible()
  }

  async chooseProduct(name: string) {
    await this.page.getByRole('button', { name: `Выбрать: ${name}` }).click()
    await expect(this.page.getByRole('heading', { name: 'Проверьте заявку' })).toBeVisible()
  }

  get submitButton() {
    return this.page.getByRole('button', { name: 'Отправить заявку' })
  }

  async consentAndSubmit() {
    await this.page.getByRole('checkbox', { name: /запрос кредитного отчёта в БКИ/ }).check()
    await this.submitButton.click()
  }
}

/** Страница заявки клиента (/client/applications/$id). */
export class ClientApplicationPage {
  constructor(readonly page: Page) {}

  async goto(id: string) {
    await this.page.goto(`/client/applications/${id}`)
  }

  get id() {
    const match = /\/client\/applications\/([0-9a-f-]{36})/.exec(this.page.url())
    if (!match?.[1]) throw new Error(`Не страница заявки: ${this.page.url()}`)
    return match[1]
  }

  /** Бейдж статуса под заголовком: ждём смены без перезагрузки — экран опрашивает API. */
  async expectStatus(label: string, timeout = 20_000) {
    await expect(this.page.getByRole('main').getByText(label, { exact: true }).first()).toBeVisible(
      {
        timeout,
      },
    )
  }

  async acceptOffer() {
    await this.page.getByRole('button', { name: 'Принять предложение' }).click()
    const dialog = this.page.getByRole('dialog', { name: 'Принять предложение банка?' })
    await dialog.getByRole('button', { name: 'Да, принять' }).click()
  }

  async declineOffer() {
    await this.page.getByRole('button', { name: 'Отказаться' }).click()
    const dialog = this.page.getByRole('dialog', { name: 'Отказаться от предложения?' })
    await dialog.getByRole('button', { name: 'Да, отказаться' }).click()
  }

  async answer(text: string) {
    await this.page.getByLabel('Ваш ответ').fill(text)
    await this.page.getByRole('button', { name: 'Отправить ответ' }).click()
  }

  /** Подписание демо-кодом: код показывается баннером вместо SMS (DEMO_AUTH_ENABLED). */
  async sign() {
    await this.page.getByRole('checkbox', { name: /согласен\(на\) с условиями/ }).check()
    await this.page.getByRole('button', { name: 'Получить код' }).click()
    const banner = this.page.getByText(/Демо: вместо SMS — код \d{6}/)
    await expect(banner).toBeVisible()
    const code = /(\d{6})/.exec((await banner.textContent()) ?? '')?.[1]
    if (!code) throw new Error('Демо-код не найден')
    await this.page.getByLabel('Код подтверждения').fill(code)
    await this.page.getByRole('button', { name: 'Подписать договор' }).click()
  }

  scheduleTable(): Locator {
    return this.page.getByRole('table').filter({ hasText: 'Основной долг' })
  }
}
