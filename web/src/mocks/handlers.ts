import { http, HttpResponse } from 'msw'
import type { ErrorCode, PurposeCode } from '@/api/enums.ts'
import { CLIENT_REASON_CODES, PURPOSE_CODES } from '@/api/enums.ts'
import type { components } from '@/api/schema.d.ts'
import {
  acceptOffer,
  answerInfoRequest,
  type ApplicationRow,
  applyDecision,
  BKI_CONSENT_VERSION,
  bindCompany,
  CHALLENGE_LIMIT,
  CHALLENGE_WINDOW_MS,
  db,
  DEMO_PASSWORD,
  type Decision,
  PD_CONSENT_VERSION,
  providerDown,
  requestedTerms,
  setStatus,
  signApplication,
  submitApplication,
  touch,
  type UserRow,
} from './db.ts'
import { isValidInn } from '@/lib/inn.ts'
import { interpret } from './interpret.ts'
import { getScenario } from './scenarios.ts'
import {
  toClientView,
  toCompany,
  toContract,
  toDemoAccount,
  toMe,
  toProduct,
  unmetConstraints,
} from './views.ts'
import {
  aiReportFor,
  offerPreview,
  riskFor,
  toManagerView,
  toQueueItem,
  toStats,
} from './manager-views.ts'

/*
 * Обработчики повторяют docs/openapi.json (контракт #6), тела — только типы schema.d.ts.
 * Проверки и коды ошибок — как описаны в docs/api.md: роль, привязка компании, владелец,
 * статус, revision, Idempotency-Key. Менеджер: очередь, карточка, сводка, решения,
 * предпросмотр оффера, AI-заключение и оценки к нему (#10).
 */

type Schemas = components['schemas']
type Details = NonNullable<Schemas['ErrorBody']['details']>

const API = '/api/v1'

/** Ошибка в конверте `{error: {code, message, details?}}` из docs/api.md. */
export function apiError(
  status: number,
  code: ErrorCode,
  message: string = code,
  { details, headers }: { details?: Details; headers?: HeadersInit } = {},
) {
  const error: Schemas['ErrorBody'] = details ? { code, message, details } : { code, message }
  return HttpResponse.json({ error } satisfies Schemas['ErrorEnvelope'], { status, headers })
}

function validationError(field: string, message: string, code = 'INVALID') {
  return apiError(422, 'VALIDATION_ERROR', message, {
    details: { fields: [{ field, code, message }] },
  })
}

// Токен моков — `mock.<id пользователя>`: проверять подпись здесь нечего.
const TOKEN_PREFIX = 'mock.'

export function tokenFor(user: Pick<UserRow, 'id'>) {
  return `${TOKEN_PREFIX}${user.id}`
}

function userFrom(request: Request) {
  const header = request.headers.get('Authorization') ?? ''
  const token = header.startsWith('Bearer ') ? header.slice('Bearer '.length) : ''
  return token.startsWith(TOKEN_PREFIX) ? db.findUser(token.slice(TOKEN_PREFIX.length)) : undefined
}

/** Результат проверки: данные или готовый ответ с ошибкой. */
type Checked<T> = { ok: true; value: T } | { ok: false; response: Response }

const fail = (response: Response) => ({ ok: false, response }) as const
const pass = <T>(value: T) => ({ ok: true, value }) as const

function authorize(request: Request, role?: UserRow['role']): Checked<UserRow> {
  const user = userFrom(request)
  if (!user) {
    return fail(
      apiError(401, 'UNAUTHORIZED', 'Not authenticated', {
        headers: { 'WWW-Authenticate': 'Bearer' },
      }),
    )
  }
  if (role && user.role !== role) return fail(apiError(403, 'FORBIDDEN'))
  return pass(user)
}

