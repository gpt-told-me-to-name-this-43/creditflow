import type {
  ApplicationStatus,
  ClientReasonCode,
  ErrorCode,
  PurposeCode,
  Role,
} from '@/api/enums.ts'
import type { components } from '@/api/schema.d.ts'
import { isValidInn } from '@/lib/inn.ts'
import { formatKopecks, toKopecks } from './finance.ts'
import { getScenario, type Scenario } from './scenarios.ts'

/*
 * In-memory «база» моков. Записи повторяют таблицы БД из design.md §3.7, а не ответы API:
 * ответы из них собирает views.ts по типам schema.d.ts.
 * Данные — из ветки feat/6_findemo_and_test_data: учётки и продукты из api/app/seed.py,
 * реестр из ext-sim/fixtures (ЕГРЮЛ/ЕГРИП), ставки — каталог products-v2 (docs/demo-data.md).
 * Синтетика: регион «00» в ИНН не существует.
 */

type FieldSource = components['schemas']['FieldSource']
type TermsField = components['schemas']['TermsField']

export const DEMO_PASSWORD = 'creditflow-demo'
export const PD_CONSENT_VERSION = 'pd-v1'
export const BKI_CONSENT_VERSION = 'bki-v1'

export interface UserRow {
  id: string
  email: string
  role: Role
  full_name: string
  person_inn: string | null
  company_id: string | null
  /** Подпись в блоке «Демо-доступ» на экране входа. */
  scenario: string
}

export interface CompanyRow {
  id: string
  inn: string
  legal_form: 'LLC' | 'IE'
  name: string
  okved_main: string
  registered_at: string
  bound_at: string
}

/** Запись реестра: у ООО руководитель из ЕГРЮЛ, у ИП руководитель — он сам. */
export interface RegistryRow {
  inn: string
  legal_form: 'LLC' | 'IE'
  name: string
  status: 'ACTIVE' | 'LIQUIDATING' | 'LIQUIDATED'
  registered_at: string
  okved_main: string
  director: { full_name: string; inn: string }
}

export interface CreditProductRow {
  id: string
  name: string
  allowed_purposes: PurposeCode[]
  min_amount_rub: string
  max_amount_rub: string
  min_term_months: number
  max_term_months: number
  annual_rate_pct: string
}

/** Условия кредита: запрошенные, предложенные банком или вошедшие в договор. */
export interface TermsRow {
  amount_rub: string
  term_months: number
  annual_rate_pct: string
}

export interface ChallengeRow {
  id: string
  code: string
  expires_at: string
  attempts_remaining: number
  active: boolean
}

export interface ApplicationRow {
  id: string
  company_id: string
  owner_user_id: string
  status: ApplicationStatus
  revision: number
  purpose_text: string | null
  purpose_code: PurposeCode | null
  requested_amount_rub: string | null
  term_months: number | null
  product_id: string | null
  terms_field_sources: Partial<Record<TermsField, FieldSource>>
  created_at: string
  submitted_at: string | null
  client_reason_code: ClientReasonCode | null
  info_request: {
    question_text: string
    answer_text: string | null
    answered_at: string | null
  } | null
  offer: TermsRow | null
  /** Договор появляется при переходе в APPROVED (design.md §3.7). */
  contract: (TermsRow & { number: string; approved_at: string }) | null
  signed_at: string | null
  issued_at: string | null
  challenges: ChallengeRow[]
  /** Время выдачи кодов: не больше CHALLENGE_LIMIT за CHALLENGE_WINDOW_MS. */
  challenge_issued_at: number[]
}

export interface ApplicationEventRow {
  id: string
  application_id: string
  from_status: ApplicationStatus | null
  to_status: ApplicationStatus
  created_at: string
}

/** Сохранённый ответ действия с Idempotency-Key. */
export interface IdempotencyRow {
  fingerprint: string
  status: number
  body: unknown
}

