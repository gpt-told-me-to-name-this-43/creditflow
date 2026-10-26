import { setupWorker } from 'msw/browser'
import { resetDb, restoreDb, seedManagerQueue, snapshotDb } from './db.ts'
import { handlers } from './handlers.ts'
import { initScenario, type Scenario } from './scenarios.ts'

const DB_STORAGE_KEY = 'creditflow.mock-db'

/**
 * База моков живёт в sessionStorage вкладки: перезагрузка на любом шаге не теряет заявку.
 * `?mock=…` в адресе начинает демо с чистой базы.
 */
function loadDb(location: Pick<Location, 'search'>, scenario: Scenario) {
  const saved = sessionStorage.getItem(DB_STORAGE_KEY)
  if (new URLSearchParams(location.search).has('mock') || !saved) {
    resetDb()
    // Демо кабинета менеджера начинается с очереди заявок C1–C7.
    if (scenario === 'manager') seedManagerQueue()
    return
  }
  try {
    restoreDb(saved)
  } catch {
    resetDb()
  }
}

/** Запускает моки в браузере. Импортируется только динамически под VITE_API_MOCKS=1. */
export async function startMocks() {
  const scenario = initScenario(window.location)
  loadDb(window.location, scenario)
  const worker = setupWorker(...handlers)
  // Сохраняем после каждого ответа моков и перед уходом со страницы (отложенные переходы).
  const save = () => sessionStorage.setItem(DB_STORAGE_KEY, snapshotDb())
  worker.events.on('response:mocked', save)
  window.addEventListener('pagehide', save)
  await worker.start({
    serviceWorker: { url: '/mockServiceWorker.js' },
    // Статика, шрифты и HMR идут мимо моков без предупреждений, неизвестный /api — в консоль.
    onUnhandledRequest: (request, print) => {
      if (new URL(request.url).pathname.startsWith('/api/')) print.warning()
    },
  })
  console.info(`[mocks] API на моках, сценарий: ${scenario}`)
}
