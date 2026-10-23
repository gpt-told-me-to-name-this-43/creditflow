import createClient, { type Middleware } from 'openapi-fetch'
import { auth } from '@/lib/auth.ts'
import { ApiError, NETWORK_ERROR } from './errors.ts'
import type { paths } from './schema.d.ts'

const withToken: Middleware = {
  onRequest({ request }) {
    const session = auth.getSession()
    if (session) request.headers.set('Authorization', `Bearer ${session.token}`)
    return request
  },
}

// Пути в контракте уже начинаются с /api/v1, origin тот же (nginx или прокси vite).
export const api = createClient<paths>({
  baseUrl: globalThis.location?.origin ?? '',
  // fetch берётся в момент запроса, а не при создании клиента: так его подменяют MSW и тесты
  fetch: (request) => globalThis.fetch(request),
})
api.use(withToken)

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