const SEED_USERS: Omit<UserRow, 'id' | 'company_id'>[] = [
  client('director.techservice', 'Иванов Пётр Сергеевич', '009901001052', 'C1'),
  client('director.bakery', 'Кузнецова Анна Михайловна', '009902001009', 'C2'),
  client('ip.sokolova', 'Соколова Алёна Викторовна', '009903001040', 'C3'),
  client('director.newstart', 'Новиков Станислав Олегович', '009904001090', 'C4'),
  client('director.vector', 'Векторов Андрей Игоревич', '009905001039', 'C5'),
  client('director.sklad', 'Складов Михаил Дмитриевич', '009906001088', 'C6'),
  client('ip.orlov', 'Орлов Дмитрий Степанович', '009907001027', 'C7'),
  // Не руководитель «Пекарни Плюс»: привязка её ИНН → 403 APPLICANT_NOT_AUTHORIZED.
  client('accountant.bakery', 'Бухгалтерова Ольга Ивановна', '009902002059', 'Отказ полномочий'),
  manager('manager.anna', 'Анна Менеджерова'),
  manager('manager.oleg', 'Олег Менеджеров'),
]

const REGISTRY: RegistryRow[] = [
  llc(
    '0099010012',
    'ООО «ТехСервис»',
    '2021-10-21',
    '62.01',
    'Иванов Пётр Сергеевич',
    '009901001052',
  ),
  llc(
    '0099020010',
    'ООО «Пекарня Плюс»',
    '2023-10-21',
    '10.71',
    'Кузнецова Анна Михайловна',
    '009902001009',
  ),
  ie('009903001040', 'Соколова Алёна Викторовна', '2024-04-21', '62.02'),
  llc(
    '0099040017',
    'ООО «Новый Старт»',
    '2026-06-21',
    '46.39',
    'Новиков Станислав Олегович',
    '009904001090',
  ),
  {
    ...llc(
      '0099050015',
      'ООО «Вектор»',
      '2019-03-21',
      '46.90',
      'Векторов Андрей Игоревич',
      '009905001039',
    ),
    status: 'LIQUIDATING',
  },
  llc(
    '0099060013',
    'ООО «Склад-М»',
    '2020-09-21',
    '52.10',
    'Складов Михаил Дмитриевич',
    '009906001088',
  ),
  ie('009907001027', 'Орлов Дмитрий Степанович', '2023-10-21', '49.41'),
  llc('0099000014', 'ООО «Образец»', '2021-03-15', '10.71', 'Образцов Пётр Ильич', '009900000120'),
  llc(
    '0099990019',
    'ООО «Тест Сбой»',
    '2022-10-21',
    '62.01',
    'Тестов Тест Тестович',
    '009999001063',
  ),
]

/** Причина отказа по стоп-фактору компании (docs/demo-data.md, C4–C6). */
const STOP_REASONS: Record<string, ClientReasonCode> = {
  '0099040017': 'INSUFFICIENT_DATA',
  '0099050015': 'COMPANY_STATUS',
  '0099060013': 'TAX_AUTHORITY_RESTRICTIONS',
}

const PRODUCTS: CreditProductRow[] = [
  {
    id: 'investment',
    name: 'Инвестиционный кредит',
    allowed_purposes: ['EQUIPMENT', 'RENOVATION', 'BUSINESS_EXPANSION'],
    min_amount_rub: '100000.00',
    max_amount_rub: '5000000.00',
    min_term_months: 12,
    max_term_months: 60,
    annual_rate_pct: '24.00',
  },
  {
    id: 'working_capital',
    name: 'Оборотный кредит',
    allowed_purposes: ['INVENTORY', 'SUPPLIERS', 'WORKING_CAPITAL'],
    min_amount_rub: '100000.00',
    max_amount_rub: '3000000.00',
    min_term_months: 3,
    max_term_months: 24,
    annual_rate_pct: '25.00',
  },
]

function client(login: string, full_name: string, person_inn: string, scenario: string) {
  return {
    email: `${login}@creditflow.demo`,
    role: 'CLIENT' as const,
    full_name,
    person_inn,
    scenario,
  }
}

function manager(login: string, full_name: string) {
  return {
    email: `${login}@creditflow.demo`,
    role: 'MANAGER' as const,
    full_name,
    person_inn: null,
    scenario: 'MANAGER',
  }
}

