import { z } from 'zod'

/*
 * Сценарий моков выбирается параметром `?mock=…` в адресе и живёт до конца вкладки:
 * после переходов внутри кабинета параметр из URL пропадает, а сценарий остаётся.
 * `?mock=default` возвращает обычное поведение: решение по ветке демо-учётки (C1–C7).
 * `?mock=manager` — заявка ждёт решения в кабинете менеджера.
 */
export const scenarioSchema = z.enum([
  'default',
  'manager',
  'approve',
  'offer',
  'offer_term',
  'need_info',
  'stop',
  'unavailable',
  'error503',
])
export type Scenario = z.infer<typeof scenarioSchema>

const STORAGE_KEY = 'creditflow.mock'

let current: Scenario = 'default'

/** Читает сценарий из `?mock=` или из прошлого запуска вкладки. Вызывается при старте воркера. */
export function initScenario(location: Pick<Location, 'search'>) {
  const fromUrl = scenarioSchema.safeParse(new URLSearchParams(location.search).get('mock'))
  if (fromUrl.success) {
    setScenario(fromUrl.data)
    return current
  }
  const stored = scenarioSchema.safeParse(sessionStorage.getItem(STORAGE_KEY))
  current = stored.success ? stored.data : 'default'
  return current
}

export function getScenario() {
  return current
}

export function setScenario(scenario: Scenario) {
  current = scenario
  sessionStorage.setItem(STORAGE_KEY, scenario)
}

/** Для тестов: каждый тест начинает с обычного поведения. */
export function resetScenario() {
  current = 'default'
  sessionStorage.removeItem(STORAGE_KEY)
}
