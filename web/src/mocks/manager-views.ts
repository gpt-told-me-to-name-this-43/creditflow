import type { components } from '@/api/schema.d.ts'
import { type ApplicationRow, CHALLENGE_TTL_MS, db, requestedTerms } from './db.ts'
import { getScenario } from './scenarios.ts'
import {
  assess,
  COMPANY_DATA,
  externalSources,
  propose,
  type RiskResult,
  stopFactors,
} from './scoring.ts'
import { termsSource, toClientView, toContract } from './views.ts'

/* Ответы кабинета менеджера из записей db: только DTO из schema.d.ts. */

type Schemas = components['schemas']

function facts(application: ApplicationRow) {
  const company = db.findCompany(application.company_id)
  if (!company) throw new Error(`Нет компании у заявки ${application.id}`)
  const registry = db.findRegistry(company.inn)
  return {
    company,
    inn: company.inn,
    registered_at: company.registered_at,
    registry_status: registry?.status ?? 'ACTIVE',
    legal_form: company.legal_form,
    director: registry?.director ?? { full_name: '', inn: '' },
  }
}

/**
 * Расчёт и рекомендация по запрошенным условиям. Данные детерминированы, поэтому
 * моки считают на лету, а не хранят снимок, как бэк.
 */
export function riskFor(application: ApplicationRow): {
  risk: RiskResult
  proposal: Schemas['Proposal']
} | null {
  if (application.status === 'DRAFT') return null
  const product = db.findProduct(application.product_id)
  const terms = requestedTerms(application)
  if (!product || !terms) return null
  const companyFacts = facts(application)
  const risk = assess(companyFacts, {
    amount: parseInt(terms.amount_rub, 10),
    term: terms.term_months,
    product,
  })
  const blocking = stopFactors(companyFacts, COMPANY_DATA[companyFacts.inn])
  return { risk, proposal: propose(risk, blocking) }
}

export function toQueueItem(application: ApplicationRow): Schemas['QueueItem'] {
  const { company } = facts(application)
  const result = riskFor(application)
  return {
    id: application.id,
    status: application.status,
    company_inn: company.inn,
    company_name: company.name,
    product_id: application.product_id,
    requested_amount_rub: application.requested_amount_rub,
    term_months: application.term_months,
    submitted_at: application.submitted_at,
    blocking_codes: result?.proposal.blocking_codes ?? [],
    suggested_action: result?.proposal.suggested_action ?? null,
  }
}

/** Набор действий менеджера: только на рассмотрении; при стоп-факторе — только отказ. */
export function managerActions(
  application: ApplicationRow,
  result: ReturnType<typeof riskFor>,
): Schemas['ManagerAction'][] {
  if (application.status !== 'UNDER_REVIEW' || !result) return []
  if (result.proposal.blocking_codes.length > 0) return ['REJECT']
  const actions: Schemas['ManagerAction'][] = ['APPROVE']
  if (result.risk.scoring.limit_rub !== null) actions.push('COUNTER_OFFER')
  actions.push('REQUEST_INFO', 'REJECT')
  return actions
}

function userName(id: string | null) {
  return id ? (db.findUser(id)?.full_name ?? null) : null
}

function offerHistory(application: ApplicationRow): Schemas['OfferHistoryItem'][] {
  const offer = application.offer
  const product = db.findProduct(application.product_id)
  if (!offer || !product) return []
  const risk = assess(
    facts(application),
    { amount: parseInt(offer.amount_rub, 10), term: offer.term_months, product },
    'COUNTER_OFFER',
  )
  // Платёж и переплата оффера — те же, что видит клиент.
  const client = toClientView(application)
  const status =
    application.status === 'COUNTER_OFFER'
      ? 'OPEN'
      : application.status === 'DECLINED'
        ? 'DECLINED'
        : 'ACCEPTED'
  return [
    {
      id: `${offer.decision_id.slice(0, -1)}f`,
      decision_id: offer.decision_id,
      created_at: offer.created_at,
      product_id: product.id,
      amount_rub: offer.amount_rub,
      term_months: offer.term_months,
      annual_rate_pct: offer.annual_rate_pct,
      monthly_payment_rub:
        client.offer?.monthly_payment_rub ?? risk.scoring.monthly_payment_rub ?? '0.00',
      overpayment_rub: client.offer?.overpayment_rub ?? '0.00',
      status,
      scoring: risk.scoring,
    },
  ]
}

