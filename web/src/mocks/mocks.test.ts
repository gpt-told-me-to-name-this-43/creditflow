import { http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, unwrap } from '@/api/client.ts'
import { auth } from '@/lib/auth.ts'
import { server } from '@/test/server.ts'
import { demoUser, signInAs, signInWithCompany } from '@/test/session.ts'
import { ISSUE_DELAY_MS, REVIEW_DELAY_MS } from './db.ts'
import { apiError } from './handlers.ts'
import { getScenario, initScenario, setScenario } from './scenarios.ts'

const failure = (request: Promise<unknown>) =>
  request.then(
    () => null,
    (error: unknown) => error,
  )

describe('сценарии моков', () => {
  it('берётся из ?mock= и переживает переход без параметра', () => {
    expect(initScenario({ search: '?mock=need_info' })).toBe('need_info')
    expect(initScenario({ search: '' })).toBe('need_info')
  })

  it('неизвестное значение не меняет сценарий', () => {
    setScenario('offer')
    expect(initScenario({ search: '?mock=nope' })).toBe('offer')
  })

  it('каждый тест начинается с обычного поведения', () => {
    expect(getScenario()).toBe('default')
    expect(initScenario({ search: '' })).toBe('default')
  })
})

describe('общие обработчики', () => {
  it('health отвечает по контракту', async () => {
    const data = await unwrap(api.GET('/api/v1/health'))
    expect(data).toEqual({ status: 'ok', db: 'ok', ext_sim: 'ok', llm: 'replay' })
  })

  it('сценарий unavailable отключает ИИ', async () => {
    setScenario('unavailable')
    const data = await unwrap(api.GET('/api/v1/health'))
    expect(data.llm).toBe('disabled')
  })

  it('apiError отдаёт конверт ошибки, который понимает клиент', async () => {
    server.use(http.get('/api/v1/health', () => apiError(503, 'PROVIDER_UNAVAILABLE')))
    const error = await failure(unwrap(api.GET('/api/v1/health')))
    expect(error).toMatchObject({ status: 503, code: 'PROVIDER_UNAVAILABLE' })
  })
})

describe('вход', () => {
  it('демо-учётки: семь сценариев, бухгалтер и менеджеры', async () => {
    const accounts = await unwrap(api.GET('/api/v1/auth/demo-accounts'))
    expect(accounts).toHaveLength(10)
    expect(accounts[1]).toEqual({
      label: 'Кузнецова Анна Михайловна',
      login: 'director.bakery@creditflow.demo',
      password: 'creditflow-demo',
      role: 'CLIENT',
      scenario: 'C2',
    })
  })

  it('верный пароль — токен, /auth/me знает пользователя', async () => {
    await signInAs('director.bakery')
    const me = await unwrap(api.GET('/api/v1/auth/me'))
    expect(me).toMatchObject({ full_name: 'Кузнецова Анна Михайловна', company_id: null })
  })

  it('неверный пароль — 401 INVALID_CREDENTIALS', async () => {
    const body = { login: 'director.bakery@creditflow.demo', password: 'nope' }
    const error = await failure(unwrap(api.POST('/api/v1/auth/login', { body })))
    expect(error).toMatchObject({ status: 401, code: 'INVALID_CREDENTIALS' })
  })

  it('без токена — 401 UNAUTHORIZED', async () => {
    const error = await failure(unwrap(api.GET('/api/v1/auth/me')))
    expect(error).toMatchObject({ status: 401, code: 'UNAUTHORIZED' })
  })

  it('менеджеру клиентские эндпоинты запрещены', async () => {
    await signInAs('manager.anna')
    const error = await failure(unwrap(api.GET('/api/v1/applications')))
    expect(error).toMatchObject({ status: 403, code: 'FORBIDDEN' })
  })
})

