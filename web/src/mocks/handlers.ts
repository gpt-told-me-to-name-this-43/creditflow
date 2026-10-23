import { http, HttpResponse } from 'msw'
import type { ErrorCode } from '@/api/contract-draft.ts'
import type { components } from '@/api/schema.d.ts'
import { getScenario } from './scenarios.ts'

/*
 * Обработчики повторяют docs/openapi.json, типы тел — только из schema.d.ts.
 * Пока в контракте один /health: остальные эндпоинты (auth, onboarding, заявки, менеджер)
 * добавляются после contract-v1 (#6) вместе с in-memory db.
 */

type HealthResponse = components['schemas']['HealthResponse']

/** Ошибка в конверте `{error: {code, message}}` из docs/api.md. */
export function apiError(status: number, code: ErrorCode, message: string = code) {
  return HttpResponse.json({ error: { code, message } }, { status })
}

function health(): HealthResponse {
  switch (getScenario()) {
    case 'unavailable':
      return { status: 'degraded', db: 'ok', ext_sim: 'ok', llm: 'disabled' }
    case 'error503':
      return { status: 'degraded', db: 'ok', ext_sim: 'unavailable', llm: 'replay' }
    default:
      return { status: 'ok', db: 'ok', ext_sim: 'ok', llm: 'replay' }
  }
}

export const handlers = [http.get('/api/v1/health', () => HttpResponse.json(health()))]