/** Клиент с привязанной компанией: без неё /company и /applications* — 409 COMPANY_NOT_BOUND. */
function authorizeBoundClient(request: Request): Checked<UserRow & { company_id: string }> {
  const checked = authorize(request, 'CLIENT')
  if (!checked.ok) return checked
  const user = checked.value
  if (!user.company_id) return fail(apiError(409, 'COMPANY_NOT_BOUND'))
  return pass({ ...user, company_id: user.company_id })
}

/** Чужая или несуществующая заявка — 404, а не 403 (docs/api.md). */
function ownApplication(
  request: Request,
  applicationId: string,
): Checked<{ user: UserRow; application: ApplicationRow }> {
  const checked = authorizeBoundClient(request)
  if (!checked.ok) return checked
  const application = db.findApplication(applicationId)
  if (!application || application.company_id !== checked.value.company_id) {
    return fail(apiError(404, 'NOT_FOUND'))
  }
  // В user — исходная запись db, а не копия из authorizeBoundClient.
  const user = db.findUser(checked.value.id) as UserRow
  return pass({ user, application })
}

function conflict(application: ApplicationRow, revision: unknown) {
  if (revision === application.revision) return null
  return apiError(409, 'REVISION_CONFLICT', 'Revision is stale', {
    details: { current_revision: application.revision },
  })
}

function wrongStatus(application: ApplicationRow, ...allowed: ApplicationRow['status'][]) {
  if (allowed.includes(application.status)) return null
  return apiError(409, 'INVALID_STATUS_TRANSITION')
}

/** Тело запроса; битый JSON — пустой объект, дальше сработают проверки полей. */
async function readJson<T>(request: { clone(): { json(): Promise<T> } }): Promise<Partial<T>> {
  try {
    return ((await request.clone().json()) ?? {}) as Partial<T>
  } catch {
    return {}
  }
}

/**
 * Idempotency-Key (design.md §3.7): тот же ключ и тело — сохранённый ответ, другое тело — 422.
 * Ошибки не сохраняются: повтор после 4xx/5xx выполняется заново.
 * Ключ занимается синхронно до первого await обработчика: параллельный повтор получает
 * 409 IDEMPOTENCY_IN_PROGRESS, а не выполняет действие второй раз.
 */
async function idempotent(
  request: Request,
  user: UserRow,
  run: () => Promise<Response> | Response,
) {
  const key = request.headers.get('Idempotency-Key')
  if (!key) return validationError('header.Idempotency-Key', 'Field required', 'MISSING')
  const store = db.idempotency(user.id, key)
  const fingerprint = `${request.method} ${new URL(request.url).pathname} ${await request.clone().text()}`
  const saved = store.get()
  if (saved) {
    if (saved.fingerprint !== fingerprint) return apiError(422, 'IDEMPOTENCY_KEY_REUSED')
    if (saved.state === 'in_progress') return apiError(409, 'IDEMPOTENCY_IN_PROGRESS')
    return HttpResponse.json(saved.body as never, { status: saved.status })
  }
  store.set({ fingerprint, state: 'in_progress' })
  try {
    const response = await run()
    if (!response.ok) {
      store.release()
      return response
    }
    const body: unknown = await response.clone().json()
    store.set({ fingerprint, state: 'done', status: response.status, body })
    return response
  } catch (error) {
    store.release()
    throw error
  }
}

const view = (application: ApplicationRow, status = 200) =>
  HttpResponse.json(toClientView(application), { status })

function health(): Schemas['HealthResponse'] {
  switch (getScenario()) {
    case 'unavailable':
      return { status: 'degraded', db: 'ok', ext_sim: 'ok', llm: 'disabled' }
    case 'error503':
      return { status: 'degraded', db: 'ok', ext_sim: 'unavailable', llm: 'replay' }
    default:
      return { status: 'ok', db: 'ok', ext_sim: 'ok', llm: 'replay' }
  }
}

