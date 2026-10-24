import { api, unwrap } from '@/api/client.ts'
import { auth } from '@/lib/auth.ts'
import {
  applyDecision,
  bindCompany,
  db,
  type Decision,
  DEMO_PASSWORD,
  submitApplication,
} from '@/mocks/db.ts'

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

/**
 * Отправленная заявка клиента C1 («ТехСервис», 2 000 000 ₽ на 36 мес.) в нужном состоянии:
 * `decision` — решение менеджера после отправки.
 */
export async function submittedApplication(decision?: Decision) {
  const client = await signInWithCompany('director.techservice', '0099010012')
  const application = Object.assign(db.createApplication(client), {
    purpose_code: 'EQUIPMENT',
    requested_amount_rub: '2000000.00',
    term_months: 36,
    product_id: 'investment',
    terms_field_sources: {
      purpose_code: 'LLM',
      requested_amount_rub: 'RULES',
      term_months: 'RULES',
    },
  } as const)
  submitApplication(application)
  if (decision) applyDecision(application, decision)
  return application
}