function contractFor(application: ApplicationRow): Schemas['ManagerContractView'] | null {
  if (!application.contract) return null
  return {
    ...toContract(application),
    id: `${application.id.slice(0, -1)}c`,
    signed_by_user_id: application.signed_at ? application.owner_user_id : null,
  }
}

export function toManagerView(application: ApplicationRow): Schemas['ManagerApplicationView'] {
  const companyFacts = facts(application)
  const { company } = companyFacts
  const result = riskFor(application)
  const actions = managerActions(application, result)
  const product = db.findProduct(application.product_id)
  const events = db.listEvents(application.id)
  const fetchedAt = application.submitted_at ?? application.created_at

  return {
    id: application.id,
    revision: application.revision,
    status: application.status,
    company_name: company.name,
    company_inn: company.inn,
    legal_form: company.legal_form,
    okved_main: company.okved_main,
    registered_at: company.registered_at,
    purpose_text: application.purpose_text,
    purpose_code: application.purpose_code,
    requested_amount_rub: application.requested_amount_rub,
    term_months: application.term_months,
    product_id: application.product_id,
    terms_source: termsSource(application),
    terms_field_sources: { ...application.terms_field_sources },
    submitted_at: application.submitted_at,
    sources: application.submitted_at ? externalSources(companyFacts, fetchedAt) : [],
    scoring: result?.risk.scoring ?? null,
    proposal: result?.proposal ?? null,
    allowed_actions: actions,
    offer_constraints:
      actions.includes('COUNTER_OFFER') && product
        ? {
            min_amount_rub: product.min_amount_rub,
            max_amount_rub: product.max_amount_rub,
            min_term_months: product.min_term_months,
            max_term_months: product.max_term_months,
          }
        : null,
    ai_report: aiReportFor(application, result),
    decisions: db.listDecisions(application.id).map((decision) => ({
      id: decision.id,
      action: decision.action,
      client_reason_code: decision.client_reason_code,
      comment: decision.comment,
      created_at: decision.created_at,
      manager_user_id: decision.manager_user_id,
      manager_full_name: userName(decision.manager_user_id) ?? '',
      proposal_id: `${decision.id.slice(0, -1)}a`,
    })),
    offers: offerHistory(application),
    info_requests: application.info_request
      ? [
          {
            id: `${application.info_request.decision_id.slice(0, -1)}b`,
            decision_id: application.info_request.decision_id,
            created_at: application.info_request.created_at,
            question_text: application.info_request.question_text,
            answer_text: application.info_request.answer_text,
            answered_at: application.info_request.answered_at,
          },
        ]
      : [],
    contract: contractFor(application),
    sign_challenges: application.challenges.map((challenge) => ({
      id: challenge.id,
      created_at: new Date(Date.parse(challenge.expires_at) - CHALLENGE_TTL_MS).toISOString(),
      expires_at: challenge.expires_at,
      attempts: 3 - challenge.attempts_remaining,
      used_at:
        !challenge.active && application.signed_at && challenge.attempts_remaining > 0
          ? application.signed_at
          : null,
    })),
    timeline: events.map((event) => ({
      id: event.id,
      from_status: event.from_status,
      to_status: event.to_status,
      created_at: event.created_at,
      actor_user_id: event.actor_user_id ?? null,
      actor_full_name: userName(event.actor_user_id ?? null),
    })),
  }
}

/** Совпадает ли решение с рекомендацией; «ручное рассмотрение» не сравнивается. */
const MATCHING: Partial<Record<Schemas['SuggestedAction'], Schemas['ManagerAction']>> = {
  ELIGIBLE_FOR_MANAGER_REVIEW: 'APPROVE',
  COUNTER_OFFER_CANDIDATE: 'COUNTER_OFFER',
  BLOCKED_BY_RULE: 'REJECT',
}

