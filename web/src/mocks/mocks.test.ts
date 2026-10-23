import { http } from 'msw'
import { describe, expect, it } from 'vitest'
import { api, unwrap } from '@/api/client.ts'
import { server } from '@/test/server.ts'
import { apiError } from './handlers.ts'
import { getScenario, initScenario, setScenario } from './scenarios.ts'

describe('сценарии моков', () => {
  it('берётся из ?mock= и переживает переход без параметра', () => {
    expect(initScenario({ search: '?mock=need_info' })).toBe('need_info')
    expect(initScenario({ search: '' })).toBe('need_info')
  })

  it('неизвестное значение не меняет сценарий', () => {
    setScenario('offer')
    expect(initScenario({ search: '?mock=nope' })).toBe('offer')
  })

  it('каждый тест начинается с обычного поведения', () => {
    expect(getScenario()).toBe('default')
    expect(initScenario({ search: '' })).toBe('default')
  })
})

describe('обработчики', () => {
  it('health отвечает по контракту', async () => {
    const data = await unwrap(api.GET('/api/v1/health'))
    expect(data).toEqual({ status: 'ok', db: 'ok', ext_sim: 'ok', llm: 'replay' })
  })

  it('сценарий unavailable отключает ИИ', async () => {
    setScenario('unavailable')
    const data = await unwrap(api.GET('/api/v1/health'))
    expect(data.llm).toBe('disabled')
  })

  it('apiError отдаёт конверт ошибки, который понимает клиент', async () => {
    server.use(http.get('/api/v1/health', () => apiError(503, 'PROVIDER_UNAVAILABLE')))
    const error = await unwrap(api.GET('/api/v1/health')).catch((e: unknown) => e)
    expect(error).toMatchObject({ status: 503, code: 'PROVIDER_UNAVAILABLE' })
  })
})
