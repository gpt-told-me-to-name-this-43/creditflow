import { type APIRequestContext, expect, request } from '@playwright/test'
import type { Company } from './companies.ts'
import { API, baseURL, DEMO_PASSWORD, RESET_HEADER } from './env.ts'

export interface Session {
  token: string
  role: 'CLIENT' | 'MANAGER'
}

interface ApplicationRef {
  id: string
  revision: number
  status: string
}

/** Сброс БД — единственный путь к reset в E2E: `clean` перед s1–s11, `demo` — в s12. */
export async function resetDb(mode: 'clean' | 'demo') {
  const api = await request.newContext({ baseURL: baseURL() })
  try {
    const response = await api.post(`${API}/_test/reset?mode=${mode}`, {
      headers: { [RESET_HEADER]: process.env.TEST_RESET_TOKEN ?? '' },
      timeout: 60_000,
    })
    expect(response.status(), `reset ${mode}`).toBe(200)
  } finally {
    await api.dispose()
  }
}

/** Вход через API: так же, как экран входа, — POST /auth/login и роль из /auth/me. */
export async function login(login: string): Promise<Session> {
  const api = await request.newContext({ baseURL: baseURL() })
  try {
    const response = await api.post(`${API}/auth/login`, {
      data: { login: `${login}@creditflow.demo`, password: DEMO_PASSWORD },
    })
    expect(response.status(), `login ${login}`).toBe(200)
    const { access_token: token } = (await response.json()) as { access_token: string }
    const me = await api.get(`${API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
    const { role } = (await me.json()) as { role: Session['role'] }
    return { token, role }
  } finally {
    await api.dispose()
  }
}

/**
 * Клиент через API — для подготовки состояния, когда шаг не предмет спеки.
 * Сам путь клиента в браузере проверяют s1, s8 и s9.
 */
export class ClientApi {
  private constructor(
    private readonly api: APIRequestContext,
    readonly session: Session,
  ) {}

  static async as(loginName: string) {
    const session = await login(loginName)
    const api = await request.newContext({
      baseURL: baseURL(),
      extraHTTPHeaders: { Authorization: `Bearer ${session.token}` },
    })
    return new ClientApi(api, session)
  }

  async dispose() {
    await this.api.dispose()
  }

  async bind(inn: string) {
    const response = await this.api.post(`${API}/onboarding/company-binding`, {
      data: { inn, pd_consent_version: 'pd-v1' },
    })
    expect(response.status(), 'company-binding').toBe(200)
  }

  /** Привязка, черновик с условиями компании и Submit — заявка уходит менеджеру. */
  async submitted(company: Company): Promise<ApplicationRef> {
    await this.bind(company.inn)
    const created = await this.api.post(`${API}/applications`, { data: {} })
    expect([200, 201], 'create application').toContain(created.status())
    let app = (await created.json()) as ApplicationRef
    const patched = await this.api.patch(`${API}/applications/${app.id}`, {
      data: {
        revision: app.revision,
        purpose_code: company.request.purpose,
        requested_amount_rub: company.request.amount,
        term_months: company.request.term,
        product_id: company.request.product,
      },
    })
    expect(patched.status(), 'patch application').toBe(200)
    app = (await patched.json()) as ApplicationRef
    const submitted = await this.api.post(`${API}/applications/${app.id}/submit`, {
      headers: { 'Idempotency-Key': crypto.randomUUID() },
      data: { revision: app.revision, bki_consent_version: 'bki-v1' },
    })
    expect(submitted.status(), 'submit').toBe(200)
    return (await submitted.json()) as ApplicationRef
  }

  async application(id: string) {
    const response = await this.api.get(`${API}/applications/${id}`)
    expect(response.status()).toBe(200)
    return (await response.json()) as ApplicationRef & Record<string, unknown>
  }

  async contract(id: string) {
    const response = await this.api.get(`${API}/applications/${id}/contract`)
    expect(response.status()).toBe(200)
    return (await response.json()) as {
      amount_rub: string
      overpayment_rub: string
      schedule: { principal_rub: string; interest_rub: string; payment_rub: string }[]
    }
  }
}

/** Менеджер через API — только для проверок по БД-видимым данным (сводка, счётчики). */
export class ManagerApi {
  private constructor(private readonly api: APIRequestContext) {}

  static async as(loginName: string) {
    const session = await login(loginName)
    const api = await request.newContext({
      baseURL: baseURL(),
      extraHTTPHeaders: { Authorization: `Bearer ${session.token}` },
    })
    return new ManagerApi(api)
  }

  async dispose() {
    await this.api.dispose()
  }

  async application(id: string) {
    const response = await this.api.get(`${API}/manager/applications/${id}`)
    expect(response.status()).toBe(200)
    return (await response.json()) as {
      status: string
      revision: number
      decisions: unknown[]
      info_requests: { question_text: string; answer_text: string | null }[]
    }
  }

  async queue(status: string) {
    const response = await this.api.get(`${API}/manager/applications?status=${status}`)
    expect(response.status()).toBe(200)
    return (await response.json()) as { company_name: string }[]
  }
}
