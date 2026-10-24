import createClient, { type Middleware } from 'openapi-fetch'
import { auth } from '@/lib/auth.ts'
import { ApiError, NETWORK_ERROR, StaleSessionError } from './errors.ts'
import type { paths } from './schema.d.ts'

export { newIdempotencyKey } from '@/lib/idempotency.ts'

// Пути в контракте уже начинаются с /api/v1: baseUrl — origin без префикса API.
export function createApiClient(
  baseUrl = globalThis.location?.origin ?? '',
  getToken: () => string | null | undefined = () => auth.getSession()?.token,
) {
  const client = createClient<paths>({
    baseUrl,
    // fetch читается при запросе: MSW и тесты могут подменить его после создания клиента.
    fetch: (request) => globalThis.fetch(request),
  })
  // Поколение сессии на момент отправки — по id запроса openapi-fetch.
  const startedIn = new Map<string, number>()
  // Поколение, в котором ушёл запрос; метка снимается при ответе или сбое.
  const settle = (id: string) => {
    const generation = startedIn.get(id)
    startedIn.delete(id)
    return generation
  }
  const withToken: Middleware = {
    onRequest({ request, id }) {
      startedIn.set(id, auth.generation())
      const token = getToken()
      if (token) request.headers.set('Authorization', `Bearer ${token}`)
      return request
    },
    onResponse({ id, response }) {
      const generation = settle(id)
      if (generation !== auth.generation()) throw new StaleSessionError()
      // Тело openapi-fetch дочитает уже после onResponse: окончательная проверка — в unwrap.
      if (generation !== undefined) responseGeneration.set(response, generation)
      return undefined
    },
    onError({ id, error }) {
      // Сбой сети запроса прошлой сессии — тоже не для нового пользователя (без тоста).
      if (settle(id) !== auth.generation()) return new StaleSessionError()
      return error instanceof Error ? error : new Error(String(error))
    },
  }
  client.use(withToken)
  return client
}

export const api = createApiClient()

// Поколение сессии, в котором отправлен запрос, — по объекту ответа.
const responseGeneration = new WeakMap<Response, number>()

type FetchResult = { data?: unknown; error?: unknown; response: Response }

/** Данные успешного ответа или ApiError: в queryFn и mutationFn ошибки только бросаются. */
export async function unwrap<R extends FetchResult>(
  request: Promise<R>,
): Promise<NonNullable<R['data']>> {
  // onRequest openapi-fetch вызывает синхронно внутри api.X(): это поколение старта запроса.
  // Своя переменная на каждый вызов — параллельные запросы не делят метку.
  const startedIn = auth.generation()
  let result: R
  try {
    result = await request
  } catch (cause) {
    if (cause instanceof StaleSessionError) throw cause
    // Тело оборвалось уже после onResponse (onError openapi-fetch тут не вызывает).
    if (startedIn !== auth.generation()) throw new StaleSessionError()
    throw new ApiError(0, NETWORK_ERROR, cause instanceof Error ? cause.message : 'Network error')
  }
  // Здесь тело уже прочитано: пока оно шло, пользователь мог смениться.
  const generation = responseGeneration.get(result.response)
  if (generation !== undefined && generation !== auth.generation()) throw new StaleSessionError()
  if (!result.response.ok) throw ApiError.fromBody(result.response.status, result.error)
  return result.data as NonNullable<R['data']>
}
