import { afterEach, describe, expect, it, vi } from 'vitest'
import { auth } from '@/lib/auth.ts'
import { api, unwrap } from './client.ts'
import { ApiError, errorMessage, NETWORK_ERROR } from './errors.ts'

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

afterEach(() => vi.unstubAllGlobals())

describe('api client', () => {
  it('отдаёт данные и добавляет токен сессии', async () => {
    auth.setSession({ token: 'secret', role: 'CLIENT' })
    const fetch = vi.fn<(request: Request) => Promise<Response>>(async () =>
      json(200, { status: 'ok', db: 'ok', ext_sim: 'ok', llm: 'replay' }),
    )
    vi.stubGlobal('fetch', fetch)
    const data = await unwrap(api.GET('/api/v1/health'))
    expect(data.status).toBe('ok')
    expect(fetch.mock.calls[0]?.[0].headers.get('Authorization')).toBe('Bearer secret')
  })

  it('конверт ошибки превращается в ApiError с кодом', async () => {
    vi.stubGlobal('fetch', async () =>
      json(409, { error: { code: 'REVISION_CONFLICT', message: 'stale' } }),
    )
    const error = await unwrap(api.GET('/api/v1/health')).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 409, code: 'REVISION_CONFLICT' })
  })

  it('ответ без конверта — код по HTTP-статусу', async () => {
    vi.stubGlobal('fetch', async () => new Response('Bad gateway', { status: 502 }))
    const error = await unwrap(api.GET('/api/v1/health')).catch((e: unknown) => e)
    expect(error).toMatchObject({ status: 502, code: 'HTTP_502' })
  })

  it('сбой сети — NETWORK_ERROR', async () => {
    vi.stubGlobal('fetch', async () => {
      throw new TypeError('Failed to fetch')
    })
    const error = await unwrap(api.GET('/api/v1/health')).catch((e: unknown) => e)
    expect(error).toMatchObject({ status: 0, code: NETWORK_ERROR })
  })
})

describe('errorMessage', () => {
  it('текст берётся по коду, а не из message бэка', () => {
    expect(errorMessage(new ApiError(422, 'INVALID_INN', 'inn bad'))).toBe(
      'Проверьте ИНН: 10 цифр для организации или 12 для ИП',
    )
  })

  it('неизвестный код и не-ApiError — общий текст', () => {
    expect(errorMessage(new ApiError(500, 'HTTP_500', 'boom'))).toBe(
      'Что-то пошло не так. Повторите ещё раз',
    )
    expect(errorMessage(new Error('x'))).toBe('Что-то пошло не так. Повторите ещё раз')
  })
})
