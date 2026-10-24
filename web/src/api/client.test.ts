import { afterEach, describe, expect, it, vi } from 'vitest'
import { auth } from '@/lib/auth.ts'
import { api, unwrap } from './client.ts'
import { ApiError, errorMessage, NETWORK_ERROR, StaleSessionError } from './errors.ts'

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

afterEach(() => vi.unstubAllGlobals())

function deferred() {
  let resolve: () => void = () => {}
  const promise = new Promise<void>((done) => (resolve = done))
  return { promise, resolve }
}

/**
 * Ответ, у которого заголовки уже пришли, а тело — по команде теста. `reading` выполняется,
 * когда клиент начал читать тело, то есть onResponse уже отработал.
 */
function heldBody() {
  const reading = deferred()
  let controller: ReadableStreamDefaultController<Uint8Array> | undefined
  const stream = new ReadableStream<Uint8Array>(
    {
      start: (c) => void (controller = c),
      pull: () => reading.resolve(),
    },
    // Без буфера: pull вызывается только при чтении, а не сразу при создании потока.
    { highWaterMark: 0 },
  )
  return {
    response: new Response(stream, { headers: { 'Content-Type': 'application/json' } }),
    reading: reading.promise,
    finish(body: unknown) {
      controller?.enqueue(new TextEncoder().encode(JSON.stringify(body)))
      controller?.close()
    },
    fail: () => controller?.error(new TypeError('terminated')),
  }
}

const switchUser = () => {
  auth.clear()
  auth.setSession({ token: 'second', role: 'CLIENT' })
}

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

  it('ответ, пришедший после выхода и входа другим пользователем, отбрасывается', async () => {
    auth.setSession({ token: 'first', role: 'CLIENT' })
    let respond: ((response: Response) => void) | undefined
    vi.stubGlobal('fetch', () => new Promise<Response>((resolve) => (respond = resolve)))
    const late = unwrap(api.GET('/api/v1/health')).catch((e: unknown) => e)
    await vi.waitFor(() => expect(respond).toBeDefined())
    auth.clear()
    auth.setSession({ token: 'second', role: 'CLIENT' })
    respond?.(json(200, { status: 'ok', db: 'ok', ext_sim: 'ok', llm: 'replay' }))
    expect(await late).toBeInstanceOf(StaleSessionError)
  })

  it('тело дочитывается уже после смены пользователя — результат отбрасывается', async () => {
    auth.setSession({ token: 'first', role: 'CLIENT' })
    const held = heldBody()
    vi.stubGlobal('fetch', async () => held.response)
    const late = unwrap(api.GET('/api/v1/health')).catch((e: unknown) => e)
    await held.reading
    switchUser()
    held.finish({ status: 'ok' })
    expect(await late).toBeInstanceOf(StaleSessionError)
  })

  it('заголовки пришли, сессия сменилась, тело оборвалось — StaleSessionError', async () => {
    auth.setSession({ token: 'first', role: 'CLIENT' })
    const held = heldBody()
    vi.stubGlobal('fetch', async () => held.response)
    const late = unwrap(api.GET('/api/v1/health')).catch((e: unknown) => e)
    await held.reading
    switchUser()
    held.fail()
    expect(await late).toBeInstanceOf(StaleSessionError)
  })

  it('тело оборвалось без смены сессии — NETWORK_ERROR', async () => {
    auth.setSession({ token: 'first', role: 'CLIENT' })
    const held = heldBody()
    vi.stubGlobal('fetch', async () => held.response)
    const late = unwrap(api.GET('/api/v1/health')).catch((e: unknown) => e)
    await held.reading
    held.fail()
    expect(await late).toMatchObject({ status: 0, code: NETWORK_ERROR })
  })

  it('параллельные запросы разных сессий не смешивают метки', async () => {
    auth.setSession({ token: 'first', role: 'CLIENT' })
    const byToken = { first: heldBody(), second: heldBody() }
    vi.stubGlobal('fetch', async (request: Request) =>
      request.headers.get('Authorization') === 'Bearer first'
        ? byToken.first.response
        : byToken.second.response,
    )
    const old = unwrap(api.GET('/api/v1/health')).catch((e: unknown) => e)
    await byToken.first.reading
    switchUser()
    const current = unwrap(api.GET('/api/v1/health')).catch((e: unknown) => e)
    await byToken.second.reading
    // Сначала дочитывается тело нового запроса, потом старого — и наоборот для сбоя ниже.
    byToken.second.finish({ status: 'ok' })
    byToken.first.finish({ status: 'ok' })
    expect(await current).toEqual({ status: 'ok' })
    expect(await old).toBeInstanceOf(StaleSessionError)

    const failing = heldBody()
    vi.stubGlobal('fetch', async () => failing.response)
    const broken = unwrap(api.GET('/api/v1/health')).catch((e: unknown) => e)
    await failing.reading
    failing.fail()
    expect(await broken).toMatchObject({ code: NETWORK_ERROR })
  })

  it('сбой сети запроса прошлой сессии — StaleSessionError, а не NETWORK_ERROR', async () => {
    auth.setSession({ token: 'first', role: 'CLIENT' })
    let fail: ((error: Error) => void) | undefined
    vi.stubGlobal('fetch', () => new Promise<Response>((_, reject) => (fail = reject)))
    const late = unwrap(api.GET('/api/v1/health')).catch((e: unknown) => e)
    await vi.waitFor(() => expect(fail).toBeDefined())
    auth.clear()
    auth.setSession({ token: 'second', role: 'CLIENT' })
    fail?.(new TypeError('Failed to fetch'))
    expect(await late).toBeInstanceOf(StaleSessionError)
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