export function toStats(): Schemas['ManagerStats'] {
  const submitted = db.listApplications().filter((application) => application.status !== 'DRAFT')
  const byStatus: Record<string, number> = {}
  const distribution: Record<string, number> = {}
  const waits: number[] = []
  let compared = 0
  let matched = 0

  for (const application of submitted) {
    byStatus[application.status] = (byStatus[application.status] ?? 0) + 1
    const suggestion = riskFor(application)?.proposal.suggested_action
    // Распределение рекомендаций — по заявкам на рассмотрении (docs/api.md).
    if (suggestion && application.status === 'UNDER_REVIEW') {
      distribution[suggestion] = (distribution[suggestion] ?? 0) + 1
    }
    const [first] = db.listDecisions(application.id)
    if (first && application.submitted_at) {
      waits.push((Date.parse(first.created_at) - Date.parse(application.submitted_at)) / 1000)
      const expected = suggestion && MATCHING[suggestion]
      if (expected) {
        compared += 1
        if (expected === first.action) matched += 1
      }
    }
  }

  waits.sort((a, b) => a - b)
  const mid = Math.floor(waits.length / 2)
  const median =
    waits.length === 0
      ? null
      : Math.round(
          waits.length % 2 ? (waits[mid] ?? 0) : ((waits[mid - 1] ?? 0) + (waits[mid] ?? 0)) / 2,
        )

  return {
    applications_by_status: byStatus,
    suggested_action_distribution: distribution,
    median_time_to_decision_seconds: median,
    decisions_matching_suggestion_share: compared ? (matched / compared).toFixed(2) : null,
    ...feedbackStats(),
  }
}

function feedbackStats(): Pick<
  Schemas['ManagerStats'],
  'ai_feedback_up_share' | 'ai_feedback_groups'
> {
  const groups = new Map<string, Schemas['AiFeedbackGroup']>()
  for (const row of db.listFeedback()) {
    const key = `${row.prompt_version}|${row.model_id ?? '—'}|${row.source}`
    const group = groups.get(key) ?? {
      prompt_version: row.prompt_version,
      model_id: row.model_id,
      source: row.source,
      total: 0,
      up_count: 0,
      up_share: null,
    }
    group.total += 1
    if (row.verdict === 'UP') group.up_count += 1
    group.up_share = (group.up_count / group.total).toFixed(2)
    groups.set(key, group)
  }
  const shares: Record<string, string> = {}
  for (const [key, group] of groups) if (group.up_share) shares[key] = group.up_share
  return { ai_feedback_up_share: shares, ai_feedback_groups: [...groups.values()] }
}

/* ---------- AI-заключение (#8): в моках — шаблон по расчёту, как replay-фикстура ---------- */

/** Сколько «генерируется» заключение после отправки заявки или запроса нового. */
export const AI_REPORT_DELAY_MS = 3000
const PROMPT_VERSION = 'explain_risk/v1'
const MODEL_ID = 'qwen2.5-7b-instruct'

const rubles = (value: string) => `${new Intl.NumberFormat('ru-RU').format(parseInt(value, 10))} ₽`

const RISK_WORDS: Record<Schemas['RiskLevel'], string> = {
  LOW: 'низкий',
  MODERATE: 'умеренный',
  HIGH: 'высокий',
  VERY_HIGH: 'очень высокий',
}