describe('привязка компании', () => {
  const bind = (inn: string, pd_consent_version = 'pd-v1') =>
    unwrap(api.POST('/api/v1/onboarding/company-binding', { body: { inn, pd_consent_version } }))

  it('без компании заявки и /company — 409 COMPANY_NOT_BOUND', async () => {
    await signInAs('director.bakery')
    const company = await failure(unwrap(api.GET('/api/v1/company')))
    const applications = await failure(unwrap(api.GET('/api/v1/applications')))
    expect(company).toMatchObject({ status: 409, code: 'COMPANY_NOT_BOUND' })
    expect(applications).toMatchObject({ status: 409, code: 'COMPANY_NOT_BOUND' })
  })

  it('руководитель привязывает компанию, повтор — тот же ответ', async () => {
    await signInAs('director.bakery')
    const company = await bind('0099020010')
    expect(company).toMatchObject({ inn: '0099020010', name: 'ООО «Пекарня Плюс»' })
    expect(await bind('0099020010')).toEqual(company)
    expect(await unwrap(api.GET('/api/v1/company'))).toEqual(company)
  })

  it.each([
    ['director.bakery', '12345', 'pd-v1', 422, 'INVALID_INN'],
    ['director.bakery', '0099020010', 'pd-v0', 422, 'CONSENT_REQUIRED'],
    ['director.bakery', '0099020011', 'pd-v1', 422, 'INVALID_INN'],
    ['director.bakery', '7707083893', 'pd-v1', 422, 'COMPANY_NOT_IN_REGISTRY'],
    ['accountant.bakery', '0099020010', 'pd-v1', 403, 'APPLICANT_NOT_AUTHORIZED'],
  ])('%s, ИНН %s, согласие %s → %i %s', async (login, inn, consent, status, code) => {
    await signInAs(login)
    expect(await failure(bind(inn, consent))).toMatchObject({ status, code })
  })

  it('реестр недоступен — 503 PROVIDER_UNAVAILABLE', async () => {
    setScenario('error503')
    await signInAs('director.bakery')
    expect(await failure(bind('0099020010'))).toMatchObject({
      status: 503,
      code: 'PROVIDER_UNAVAILABLE',
    })
  })
})

describe('продукты', () => {
  it('C2: инвестиционный подходит с платежом, оборотный — нет и почему', async () => {
    await signInAs('director.bakery')
    const products = await unwrap(
      api.GET('/api/v1/credit-products', {
        params: { query: { purpose: 'EQUIPMENT', amount: 3_000_000, term: 36 } },
      }),
    )
    expect(products).toMatchObject([
      { id: 'investment', suitable: true, monthly_payment_rub: '117698.56', unmet_constraints: [] },
      {
        id: 'working_capital',
        suitable: false,
        monthly_payment_rub: null,
        annual_rate_pct: '25.00',
        unmet_constraints: ['PURPOSE_NOT_ALLOWED', 'TERM_ABOVE_PRODUCT_MAX'],
      },
    ])
  })
})

