import { setupWorker } from 'msw/browser'
import { resetDb, restoreDb, snapshotDb } from './db.ts'
import { handlers } from './handlers.ts'
import { initScenario } from './scenarios.ts'

const DB_STORAGE_KEY = 'creditflow.mock-db'

/**
 * База моков живёт в sessionStorage вкладки: перезагрузка на любом шаге не теряет заявку.
 * `?mock=…` в адресе начинает демо с чистой базы.
 */
function loadDb(location: Pick<Location, 'search'>) {
  const saved = sessionStorage.getItem(DB_STORAGE_KEY)
  if (new URLSearchParams(location.search).has('mock') || !saved) return resetDb()
  try {
    restoreDb(saved)
  } catch {
    resetDb()
  }
}

/** Запускает моки в браузере. Импортируется только динамически под VITE_API_MOCKS=1. */
export async function startMocks() {
  const scenario = initScenario(window.location)
  loadDb(window.location)
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