function llc(
  inn: string,
  name: string,
  registered_at: string,
  okved_main: string,
  directorName: string,
  directorInn: string,
): RegistryRow {
  const director = { full_name: directorName, inn: directorInn }
  return { inn, legal_form: 'LLC', name, status: 'ACTIVE', registered_at, okved_main, director }
}

function ie(
  inn: string,
  full_name: string,
  registered_at: string,
  okved_main: string,
): RegistryRow {
  const director = { full_name, inn }
  return {
    inn,
    legal_form: 'IE',
    name: `ИП ${full_name}`,
    status: 'ACTIVE',
    registered_at,
    okved_main,
    director,
  }
}

/** Сравнение ФИО как на бэке (design.md §3.3): NFC, ё→е, нижний регистр, схлопнутые пробелы. */
export function normalizeFullName(name: string): string {
  return name.normalize('NFC').toLowerCase().replaceAll('ё', 'е').replace(/\s+/g, ' ').trim()
}

/** id в формате uuid, как в контракте, но предсказуемые: удобно в тестах и логах. */
function mockUuid(n: number) {
  return `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`
}

/** Отложенный переход «системы»: решение по сценарию или выдача после подписи. */
export type Job = { application_id: string; due_at: number } & (
  { kind: 'decide'; decision: Decision } | { kind: 'issue' }
)

/** Состояние — только данные: его можно сохранить в sessionStorage и восстановить. */
interface State {
  counter: number
  users: UserRow[]
  companies: CompanyRow[]
  applications: ApplicationRow[]
  events: ApplicationEventRow[]
  idempotency: Record<string, IdempotencyRow>
  jobs: Job[]
}

function createState(): State {
  return {
    counter: SEED_USERS.length,
    users: SEED_USERS.map((user, i) => ({ ...user, id: mockUuid(i + 1), company_id: null })),
    companies: [],
    applications: [],
    events: [],
    idempotency: {},
    jobs: [],
  }
}

let state = createState()
const timers = new Set<ReturnType<typeof setTimeout>>()

function nextId() {
  return mockUuid(++state.counter)
}

function disarm() {
  for (const timer of timers) clearTimeout(timer)
  timers.clear()
}

/** Для тестов и `?mock=`-перезапуска: чистые данные, отложенные переходы отменены. */
export function resetDb() {
  disarm()
  state = createState()
}

/** Снимок для sessionStorage: моки в браузере переживают перезагрузку страницы. */
export function snapshotDb(): string {
  return JSON.stringify(state)
}

/** Восстановить снимок; переходы, срок которых прошёл, пока страница перезагружалась, выполнятся сразу. */
export function restoreDb(snapshot: string) {
  disarm()
  state = JSON.parse(snapshot) as State
  for (const job of state.jobs) arm(job)
}

function now() {
  return new Date().toISOString()
}

