import { request } from '@playwright/test'
import { API, baseURL, RESET_HEADER } from './support/env.ts'

const HEALTH_TIMEOUT_MS = 120_000
const MIN_TOKEN_BYTES = 32

/**
 * Перед прогоном: токен reset задан, стек отвечает, reset принимает токен.
 * Без токена прогон падает здесь с понятной ошибкой, а не случайными 404 в спеках.
 */
export default async function globalSetup() {
  const token = process.env.TEST_RESET_TOKEN
  if (!token) {
    throw new Error(
      'TEST_RESET_TOKEN не задан. E2E сбрасывают БД через POST /_test/reset — ' +
        'запустите стек `make e2e-up` и передайте тот же токен: `make e2e TEST_RESET_TOKEN=…` (или в .env).',
    )
  }

  // Короче — api отвечает на reset 404, как на несуществующий маршрут (app/api/test_reset.py).
  if (new TextEncoder().encode(token).length < MIN_TOKEN_BYTES) {
    throw new Error(
      `TEST_RESET_TOKEN короче ${MIN_TOKEN_BYTES} байт — api его не примет. ` +
        'Сгенерируйте, например: openssl rand -hex 32',
    )
  }

  const api = await request.newContext({ baseURL: baseURL() })
  try {
    const deadline = Date.now() + HEALTH_TIMEOUT_MS
    let last = 'нет ответа'
    for (;;) {
      try {
        const health = await api.get(`${API}/health`)
        const body = (await health.json()) as { status?: string; llm?: string }
        if (health.ok() && body.status === 'ok') {
          if (body.llm !== 'replay') {
            throw new Error(`E2E ждут LLM_MODE=replay, а health.llm = ${String(body.llm)}`)
          }
          break
        }
        last = `${health.status()} ${JSON.stringify(body)}`
      } catch (error) {
        if (error instanceof Error && error.message.startsWith('E2E ждут')) throw error
        last = String(error)
      }
      if (Date.now() > deadline) throw new Error(`Стек не готов за 2 минуты: ${last}`)
      await new Promise((resolve) => setTimeout(resolve, 2000))
    }

    const reset = await api.post(`${API}/_test/reset?mode=clean`, {
      headers: { [RESET_HEADER]: token },
    })
    if (reset.status() !== 200) {
      throw new Error(
        `POST /_test/reset ответил ${reset.status()}: токен не совпадает со стеком ` +
          'или стек поднят без docker-compose.e2e.yml (TEST_RESET_ENABLED=false).',
      )
    }
  } finally {
    await api.dispose()
  }
}