function consentTexts(): Schemas['ConsentText'][] {
  return [
    {
      type: 'PD_PROCESSING',
      version: PD_CONSENT_VERSION,
      text: 'Согласен на обработку персональных данных для рассмотрения заявки (демо).',
    },
    {
      type: 'BKI_REQUEST',
      version: BKI_CONSENT_VERSION,
      text: 'Согласен на запрос кредитного отчёта в БКИ для рассмотрения заявки (демо).',
    },
  ]
}

const isPurpose = (value: unknown): value is PurposeCode =>
  PURPOSE_CODES.includes(value as PurposeCode)

/** Целое положительное число из query: «3000000» → 3000000, иначе undefined/ошибка. */
function positiveInt(value: string | null): number | undefined | false {
  if (value === null || value === '') return undefined
  return /^\d+$/.test(value) && value !== '0' ? parseInt(value, 10) : false
}

type Params = { application_id: string }

const authHandlers = [
  http.get(`${API}/health`, () => HttpResponse.json(health())),

  http.get(`${API}/auth/demo-accounts`, () =>
    HttpResponse.json(db.users.map((user) => toDemoAccount(user, DEMO_PASSWORD))),
  ),

  http.post<never, Schemas['LoginRequest']>(`${API}/auth/login`, async ({ request }) => {
    const { login = '', password = '' } = await readJson(request)
    const user = db.findUserByEmail(login)
    if (!user || password !== DEMO_PASSWORD) {
      return apiError(401, 'INVALID_CREDENTIALS', 'Invalid login or password')
    }
    return HttpResponse.json({
      access_token: tokenFor(user),
      token_type: 'bearer',
      expires_in: 28800,
    } satisfies Schemas['TokenResponse'])
  }),

  http.get(`${API}/auth/me`, ({ request }) => {
    const checked = authorize(request)
    return checked.ok ? HttpResponse.json(toMe(checked.value)) : checked.response
  }),

  http.get(`${API}/consents/texts`, () => HttpResponse.json(consentTexts())),
]

const onboardingHandlers = [
  http.get(`${API}/company`, ({ request }) => {
    const checked = authorizeBoundClient(request)
    if (!checked.ok) return checked.response
    const company = db.findCompany(checked.value.company_id)
    return company ? HttpResponse.json(toCompany(company)) : apiError(409, 'COMPANY_NOT_BOUND')
  }),

  // Порядок проверок design.md §3.3: формат ИНН → версия согласия → реестр → полномочия → уникальность.
  http.post<never, Schemas['CompanyBindingRequest']>(
    `${API}/onboarding/company-binding`,
    async ({ request }) => {
      const checked = authorize(request, 'CLIENT')
      if (!checked.ok) return checked.response
      const { inn = '', pd_consent_version } = await readJson(request)
      if (!isValidInn(inn)) return apiError(422, 'INVALID_INN')
      if (pd_consent_version !== PD_CONSENT_VERSION) return apiError(422, 'CONSENT_REQUIRED')
      if (providerDown()) return apiError(503, 'PROVIDER_UNAVAILABLE', 'Registry is unavailable')
      const result = bindCompany(checked.value.id, inn)
      return result.ok
        ? HttpResponse.json(toCompany(result.company))
        : apiError(result.status, result.code)
    },
  ),

  http.get(`${API}/credit-products`, ({ request }) => {
    const checked = authorize(request, 'CLIENT')
    if (!checked.ok) return checked.response
    const query = new URL(request.url).searchParams
    const purpose = query.get('purpose')
    const amount = positiveInt(query.get('amount'))
    const term = positiveInt(query.get('term'))
    if (purpose !== null && !isPurpose(purpose)) {
      return validationError('query.purpose', 'Input should be a purpose code', 'ENUM')
    }
    if (amount === false) return validationError('query.amount', 'Must be positive', 'OUT_OF_RANGE')
    if (term === false) return validationError('query.term', 'Must be positive', 'OUT_OF_RANGE')
    const params = { purpose: purpose ?? undefined, amount, term }
    return HttpResponse.json(db.products.map((product) => toProduct(product, params)))
  }),
]

