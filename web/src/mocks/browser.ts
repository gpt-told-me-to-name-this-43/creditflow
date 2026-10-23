import { setupWorker } from 'msw/browser'
import { handlers } from './handlers.ts'
import { initScenario } from './scenarios.ts'

/** Запускает моки в браузере. Импортируется только динамически под VITE_API_MOCKS=1. */
export async function startMocks() {
  const scenario = initScenario(window.location)
  await setupWorker(...handlers).start({
    serviceWorker: { url: '/mockServiceWorker.js' },
    // Статика, шрифты и HMR идут мимо моков без предупреждений, неизвестный /api — в консоль.
    onUnhandledRequest: (request, print) => {
      if (new URL(request.url).pathname.startsWith('/api/')) print.warning()
    },
  })
  console.info(`[mocks] API на моках, сценарий: ${scenario}`)
}