export const db = {
  get products(): readonly CreditProductRow[] {
    return PRODUCTS
  },

  get users(): readonly UserRow[] {
    return state.users
  },

  findProduct(id: string | null) {
    return PRODUCTS.find((product) => product.id === id)
  },

  findUserByEmail(email: string) {
    return state.users.find((user) => user.email === email.trim().toLowerCase())
  },

  findUser(id: string) {
    return state.users.find((user) => user.id === id)
  },

  findCompany(id: string | null) {
    return state.companies.find((company) => company.id === id)
  },

  findApplication(id: string) {
    return state.applications.find((application) => application.id === id)
  },

  /** Новые сверху, как в списке «Мои заявки». */
  listApplications(companyId?: string) {
    return state.applications
      .filter((application) => companyId === undefined || application.company_id === companyId)
      .reverse()
  },

  listEvents(applicationId: string) {
    return state.events.filter((event) => event.application_id === applicationId)
  },

  findDraft(userId: string) {
    return state.applications.find(
      (application) => application.owner_user_id === userId && application.status === 'DRAFT',
    )
  },

  idempotency(userId: string, key: string) {
    return {
      get: () => state.idempotency[`${userId}:${key}`],
      set: (row: IdempotencyRow) => {
        state.idempotency[`${userId}:${key}`] = row
      },
    }
  },

  createApplication(user: UserRow, purposeText: string | null = null): ApplicationRow {
    if (!user.company_id) throw new Error('Заявку создаёт пользователь с компанией')
    const application: ApplicationRow = {
      id: nextId(),
      company_id: user.company_id,
      owner_user_id: user.id,
      status: 'DRAFT',
      revision: 1,
      purpose_text: purposeText,
      purpose_code: null,
      requested_amount_rub: null,
      term_months: null,
      product_id: null,
      terms_field_sources: {},
      created_at: now(),
      submitted_at: null,
      client_reason_code: null,
      info_request: null,
      offer: null,
      contract: null,
      signed_at: null,
      issued_at: null,
      challenges: [],
      challenge_issued_at: [],
    }
    state.applications.push(application)
    addEvent(application, null)
    return application
  },

  createChallenge(application: ApplicationRow): ChallengeRow {
    for (const challenge of application.challenges) challenge.active = false
    const challenge: ChallengeRow = {
      id: nextId(),
      // Демо-код случайный: интерфейс берёт его только из demo_code ответа.
      code: String(Math.floor(100000 + Math.random() * 900000)),
      expires_at: new Date(Date.now() + CHALLENGE_TTL_MS).toISOString(),
      attempts_remaining: 3,
      active: true,
    }
    application.challenges.push(challenge)
    application.challenge_issued_at.push(Date.now())
    return challenge
  },
}

export const CHALLENGE_TTL_MS = 5 * 60 * 1000
export const CHALLENGE_LIMIT = 5
export const CHALLENGE_WINDOW_MS = 15 * 60 * 1000

export type BindingResult =
  { ok: true; company: CompanyRow } | { ok: false; status: 403 | 409 | 422; code: ErrorCode }

/**
 * Привязка компании по правилам design.md §3.3: компания есть в реестре, ИНН и ФИО руководителя
 * или ИП совпадают с учёткой; один клиент — одна компания, одна компания — один клиент.
 * Повтор той же компании тем же клиентом — успех. Статус в реестре («ликвидируется») не мешает
 * привязке: это причина отказа по заявке (COMPANY_STATUS).
 */
export function bindCompany(userId: string, inn: string): BindingResult {
  const user = db.findUser(userId)
  if (!user) throw new Error(`Нет пользователя ${userId}`)
  if (!isValidInn(inn)) return { ok: false, status: 422, code: 'INVALID_INN' }

  const current = db.findCompany(user.company_id)
  if (current) {
    return current.inn === inn
      ? { ok: true, company: current }
      : { ok: false, status: 409, code: 'USER_ALREADY_BOUND' }
  }

  const record = REGISTRY.find((row) => row.inn === inn)
  if (!record) return { ok: false, status: 422, code: 'COMPANY_NOT_IN_REGISTRY' }

  const isApplicant =
    record.director.inn === user.person_inn &&
    normalizeFullName(record.director.full_name) === normalizeFullName(user.full_name)
  if (!isApplicant) return { ok: false, status: 403, code: 'APPLICANT_NOT_AUTHORIZED' }

  if (state.companies.some((company) => company.inn === inn)) {
    return { ok: false, status: 409, code: 'COMPANY_ALREADY_BOUND' }
  }

  const company: CompanyRow = {
    id: nextId(),
    inn,
    legal_form: record.legal_form,
    name: record.name,
    okved_main: record.okved_main,
    registered_at: record.registered_at,
    bound_at: now(),
  }
  state.companies.push(company)
  user.company_id = company.id
  return { ok: true, company }
}

function addEvent(application: ApplicationRow, from: ApplicationStatus | null) {
  state.events.push({
    id: nextId(),
    application_id: application.id,
    from_status: from,
    to_status: application.status,
    created_at: now(),
  })
}

/** Ревизия растёт при каждой записи, как на бэке. */
export function touch(application: ApplicationRow) {
  application.revision += 1
}

/** Смена статуса с ревизией и событием таймлайна — как одна транзакция на бэке. */
export function setStatus(application: ApplicationRow, status: ApplicationStatus) {
  const from = application.status
  application.status = status
  touch(application)
  addEvent(application, from)
}