const FACTOR_TEXT: Record<Schemas['ReasonCode'], (scoring: Schemas['Scoring']) => string> = {
  DSCR_BELOW_ONE: (s) =>
    `DSCR ${s.dscr}: свободного потока ${rubles(s.cfads_monthly_rub ?? '0')} в месяц не хватает на текущие долги и новый платёж`,
  DSCR_BELOW_TARGET: (s) =>
    `DSCR ${s.dscr} ниже целевого 1.25: запас по обслуживанию долга небольшой`,
  CREDIT_HISTORY_SERIOUS: () => 'В БКИ серьёзные просрочки — нужна ручная проверка',
  CREDIT_HISTORY_MINOR: () => 'В БКИ есть небольшие просрочки',
  CREDIT_HISTORY_UNKNOWN: () => 'Кредитной истории нет — опереться можно только на выписку',
  REVENUE_DECLINE: (s) =>
    `Выручка за последние месяцы снизилась на ${Math.abs(parseFloat(s.revenue_change_pct ?? '0')).toFixed(1)} %`,
  REVENUE_SHARP_DECLINE: (s) =>
    `Выручка резко снизилась: ${parseFloat(s.revenue_change_pct ?? '0').toFixed(1)} %`,
  YOUNG_BUSINESS: (s) => `Бизнесу ${s.business_age_months} мес. — меньше двух лет`,
  DSCR_MEETS_TARGET: (s) =>
    `DSCR ${s.dscr}: свободный поток ${rubles(s.cfads_monthly_rub ?? '0')} в месяц покрывает платежи с запасом`,
  CLEAN_CREDIT_HISTORY: () => 'Кредитная история без просрочек',
  REVENUE_STABLE_OR_GROWING: (s) =>
    `Выручка стабильна или растёт: ${parseFloat(s.revenue_change_pct ?? '0') >= 0 ? '+' : ''}${parseFloat(s.revenue_change_pct ?? '0').toFixed(1)} %`,
  ESTABLISHED_BUSINESS: (s) => `Бизнес работает ${Math.floor(s.business_age_months / 12)} г.`,
}

const QUESTIONS: Partial<Record<Schemas['ReasonCode'], string>> = {
  DSCR_BELOW_ONE:
    'Есть ли у компании другие источники дохода, из которых она будет платить по кредиту?',
  DSCR_BELOW_TARGET: 'Готов ли клиент взять меньшую сумму или более долгий срок?',
  CREDIT_HISTORY_SERIOUS: 'Чем вызваны просрочки в кредитной истории и погашены ли они сейчас?',
  CREDIT_HISTORY_MINOR: 'Чем были вызваны небольшие просрочки?',
  REVENUE_DECLINE: 'С чем связано снижение выручки — сезонность или ушли клиенты?',
  REVENUE_SHARP_DECLINE: 'Почему выручка резко упала и когда клиент ждёт восстановления?',
  YOUNG_BUSINESS: 'Есть ли у владельца опыт ведения похожего бизнеса?',
}

function reportBody(
  application: ApplicationRow,
  result: NonNullable<ReturnType<typeof riskFor>>,
): Schemas['AiReportBody'] {
  const { scoring } = result.risk
  const { proposal } = result
  const { company } = facts(application)
  const request = `${company.name} просит ${rubles(application.requested_amount_rub ?? '0')} на ${application.term_months ?? 0} мес.`

  if (proposal.blocking_codes.length > 0) {
    return {
      summary: `${request} Заявку останавливает стоп-фактор — одобрить её нельзя, остаётся отказ с понятной клиенту причиной.`,
      risk_factors: [],
      positive_factors: [],
      manager_questions: [],
    }
  }
  if (scoring.calculation_status === 'SKIPPED' || scoring.dscr === null) {
    return {
      summary: `${request} Расчёт не выполнялся: данных по счёту недостаточно.`,
      risk_factors: [],
      positive_factors: [],
      manager_questions: [],
    }
  }

  const risk = scoring.risk_level ? RISK_WORDS[scoring.risk_level] : '—'
  const verdict = {
    ELIGIBLE_FOR_MANAGER_REVIEW:
      'Показатели проходят пороги — заявку можно одобрять на запрошенных условиях.',
    COUNTER_OFFER_CANDIDATE: `На запрошенных условиях нагрузка высокая; на этот срок компания потянет до ${rubles(scoring.limit_rub ?? '0')} — стоит предложить меньшую сумму.`,
    MANUAL_REVIEW:
      'Автоматическая рекомендация невозможна — посмотрите кредитную историю и выписку.',
    BLOCKED_BY_RULE: '',
  }[proposal.suggested_action]
  const questions = scoring.reason_codes.flatMap((code) => QUESTIONS[code] ?? [])

  return {
    summary: `${request} DSCR ${scoring.dscr}, score ${scoring.score ?? '—'} из 100, риск ${risk}. ${verdict}`,
    risk_factors: scoring.reason_codes.map((code) => ({ code, text: FACTOR_TEXT[code](scoring) })),
    positive_factors: scoring.positive_codes.map((code) => ({
      code,
      text: FACTOR_TEXT[code](scoring),
    })),
    manager_questions: questions.length
      ? questions
      : ['Подтвердите целевое использование: есть ли счёт или договор с поставщиком?'],
  }
}

