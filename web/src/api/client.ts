import createClient from 'openapi-fetch'
import type { Middleware } from 'openapi-fetch'
import type { paths } from './schema'

/** paths уже содержат /api/v1: baseUrl — origin, без повторного префикса. */
export function createApiClient(
  baseUrl = '',
  getToken = () => sessionStorage.getItem('access_token'),
) {
  const client = createClient<paths>({ baseUrl })
  const auth: Middleware = {
    onRequest({ request }) {
      const token = getToken()
      if (token) request.headers.set('Authorization', `Bearer ${token}`)
      return request
    },
  }
  client.use(auth)
  return client
}

/** Создать на действие и сохранить до его завершения; сетевой повтор использует тот же ключ. */
export function newIdempotencyKey(): string {
  return crypto.randomUUID()
}
