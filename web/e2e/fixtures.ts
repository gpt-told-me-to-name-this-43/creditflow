import { type Browser, type BrowserContext, test as base, type Page } from '@playwright/test'
import { login, resetDb } from './support/api.ts'
import { SESSION_KEY } from './support/env.ts'

type OpenAs = (loginName: string) => Promise<Page>

interface Fixtures {
  /** Единственный путь к reset в спеках: `resetDb('clean')` перед s1–s11, `'demo'` в s12. */
  resetDb: typeof resetDb
  /** Клиент в отдельном browser context; вход через API, сессия — как после экрана входа. */
  clientPage: OpenAs
  /** Менеджер в отдельном browser context: два менеджера — две независимые сессии. */
  managerPage: OpenAs
}

async function openAs(
  browser: Browser,
  options: Parameters<Browser['newContext']>[0],
  contexts: BrowserContext[],
  loginName: string,
  role: 'CLIENT' | 'MANAGER',
) {
  const session = await login(loginName)
  if (session.role !== role)
    throw new Error(`${loginName}: роль ${session.role}, ожидалась ${role}`)
  const context = await browser.newContext(options)
  contexts.push(context)
  // Только если вкладка ещё без сессии: «Выйти» внутри теста не должно её возвращать.
  await context.addInitScript(
    ([key, value]) => {
      if (!sessionStorage.getItem(key)) sessionStorage.setItem(key, value)
    },
    [SESSION_KEY, JSON.stringify(session)] as const,
  )
  return context.newPage()
}

export const test = base.extend<Fixtures>({
  resetDb: async ({}, use) => {
    await use(resetDb)
  },
  clientPage: async ({ browser, baseURL, viewport, locale, timezoneId }, use) => {
    const contexts: BrowserContext[] = []
    const options = { baseURL, viewport, locale, timezoneId }
    await use((loginName) => openAs(browser, options, contexts, loginName, 'CLIENT'))
    await Promise.all(contexts.map((context) => context.close()))
  },
  managerPage: async ({ browser, baseURL, viewport, locale, timezoneId }, use) => {
    const contexts: BrowserContext[] = []
    const options = { baseURL, viewport, locale, timezoneId }
    await use((loginName) => openAs(browser, options, contexts, loginName, 'MANAGER'))
    await Promise.all(contexts.map((context) => context.close()))
  },
})

export { expect } from '@playwright/test'
