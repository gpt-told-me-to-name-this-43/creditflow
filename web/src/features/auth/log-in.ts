import { api, unwrap } from '@/api/client.ts'
import type { components } from '@/api/schema.d.ts'
import type { Session } from '@/lib/auth.ts'

type LoginRequest = components['schemas']['LoginRequest']

/**
 * Вход: токен из POST /auth/login, роль из GET /auth/me с этим токеном.
 * Сессию сохраняет вызывающий (signIn) — только когда известны оба поля.
 */
export async function logIn(credentials: LoginRequest): Promise<Session> {
  const { access_token: token } = await unwrap(
    api.POST('/api/v1/auth/login', { body: credentials }),
  )
  const me = await unwrap(
    api.GET('/api/v1/auth/me', { headers: { Authorization: `Bearer ${token}` } }),
  )
  return { token, role: me.role }
}