/**
 * Заключение «готовится» AI_REPORT_DELAY_MS после отправки заявки или запроса нового,
 * затем READY; под `?mock=unavailable` модель недоступна — шаблонный FALLBACK.
 * Состояние зависит только от времени: таймеры не нужны, polling GET увидит смену.
 */
export function aiReportFor(
  application: ApplicationRow,
  result: ReturnType<typeof riskFor> = riskFor(application),
  at: number = Date.now(),
): Schemas['AiReportView'] | null {
  if (!result || !application.submitted_at) return null
  const startedAt = db.aiRegeneratedAt(application.id) ?? application.submitted_at
  const started = Date.parse(startedAt)
  const pending = at < started + AI_REPORT_DELAY_MS
  const disabled = getScenario() === 'unavailable'
  const id = `${application.id.slice(0, 24)}${String(started % 1e12).padStart(12, '0')}`
  return {
    id,
    scoring_result_id: result.risk.scoring.id,
    status: pending ? 'PENDING' : disabled ? 'FALLBACK' : 'READY',
    fallback_reason: !pending && disabled ? 'UNAVAILABLE' : null,
    llm_mode: disabled ? 'disabled' : 'replay',
    model_id: disabled ? null : MODEL_ID,
    prompt_version: PROMPT_VERSION,
    report: pending ? null : reportBody(application, result),
    updated_at: new Date(pending ? started : started + AI_REPORT_DELAY_MS).toISOString(),
  }
}

/* ---------- Предпросмотр встречного предложения (design.md §3.5) ---------- */

type Preview = Schemas['CalculatedOfferPreview'] | Schemas['SkippedOfferPreview']

/**
 * Расчёт на условиях оффера и бизнес-нарушения — та же проверка, что у decisions:
 * пределы продукта, лимит на срок, без смены срока сумма должна уменьшиться.
 */
export function offerPreview(application: ApplicationRow, amount: number, term: number): Preview {
  const product = db.findProduct(application.product_id)
  const result = riskFor(application)
  const requested = requestedTerms(application)
  if (!product || !result || !requested) throw new Error('Предпросмотр без условий заявки')
  const violations: Schemas['OfferViolation'][] = []
  if (!managerActions(application, result).includes('COUNTER_OFFER')) {
    violations.push('ACTION_NOT_ALLOWED')
  }
  const risk = assess(facts(application), { amount, term, product }, 'COUNTER_OFFER')
  const { scoring } = risk
  if (scoring.calculation_status === 'SKIPPED' || !scoring.monthly_payment_rub || !scoring.dscr) {
    return {
      calculation_status: 'SKIPPED',
      dscr: null,
      limit_for_term_rub: null,
      monthly_payment_rub: null,
      risk_level: null,
      score: null,
      valid: false,
      violations: [...violations, 'CALCULATION_SKIPPED'],
    }
  }
  if (amount < parseFloat(product.min_amount_rub) || amount > parseFloat(product.max_amount_rub)) {
    violations.push('AMOUNT_OUT_OF_PRODUCT')
  }
  if (term < product.min_term_months || term > product.max_term_months) {
    violations.push('TERM_OUT_OF_PRODUCT')
  }
  if (scoring.limit_rub === null || amount > parseFloat(scoring.limit_rub)) {
    violations.push('AMOUNT_ABOVE_LIMIT')
  }
  if (term === requested.term_months && amount >= parseFloat(requested.amount_rub)) {
    violations.push('OFFER_NOT_IMPROVED')
  }
  return {
    calculation_status: 'OK',
    dscr: scoring.dscr,
    limit_for_term_rub: scoring.limit_rub,
    monthly_payment_rub: scoring.monthly_payment_rub,
    risk_level: scoring.risk_level ?? 'VERY_HIGH',
    score: scoring.score ?? 0,
    valid: violations.length === 0,
    violations,
  }
}