// Полный путь заявки через HTTP — так же, как его пройдёт интерфейс.
describe('заявка', () => {
  const id = (applicationId: string) => ({ path: { application_id: applicationId } })
  const withKey = (applicationId: string, key: string = crypto.randomUUID()) => ({
    path: { application_id: applicationId },
    header: { 'Idempotency-Key': key },
  })

  async function filledDraft() {
    await signInWithCompany('director.bakery', '0099020010')
    const draft = await unwrap(api.POST('/api/v1/applications', { body: {} }))
    return unwrap(
      api.PATCH('/api/v1/applications/{application_id}', {
        params: id(draft.id),
        body: {
          revision: draft.revision,
          purpose_code: 'EQUIPMENT',
          requested_amount_rub: 3_000_000,
          term_months: 36,
          product_id: 'investment',
          terms_field_sources: {
            purpose_code: 'LLM',
            requested_amount_rub: 'RULES',
            term_months: 'MANUAL',
          },
        },
      }),
    )
  }

  const submit = (applicationId: string, revision: number, key?: string) =>
    unwrap(
      api.POST('/api/v1/applications/{application_id}/submit', {
        params: withKey(applicationId, key),
        body: { revision, bki_consent_version: 'bki-v1' },
      }),
    )

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'Date'] })
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('черновик один: второй POST возвращает тот же (200)', async () => {
    await signInWithCompany('director.bakery', '0099020010')
    const first = await api.POST('/api/v1/applications', { body: { purpose_text: 'печь' } })
    const second = await api.POST('/api/v1/applications', { body: { purpose_text: 'другое' } })
    expect(first.response.status).toBe(201)
    expect(second.response.status).toBe(200)
    expect(second.data).toMatchObject({ id: first.data?.id, purpose_text: 'печь' })
  })

  it('PATCH сохраняет условия, источник условий считает бэк', async () => {
    const application = await filledDraft()
    expect(application).toMatchObject({
      revision: 2,
      requested_amount_rub: '3000000.00',
      terms_source: 'LLM_CONFIRMED',
      monthly_payment_rub: '117698.56',
      allowed_actions: ['EDIT', 'INTERPRET', 'SUBMIT'],
    })
  })

  it('устаревшая ревизия — 409 с текущей', async () => {
    const application = await filledDraft()
    const error = await failure(
      unwrap(
        api.PATCH('/api/v1/applications/{application_id}', {
          params: id(application.id),
          body: { revision: 1, term_months: 48 },
        }),
      ),
    )
    expect(error).toMatchObject({
      status: 409,
      code: 'REVISION_CONFLICT',
      details: { current_revision: 2 },
    })
  })

  it('отправка неполной заявки — список недостающих полей', async () => {
    await signInWithCompany('director.bakery', '0099020010')
    const draft = await unwrap(api.POST('/api/v1/applications', { body: {} }))
    expect(await failure(submit(draft.id, draft.revision))).toMatchObject({
      code: 'APPLICATION_INCOMPLETE',
      details: {
        missing_fields: ['purpose_code', 'requested_amount_rub', 'term_months', 'product_id'],
      },
    })
  })

  it('продукт не подходит — PRODUCT_NOT_ELIGIBLE с причинами', async () => {
    const application = await filledDraft()
    const patched = await unwrap(
      api.PATCH('/api/v1/applications/{application_id}', {
        params: id(application.id),
        body: { revision: application.revision, product_id: 'working_capital' },
      }),
    )
    expect(await failure(submit(patched.id, patched.revision))).toMatchObject({
      code: 'PRODUCT_NOT_ELIGIBLE',
      details: {
        product_id: 'working_capital',
        unmet_constraints: ['PURPOSE_NOT_ALLOWED', 'TERM_ABOVE_PRODUCT_MAX'],
      },
    })
  })

  it('сбой внешнего сервиса — 503, заявка остаётся черновиком', async () => {
    setScenario('error503')
    const application = await filledDraft()
    expect(await failure(submit(application.id, application.revision))).toMatchObject({
      status: 503,
      code: 'PROVIDER_UNAVAILABLE',
    })
    const current = await unwrap(
      api.GET('/api/v1/applications/{application_id}', { params: id(application.id) }),
    )
    expect(current.status).toBe('DRAFT')
  })

  it('повтор с тем же ключом — тот же ответ, ключ с другим телом — 422', async () => {
    const application = await filledDraft()
    const key = crypto.randomUUID()
    const first = await submit(application.id, application.revision, key)
    expect(await submit(application.id, application.revision, key)).toEqual(first)
    expect(await failure(submit(application.id, application.revision + 1, key))).toMatchObject({
      code: 'IDEMPOTENCY_KEY_REUSED',
    })
  })

  it('одновременный повтор с тем же ключом не выполняет действие второй раз', async () => {
    const application = await filledDraft()
    const key = crypto.randomUUID()
    const [first, second] = await Promise.all([
      submit(application.id, application.revision, key),
      failure(submit(application.id, application.revision, key)),
    ])
    expect(second).toMatchObject({ status: 409, code: 'IDEMPOTENCY_IN_PROGRESS' })
    // Повтор после завершения — сохранённый ответ первого запроса, а не новая обработка.
    expect(first).toMatchObject({ status: 'UNDER_REVIEW', revision: application.revision + 1 })
    expect(await submit(application.id, application.revision, key)).toEqual(first)
  })

  it('пока ключ обрабатывается, другое тело — 422 IDEMPOTENCY_KEY_REUSED', async () => {
    const application = await filledDraft()
    const key = crypto.randomUUID()
    const [, reused] = await Promise.all([
      submit(application.id, application.revision, key),
      failure(submit(application.id, application.revision + 1, key)),
    ])
    expect(reused).toMatchObject({ code: 'IDEMPOTENCY_KEY_REUSED' })
  })

  it('после ошибки тот же ключ выполняет действие заново', async () => {
    setScenario('error503')
    const application = await filledDraft()
    const key = crypto.randomUUID()
    expect(await failure(submit(application.id, application.revision, key))).toMatchObject({
      code: 'PROVIDER_UNAVAILABLE',
    })
    setScenario('default')
    expect(await submit(application.id, application.revision, key)).toMatchObject({
      status: 'UNDER_REVIEW',
    })
  })

  it('чужая заявка — 404', async () => {
    const application = await filledDraft()
    await signInWithCompany('director.techservice', '0099010012')
    const error = await failure(
      unwrap(api.GET('/api/v1/applications/{application_id}', { params: id(application.id) })),
    )
    expect(error).toMatchObject({ status: 404, code: 'NOT_FOUND' })
  })

  it('C2: оффер → принятие → договор → код → выдача', async () => {
    setScenario('offer')
    const draft = await filledDraft()
    const submitted = await submit(draft.id, draft.revision)
    expect(submitted.status).toBe('UNDER_REVIEW')

    await vi.advanceTimersByTimeAsync(REVIEW_DELAY_MS)
    const offered = await unwrap(
      api.GET('/api/v1/applications/{application_id}', { params: id(draft.id) }),
    )
    expect(offered).toMatchObject({
      status: 'COUNTER_OFFER',
      requested_amount_rub: '3000000.00',
      offer: { amount_rub: '2340000.00', term_months: 36, monthly_payment_rub: '91804.88' },
      allowed_actions: ['ACCEPT_OFFER', 'DECLINE_OFFER'],
    })

    const accepted = await unwrap(
      api.POST('/api/v1/applications/{application_id}/offer/accept', {
        params: withKey(draft.id),
        body: { revision: offered.revision },
      }),
    )
    expect(accepted).toMatchObject({ status: 'APPROVED', requested_amount_rub: '3000000.00' })

    const contract = await unwrap(
      api.GET('/api/v1/applications/{application_id}/contract', { params: id(draft.id) }),
    )
    expect(contract).toMatchObject({
      status: 'DRAFT',
      amount_rub: '2340000.00',
      monthly_payment_rub: '91804.88',
    })
    expect(contract.schedule).toHaveLength(36)

    const challenge = await unwrap(
      api.POST('/api/v1/applications/{application_id}/sign/challenge', {
        params: id(draft.id),
        body: { revision: accepted.revision },
      }),
    )
    expect(challenge.demo_code).toMatch(/^\d{6}$/)
    const sign = (code: string) =>
      unwrap(
        api.POST('/api/v1/applications/{application_id}/sign', {
          params: withKey(draft.id),
          body: { revision: challenge.revision, challenge_id: challenge.challenge_id, code },
        }),
      )
    const wrong = challenge.demo_code === '000000' ? '111111' : '000000'
    expect(await failure(sign(wrong))).toMatchObject({
      code: 'SIGN_CODE_INVALID',
      details: { remaining_attempts: 2 },
    })

    const signed = await sign(challenge.demo_code ?? '')
    expect(signed.status).toBe('SIGNED')
    await vi.advanceTimersByTimeAsync(ISSUE_DELAY_MS)
    const issued = await unwrap(
      api.GET('/api/v1/applications/{application_id}', { params: id(draft.id) }),
    )
    expect(issued.status).toBe('ISSUED')
    expect(issued.timeline.map((event) => event.to_status)).toEqual([
      'DRAFT',
      'UNDER_REVIEW',
      'COUNTER_OFFER',
      'APPROVED',
      'SIGNED',
      'ISSUED',
    ])
  })

  it('третья неверная попытка — 429, код больше не действует', async () => {
    setScenario('approve')
    const draft = await filledDraft()
    await submit(draft.id, draft.revision)
    await vi.advanceTimersByTimeAsync(REVIEW_DELAY_MS)
    const approved = await unwrap(
      api.GET('/api/v1/applications/{application_id}', { params: id(draft.id) }),
    )
    const challenge = await unwrap(
      api.POST('/api/v1/applications/{application_id}/sign/challenge', {
        params: id(draft.id),
        body: { revision: approved.revision },
      }),
    )
    const sign = (code: string) =>
      failure(
        unwrap(
          api.POST('/api/v1/applications/{application_id}/sign', {
            params: withKey(draft.id),
            body: { revision: challenge.revision, challenge_id: challenge.challenge_id, code },
          }),
        ),
      )
    const wrong = challenge.demo_code === '000000' ? '111111' : '000000'
    await sign(wrong)
    await sign(wrong)
    expect(await sign(wrong)).toMatchObject({
      status: 429,
      code: 'TOO_MANY_ATTEMPTS',
      details: { scope: 'SIGN_ATTEMPTS' },
    })
    expect(await sign(challenge.demo_code ?? '')).toMatchObject({ code: 'SIGN_CHALLENGE_EXPIRED' })
  })

  it('менеджер видит заявку в очереди и запрашивает уточнение', async () => {
    const draft = await filledDraft()
    const submitted = await submit(draft.id, draft.revision)
    auth.clear()
    await signInAs('manager.anna')
    const queue = await unwrap(api.GET('/api/v1/manager/applications'))
    expect(queue).toMatchObject([{ id: draft.id, company_name: 'ООО «Пекарня Плюс»' }])

    const decision = await unwrap(
      api.POST('/api/v1/manager/applications/{application_id}/decisions', {
        params: withKey(draft.id),
        body: {
          action: 'REQUEST_INFO',
          revision: submitted.revision,
          question_text: 'Пришлите счёт на печь',
        },
      }),
    )
    expect(decision.status).toBe('NEED_INFO')
    expect(demoUser('director.bakery').company_id).not.toBeNull()
  })
})