/** Запрошенные клиентом условия по ставке выбранного продукта. */
export function requestedTerms(application: ApplicationRow): TermsRow | null {
  const product = db.findProduct(application.product_id)
  if (!product || !application.requested_amount_rub || !application.term_months) return null
  return {
    amount_rub: application.requested_amount_rub,
    term_months: application.term_months,
    annual_rate_pct: product.annual_rate_pct,
  }
}

export type Decision =
  | { action: 'APPROVE' }
  | { action: 'COUNTER_OFFER'; amount_rub: string; term_months: number }
  | { action: 'REQUEST_INFO'; question_text: string }
  | { action: 'REJECT'; client_reason_code: ClientReasonCode }

function approve(application: ApplicationRow, terms: TermsRow) {
  const number = `КФ-${application.id.slice(-6)}`
  application.contract = { ...terms, number, approved_at: now() }
  setStatus(application, 'APPROVED')
}

/** Решение менеджера по заявке UNDER_REVIEW. */
export function applyDecision(application: ApplicationRow, decision: Decision) {
  switch (decision.action) {
    case 'APPROVE': {
      const terms = requestedTerms(application)
      if (!terms) throw new Error('Одобрение заявки без условий')
      return approve(application, terms)
    }
    case 'COUNTER_OFFER': {
      const rate = requestedTerms(application)?.annual_rate_pct ?? '24.00'
      const { amount_rub, term_months } = decision
      application.offer = { amount_rub, term_months, annual_rate_pct: rate }
      application.client_reason_code = 'HIGH_DEBT_LOAD'
      return setStatus(application, 'COUNTER_OFFER')
    }
    case 'REQUEST_INFO':
      application.info_request = {
        question_text: decision.question_text,
        answer_text: null,
        answered_at: null,
      }
      return setStatus(application, 'NEED_INFO')
    case 'REJECT':
      application.client_reason_code = decision.client_reason_code
      return setStatus(application, 'REJECTED')
  }
}

/**
 * Встречное предложение сценария: по сумме — 78% запроса вниз до 10 000 ₽
 * (C2: 3 000 000 → 2 340 000), по сроку — тот же запрос на 18 мес. дольше (M11: 36 → 54).
 */
export function scenarioOffer(application: ApplicationRow, byTerm: boolean): Decision {
  const terms = requestedTerms(application)
  const product = db.findProduct(application.product_id)
  if (!terms || !product) throw new Error('Оффер по заявке без условий')
  const longer = Math.min(product.max_term_months, terms.term_months + 18)
  if (byTerm && longer > terms.term_months) {
    return { action: 'COUNTER_OFFER', amount_rub: terms.amount_rub, term_months: longer }
  }
  const step = toKopecks(10_000)
  const reduced = Math.floor((toKopecks(terms.amount_rub) * 78) / 100 / step) * step
  const amount = Math.max(reduced, toKopecks(product.min_amount_rub))
  return {
    action: 'COUNTER_OFFER',
    amount_rub: formatKopecks(amount),
    term_months: terms.term_months,
  }
}

export const NEED_INFO_QUESTION =
  'Пришлите, пожалуйста, договор с поставщиком или счёт на оборудование'

/** Сценарий демо-учётки владельца заявки (C1–C7) — для `?mock=default`. */
function ownerScenario(application: ApplicationRow) {
  return db.findUser(application.owner_user_id)?.scenario
}

/**
 * Решение по ветке демо-учётки (docs/demo-data.md): C1 — одобрение, C2 — встречное
 * предложение по сумме, C3 — дозапрос, C4–C6 — отказ по стоп-фактору, C7 — отказ
 * из-за долговой нагрузки. Остальные учётки ждут менеджера.
 */
function accountOutcome(application: ApplicationRow): Decision | null {
  switch (ownerScenario(application)) {
    case 'C1':
      return { action: 'APPROVE' }
    case 'C2':
      return scenarioOffer(application, false)
    case 'C3':
      return { action: 'REQUEST_INFO', question_text: NEED_INFO_QUESTION }
    case 'C4':
    case 'C5':
    case 'C6':
      return stopDecision(application)
    case 'C7':
      return { action: 'REJECT', client_reason_code: 'HIGH_DEBT_LOAD' }
    default:
      return null
  }
}