const applicationHandlers = [
  http.get(`${API}/applications`, ({ request }) => {
    const checked = authorizeBoundClient(request)
    if (!checked.ok) return checked.response
    return HttpResponse.json(db.listApplications(checked.value.company_id).map(toClientView))
  }),

  // Черновик у клиента один: повторный вызов возвращает его (200) и тело не применяет.
  http.post<never, Schemas['ApplicationCreate']>(`${API}/applications`, async ({ request }) => {
    const checked = authorizeBoundClient(request)
    if (!checked.ok) return checked.response
    const { purpose_text = null } = await readJson(request)
    if (purpose_text && purpose_text.length > 1000) {
      return validationError('body.purpose_text', 'At most 1000 characters', 'STRING_TOO_LONG')
    }
    const draft = db.findDraft(checked.value.id)
    if (draft) return view(draft)
    const user = db.findUser(checked.value.id) as UserRow
    return view(db.createApplication(user, purpose_text), 201)
  }),

  http.get<Params>(`${API}/applications/:application_id`, ({ request, params }) => {
    const checked = ownApplication(request, params.application_id)
    return checked.ok ? view(checked.value.application) : checked.response
  }),

  // PATCH: отсутствующие поля не трогаем, явный null очищает поле. terms_source считает «бэк».
  http.patch<Params, Schemas['ApplicationPatch']>(
    `${API}/applications/:application_id`,
    async ({ request, params }) => {
      const checked = ownApplication(request, params.application_id)
      if (!checked.ok) return checked.response
      const { application } = checked.value
      const body = await readJson(request)
      const rejected = conflict(application, body.revision) ?? wrongStatus(application, 'DRAFT')
      if (rejected) return rejected

      if (body.purpose_text && body.purpose_text.length > 1000) {
        return validationError('body.purpose_text', 'At most 1000 characters', 'STRING_TOO_LONG')
      }
      if (body.requested_amount_rub != null && body.requested_amount_rub <= 0) {
        return validationError('body.requested_amount_rub', 'Must be positive', 'OUT_OF_RANGE')
      }
      if (body.term_months != null && body.term_months <= 0) {
        return validationError('body.term_months', 'Must be positive', 'OUT_OF_RANGE')
      }
      if (body.product_id != null && !db.findProduct(body.product_id)) {
        return validationError('body.product_id', 'Unknown product', 'INVALID')
      }

      if (body.purpose_text !== undefined) application.purpose_text = body.purpose_text
      if (body.purpose_code !== undefined) application.purpose_code = body.purpose_code
      if (body.requested_amount_rub !== undefined) {
        application.requested_amount_rub =
          body.requested_amount_rub === null ? null : `${body.requested_amount_rub}.00`
      }
      if (body.term_months !== undefined) application.term_months = body.term_months
      if (body.product_id !== undefined) application.product_id = body.product_id
      if (body.terms_field_sources !== undefined) {
        application.terms_field_sources = { ...body.terms_field_sources }
      }
      touch(application)
      return view(application)
    },
  ),

  // Распознавание ничего не пишет и revision не требует, но только для черновика.
  http.post<Params, Schemas['InterpretRequest']>(
    `${API}/applications/:application_id/interpret`,
    async ({ request, params }) => {
      const checked = ownApplication(request, params.application_id)
      if (!checked.ok) return checked.response
      const rejected = wrongStatus(checked.value.application, 'DRAFT')
      if (rejected) return rejected
      const { purpose_text = '' } = await readJson(request)
      if (!purpose_text.trim() || purpose_text.length > 1000) {
        return validationError('body.purpose_text', 'From 1 to 1000 characters', 'STRING_LENGTH')
      }
      return HttpResponse.json(interpret(purpose_text, getScenario() !== 'unavailable'))
    },
  ),

  http.post<Params, Schemas['SubmitRequest']>(
    `${API}/applications/:application_id/submit`,
    async ({ request, params }) => {
      const checked = ownApplication(request, params.application_id)
      if (!checked.ok) return checked.response
      const { user, application } = checked.value
      return idempotent(request, user, async () => {
        const body = await readJson(request)
        const rejected = wrongStatus(application, 'DRAFT') ?? conflict(application, body.revision)
        if (rejected) return rejected

        const required = [
          'purpose_code',
          'requested_amount_rub',
          'term_months',
          'product_id',
        ] as const
        const missing = required.filter((field) => application[field] === null)
        if (missing.length > 0) {
          return apiError(422, 'APPLICATION_INCOMPLETE', 'Required fields are missing', {
            details: { missing_fields: [...missing] },
          })
        }
        const product = db.findProduct(application.product_id)
        const terms = requestedTerms(application)
        if (product && terms) {
          const unmet = unmetConstraints(product, {
            purpose: application.purpose_code ?? undefined,
            amount: parseInt(terms.amount_rub, 10),
            term: terms.term_months,
          })
          if (unmet.length > 0) {
            return apiError(422, 'PRODUCT_NOT_ELIGIBLE', 'Product is not eligible', {
              details: { product_id: product.id, unmet_constraints: unmet },
            })
          }
        }
        if (body.bki_consent_version !== BKI_CONSENT_VERSION) {
          return apiError(422, 'CONSENT_REQUIRED')
        }
        // Внешний сервис не ответил: заявка остаётся черновиком.
        if (providerDown()) return apiError(503, 'PROVIDER_UNAVAILABLE', 'BKI is unavailable')
        submitApplication(application)
        return view(application)
      })
    },
  ),

  http.post<Params, Schemas['InfoResponseRequest']>(
    `${API}/applications/:application_id/info-response`,
    async ({ request, params }) => {
      const checked = ownApplication(request, params.application_id)
      if (!checked.ok) return checked.response
      const { user, application } = checked.value
      return idempotent(request, user, async () => {
        const body = await readJson(request)
        const rejected =
          wrongStatus(application, 'NEED_INFO') ?? conflict(application, body.revision)
        if (rejected) return rejected
        const answer = body.answer_text?.trim() ?? ''
        if (!answer || answer.length > 2000) {
          return validationError('body.answer_text', 'From 1 to 2000 characters', 'STRING_LENGTH')
        }
        answerInfoRequest(application, answer)
        return view(application)
      })
    },
  ),

  ...(['accept', 'decline'] as const).map((action) =>
    http.post<Params, Schemas['RevisionRequest']>(
      `${API}/applications/:application_id/offer/${action}`,
      async ({ request, params }) => {
        const checked = ownApplication(request, params.application_id)
        if (!checked.ok) return checked.response
        const { user, application } = checked.value
        return idempotent(request, user, async () => {
          const body = await readJson(request)
          const rejected =
            wrongStatus(application, 'COUNTER_OFFER') ?? conflict(application, body.revision)
          if (rejected) return rejected
          if (action === 'accept') acceptOffer(application)
          else setStatus(application, 'DECLINED')
          return view(application)
        })
      },
    ),
  ),

  // Договор появляется после одобрения; до этого — 404, как у бэка.
  http.get<Params>(`${API}/applications/:application_id/contract`, ({ request, params }) => {
    const checked = ownApplication(request, params.application_id)
    if (!checked.ok) return checked.response
    const { application } = checked.value
    if (!application.contract) return apiError(404, 'NOT_FOUND')
    return HttpResponse.json(toContract(application))
  }),

  http.post<Params, Schemas['RevisionRequest']>(
    `${API}/applications/:application_id/sign/challenge`,
    async ({ request, params }) => {
      const checked = ownApplication(request, params.application_id)
      if (!checked.ok) return checked.response
      const { application } = checked.value
      const body = await readJson(request)
      const rejected = wrongStatus(application, 'APPROVED') ?? conflict(application, body.revision)
      if (rejected) return rejected

      const since = Date.now() - CHALLENGE_WINDOW_MS
      const recent = application.challenge_issued_at.filter((time) => time > since)
      if (recent.length >= CHALLENGE_LIMIT) {
        const retryAfter = Math.ceil(((recent[0] ?? Date.now()) - since) / 1000)
        return apiError(429, 'TOO_MANY_ATTEMPTS', 'Too many codes requested', {
          details: { scope: 'CHALLENGE_ISSUE', retry_after_seconds: retryAfter },
          headers: { 'Retry-After': String(retryAfter) },
        })
      }
      const challenge = db.createChallenge(application)
      return HttpResponse.json({
        challenge_id: challenge.id,
        expires_at: challenge.expires_at,
        attempts_remaining: challenge.attempts_remaining,
        revision: application.revision,
        demo_code: challenge.code,
      } satisfies Schemas['SignChallenge'])
    },
  ),

  // Две неверные попытки — 422 с остатком, третья — 429 и код больше не действует.
  http.post<Params, Schemas['SignRequest']>(
    `${API}/applications/:application_id/sign`,
    async ({ request, params }) => {
      const checked = ownApplication(request, params.application_id)
      if (!checked.ok) return checked.response
      const { user, application } = checked.value
      return idempotent(request, user, async () => {
        const body = await readJson(request)
        const rejected =
          wrongStatus(application, 'APPROVED') ?? conflict(application, body.revision)
        if (rejected) return rejected

        const challenge = application.challenges.find((item) => item.id === body.challenge_id)
        if (!challenge?.active || Date.parse(challenge.expires_at) <= Date.now()) {
          return apiError(422, 'SIGN_CHALLENGE_EXPIRED')
        }
        if (body.code !== challenge.code) {
          challenge.attempts_remaining -= 1
          if (challenge.attempts_remaining > 0) {
            return apiError(422, 'SIGN_CODE_INVALID', 'Wrong code', {
              details: { remaining_attempts: challenge.attempts_remaining },
            })
          }
          challenge.active = false
          return apiError(429, 'TOO_MANY_ATTEMPTS', 'Too many wrong codes', {
            details: { scope: 'SIGN_ATTEMPTS' },
          })
        }
        signApplication(application)
        return view(application)
      })
    },
  ),
]

