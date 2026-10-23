import { api, unwrap } from '@/api/client.ts'
import { auth } from '@/lib/auth.ts'
import { bindCompany, db, DEMO_PASSWORD } from '@/mocks/db.ts'

/** Демо-учётка по короткому логину: `director.bakery` → `director.bakery@creditflow.demo`. */
export function demoUser(login: string) {
  const user = db.findUserByEmail(`${login}@creditflow.demo`)
  if (!user) throw new Error(`Нет демо-учётки ${login}`)
  return user
}

/** Вход через моки: токен и роль в sessionStorage, как после экрана входа. */
export async function signInAs(login: string) {
  const user = demoUser(login)
  const { access_token } = await unwrap(
    api.POST('/api/v1/auth/login', { body: { login: user.email, password: DEMO_PASSWORD } }),
  )
  auth.setSession({ token: access_token, role: user.role })
  return user
}

/** Вход и привязка своей компании из реестра — клиент готов подавать заявки. */
export async function signInWithCompany(login: string, inn: string) {
  const user = await signInAs(login)
  const result = bindCompany(user.id, inn)
  if (!result.ok) throw new Error(`Привязка ${inn}: ${result.code}`)
  return user
}
