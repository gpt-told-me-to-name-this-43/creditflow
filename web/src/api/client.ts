import createClient, { type Middleware } from 'openapi-fetch'
import { auth } from '@/lib/auth.ts'
import { ApiError, NETWORK_ERROR } from './errors.ts'
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
  const withToken: Middleware = {
    onRequest({ request }) {
      const token = getToken()
      if (token) request.headers.set('Authorization', `Bearer ${token}`)
      return request
    },
  }
  client.use(withToken)
  return client
}

export const api = createApiClient()

type FetchResult = { data?: unknown; error?: unknown; response: Response }

/** Данные успешного ответа или ApiError: в queryFn и mutationFn ошибки только бросаются. */
export async function unwrap<R extends FetchResult>(
  request: Promise<R>,
): Promise<NonNullable<R['data']>> {
  let result: R
  try {
    result = await request
  } catch (cause) {
    throw new ApiError(0, NETWORK_ERROR, cause instanceof Error ? cause.message : 'Network error')
  }
  if (!result.response.ok) throw ApiError.fromBody(result.response.status, result.error)
  return result.data as NonNullable<R['data']>
}