const MAX_QUESTION = 1000
const MAX_COMMENT = 1000

const filled = (value: unknown): value is string =>
  typeof value === 'string' && value.trim().length > 0

/**
 * Обязательные поля решения (design.md §3.5): у отказа и оффера — причина для клиента
 * и комментарий; у одобрения вопреки рекомендации — комментарий-обоснование.
 */
function decisionFieldError(body: Record<string, unknown>, application: ApplicationRow) {
  if (typeof body.comment === 'string' && body.comment.length > MAX_COMMENT) {
    return validationError('body.comment', 'Comment is too long', 'TOO_LONG')
  }
  switch (body.action) {
    case 'APPROVE': {
      const suggestion = riskFor(application)?.proposal.suggested_action
      return suggestion !== 'ELIGIBLE_FOR_MANAGER_REVIEW' && !filled(body.comment)
        ? validationError('body.comment', 'Comment is required', 'REQUIRED')
        : null
    }
    case 'REJECT':
    case 'COUNTER_OFFER':
      return filled(body.comment)
        ? null
        : validationError('body.comment', 'Comment is required', 'REQUIRED')
    case 'REQUEST_INFO':
      return typeof body.question_text === 'string' && body.question_text.length > MAX_QUESTION
        ? validationError('body.question_text', 'Question is too long', 'TOO_LONG')
        : null
    default:
      return null
  }
}