function stopDecision(application: ApplicationRow): Decision {
  const inn = db.findCompany(application.company_id)?.inn ?? ''
  return { action: 'REJECT', client_reason_code: STOP_REASONS[inn] ?? 'LOW_SCORE' }
}

/**
 * Каким решением закончится рассмотрение в сценарии `?mock=`. По умолчанию — ветка
 * демо-учётки. `null` — заявка остаётся на рассмотрении и ждёт менеджера (`manager`)
 * или недоступного внешнего сервиса.
 */
export function reviewOutcome(application: ApplicationRow, scenario: Scenario): Decision | null {
  switch (scenario) {
    case 'approve':
      return { action: 'APPROVE' }
    case 'offer':
      return scenarioOffer(application, false)
    case 'offer_term':
      return scenarioOffer(application, true)
    case 'need_info':
      return { action: 'REQUEST_INFO', question_text: NEED_INFO_QUESTION }
    case 'stop':
      return stopDecision(application)
    case 'default':
      return accountOutcome(application)
    case 'manager':
    case 'unavailable':
    case 'error503':
      return null
  }
}

/** Задержки подобраны под опрос раз в 5 с: смена статуса видна на первом-втором запросе. */
export const REVIEW_DELAY_MS = 4000
export const ISSUE_DELAY_MS = 3000

function run(job: Job) {
  const application = db.findApplication(job.application_id)
  if (!application) return
  if (job.kind === 'decide' && application.status === 'UNDER_REVIEW') {
    applyDecision(application, job.decision)
  }
  if (job.kind === 'issue' && application.status === 'SIGNED') {
    application.issued_at = now()
    setStatus(application, 'ISSUED')
  }
}

function arm(job: Job) {
  const timer = setTimeout(
    () => {
      timers.delete(timer)
      state.jobs = state.jobs.filter((item) => item !== job)
      run(job)
    },
    Math.max(0, job.due_at - Date.now()),
  )
  timers.add(timer)
}

function schedule(job: Job) {
  state.jobs.push(job)
  arm(job)
}

function decideLater(application: ApplicationRow, decision: Decision | null) {
  if (!decision) return
  const due_at = Date.now() + REVIEW_DELAY_MS
  schedule({ kind: 'decide', application_id: application.id, due_at, decision })
}

/** После отправки: UNDER_REVIEW сразу, решение по сценарию через REVIEW_DELAY_MS. */
export function submitApplication(application: ApplicationRow) {
  application.submitted_at = now()
  setStatus(application, 'UNDER_REVIEW')
  decideLater(application, reviewOutcome(application, getScenario()))
}

/** Ответ на дозапрос: снова на рассмотрение; в ветке дозапроса (need_info, C3) затем одобрение. */
export function answerInfoRequest(application: ApplicationRow, answerText: string) {
  if (!application.info_request) throw new Error('Ответ без вопроса')
  application.info_request.answer_text = answerText
  application.info_request.answered_at = now()
  setStatus(application, 'UNDER_REVIEW')
  const scenario = getScenario()
  const approves =
    scenario === 'need_info' || (scenario === 'default' && ownerScenario(application) === 'C3')
  decideLater(application, approves ? { action: 'APPROVE' } : null)
}

/** Принятие оффера: договор на условиях оффера, исходный запрос не меняется. */
export function acceptOffer(application: ApplicationRow) {
  if (!application.offer) throw new Error('Принятие без оффера')
  approve(application, application.offer)
}

/** После подписи: SIGNED сразу, «Средства зачислены» через ISSUE_DELAY_MS (design.md §3.3). */
export function signApplication(application: ApplicationRow) {
  application.signed_at = now()
  for (const challenge of application.challenges) challenge.active = false
  setStatus(application, 'SIGNED')
  schedule({ kind: 'issue', application_id: application.id, due_at: Date.now() + ISSUE_DELAY_MS })
}

/** `?mock=error503`: реестр и БКИ не отвечают — 503 на привязке и отправке. */
export function providerDown() {
  return getScenario() === 'error503'
}