function toDecision(body: Record<string, unknown>, application: ApplicationRow): Decision | null {
  switch (body.action) {
    case 'APPROVE':
      return { action: 'APPROVE' }
    case 'REJECT': {
      const reason = CLIENT_REASON_CODES.find((code) => code === body.client_reason_code)
      return reason ? { action: 'REJECT', client_reason_code: reason } : null
    }
    case 'REQUEST_INFO':
      return typeof body.question_text === 'string' && body.question_text.trim()
        ? { action: 'REQUEST_INFO', question_text: body.question_text }
        : null
    case 'COUNTER_OFFER': {
      const terms = requestedTerms(application)
      const reason = CLIENT_REASON_CODES.find((code) => code === body.client_reason_code)
      const amount =
        typeof body.amount_rub === 'number' ? `${body.amount_rub}.00` : terms?.amount_rub
      const term = typeof body.term_months === 'number' ? body.term_months : terms?.term_months
      return amount && term && reason
        ? {
            action: 'COUNTER_OFFER',
            amount_rub: amount,
            term_months: term,
            client_reason_code: reason,
          }
        : null
    }
    default:
      return null
  }
}

const managerHandlers = [
  http.get(`${API}/manager/applications`, ({ request }) => {
    const checked = authorize(request, 'MANAGER')
    if (!checked.ok) return checked.response
    const status = new URL(request.url).searchParams.get('status')
    const queue = db
      .listApplications()
      .filter((application) => application.status !== 'DRAFT')
      .filter((application) => !status || application.status === status)
    return HttpResponse.json(queue.map(toQueueItem))
  }),

  http.get<Params>(`${API}/manager/applications/:application_id`, ({ request, params }) => {
    const checked = authorize(request, 'MANAGER')
    if (!checked.ok) return checked.response
    const application = db.findApplication(params.application_id)
    if (!application || application.status === 'DRAFT') return apiError(404, 'NOT_FOUND')
    return HttpResponse.json(toManagerView(application))
  }),

  http.get(`${API}/manager/stats`, ({ request }) => {
    const checked = authorize(request, 'MANAGER')
    if (!checked.ok) return checked.response
    return HttpResponse.json(toStats())
  }),

  http.post<Params, Record<string, unknown>>(
    `${API}/manager/applications/:application_id/decisions`,
    async ({ request, params }) => {
      const checked = authorize(request, 'MANAGER')
      if (!checked.ok) return checked.response
      const application = db.findApplication(params.application_id)
      if (!application) return apiError(404, 'NOT_FOUND')
      return idempotent(request, checked.value, async () => {
        const body = await readJson(request)
        const rejected =
          wrongStatus(application, 'UNDER_REVIEW') ?? conflict(application, body.revision)
        if (rejected) return rejected
        const decision = toDecision(body, application)
        if (!decision) return validationError('body.action', 'Unknown decision', 'INVALID')
        // Набор действий задаёт бэк: при стоп-факторе — только отказ (design.md §3.5).
        if (!toManagerView(application).allowed_actions.includes(decision.action)) {
          return apiError(422, 'ACTION_NOT_ALLOWED')
        }
        const fieldError = decisionFieldError(body, application)
        if (fieldError) return fieldError
        if (decision.action === 'COUNTER_OFFER') {
          // Та же проверка, что у предпросмотра: решение не расходится с расчётом.
          const preview = offerPreview(
            application,
            parseInt(decision.amount_rub, 10),
            decision.term_months,
          )
          if (preview.violations.includes('AMOUNT_ABOVE_LIMIT')) {
            return apiError(422, 'AMOUNT_ABOVE_LIMIT', 'Amount is above limit for term')
          }
          if (!preview.valid) {
            return validationError('body.amount_rub', preview.violations.join(','), 'INVALID')
          }
        }
        const comment =
          typeof body.comment === 'string' && body.comment.trim() ? body.comment : null
        applyDecision(application, decision, { managerId: checked.value.id, comment })
        return HttpResponse.json(
          {
            decision_id: crypto.randomUUID(),
            status: application.status,
            revision: application.revision,
          } satisfies Schemas['DecisionResponse'],
          { status: 201 },
        )
      })
    },
  ),

  http.post<Params, Schemas['OfferPreviewRequest']>(
    `${API}/manager/applications/:application_id/offer-preview`,
    async ({ request, params }) => {
      const checked = authorize(request, 'MANAGER')
      if (!checked.ok) return checked.response
      const application = db.findApplication(params.application_id)
      if (!application || application.status === 'DRAFT') return apiError(404, 'NOT_FOUND')
      const rejected = wrongStatus(application, 'UNDER_REVIEW')
      if (rejected) return rejected
      const { amount_rub, term_months } = await readJson(request)
      if (typeof amount_rub !== 'number' || !Number.isInteger(amount_rub) || amount_rub <= 0) {
        return validationError('body.amount_rub', 'Positive integer expected', 'INVALID')
      }
      if (typeof term_months !== 'number' || !Number.isInteger(term_months) || term_months <= 0) {
        return validationError('body.term_months', 'Positive integer expected', 'INVALID')
      }
      return HttpResponse.json(offerPreview(application, amount_rub, term_months))
    },
  ),

  http.get<Params>(
    `${API}/manager/applications/:application_id/ai-report`,
    ({ request, params }) => {
      const checked = authorize(request, 'MANAGER')
      if (!checked.ok) return checked.response
      const application = db.findApplication(params.application_id)
      const report = application && aiReportFor(application)
      return report ? HttpResponse.json(report) : apiError(404, 'NOT_FOUND')
    },
  ),

  // Новое заключение: свежий PENDING не перезапускается, готовое — только с regenerate=true.
  http.post<Params>(
    `${API}/manager/applications/:application_id/ai-report`,
    ({ request, params }) => {
      const checked = authorize(request, 'MANAGER')
      if (!checked.ok) return checked.response
      const application = db.findApplication(params.application_id)
      const current = application && aiReportFor(application)
      if (!application || !current) return apiError(404, 'NOT_FOUND')
      const regenerate = new URL(request.url).searchParams.get('regenerate') === 'true'
      if (current.status === 'PENDING' || !regenerate) return HttpResponse.json(current)
      db.regenerateAiReport(application.id)
      return HttpResponse.json(aiReportFor(application), { status: 202 })
    },
  ),

  http.post<Params, Schemas['AiFeedbackRequest']>(
    `${API}/manager/applications/:application_id/ai-feedback`,
    async ({ request, params }) => {
      const checked = authorize(request, 'MANAGER')
      if (!checked.ok) return checked.response
      const application = db.findApplication(params.application_id)
      const report = application && aiReportFor(application)
      if (!application || !report) return apiError(404, 'NOT_FOUND')
      const { ai_report_id, verdict, comment } = await readJson(request)
      if (ai_report_id !== report.id) return apiError(404, 'NOT_FOUND')
      if (verdict !== 'UP' && verdict !== 'DOWN') {
        return validationError('body.verdict', 'UP or DOWN expected', 'ENUM')
      }
      if (typeof comment === 'string' && comment.length > MAX_COMMENT) {
        return validationError('body.comment', 'Comment is too long', 'TOO_LONG')
      }
      db.saveFeedback({
        ai_report_id: report.id,
        application_id: application.id,
        manager_user_id: checked.value.id,
        verdict,
        comment: filled(comment) ? comment : null,
        prompt_version: report.prompt_version,
        model_id: report.model_id,
        source: report.llm_mode,
      })
      return new HttpResponse(null, { status: 204 })
    },
  ),
]

export const handlers = [
  ...authHandlers,
  ...onboardingHandlers,
  ...applicationHandlers,
  ...managerHandlers,
]
