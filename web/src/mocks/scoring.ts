import type { components } from '@/api/schema.d.ts'
import { formatKopecks } from './finance.ts'

/*
 * Финансовый конвейер «бэкенда» моков: признаки выписки, RiskEngine и DecisionPolicy
 * по формулам design.md §3.4. Исходные данные — помесячные агрегаты из docs/demo-data.md
 * §3 (ветка #6), а не операции выписки: категоризацию моки не повторяют.
 * Только для MSW: интерфейс ничего из этого не считает, а показывает ответ API.
 * Внутри — number: для демо-сумм точности хватает, наружу — строки, как у API.
 */

type Schemas = components['schemas']

export const AS_OF_DATE = '2026-10-21'
const TARGET_DSCR = 1.25
/** Окно выписки — 12 полных месяцев до месяца AS_OF_DATE: 2025-10 … 2026-09. */
const WINDOW_MONTHS = 12

interface CompanyData {
  /** Выручка за месяцы окна 1–6 и 7–12. */
  revenue: [number, number]
  /** net = revenue − opex: одно число на все месяцы или по месяцам 7–12 (C2). */
  net: number | { first: number; last: number[] }
  debtSvc: number
  bki: { status: 'CLEAN' | 'UNKNOWN' | 'MINOR' | 'SERIOUS'; payments: number }
  fns: { bankruptcy: boolean; blocks: number }
  /** Месяцев истории по счёту (h ≤ 12): операции в последних h месяцах окна. */
  history: number
}

/** docs/demo-data.md §3. Реестр (статус, регистрация) — в db.ts. */
export const COMPANY_DATA: Record<string, CompanyData> = {
  '0099010012': {
    revenue: [1_000_000, 1_050_000],
    net: 400_000,
    debtSvc: 50_000,
    bki: { status: 'CLEAN', payments: 50_000 },
    fns: { bankruptcy: false, blocks: 0 },
    history: 12,
  },
  '0099020010': {
    revenue: [1_000_000, 920_000],
    net: { first: 240_000, last: [238_000, 250_000, 230_000, 242_000, 235_000, 245_000] },
    debtSvc: 100_000,
    bki: { status: 'CLEAN', payments: 100_000 },
    fns: { bankruptcy: false, blocks: 0 },
    history: 12,
  },
  '009903001040': {
    revenue: [800_000, 824_000],
    net: 300_000,
    debtSvc: 0,
    bki: { status: 'SERIOUS', payments: 0 },
    fns: { bankruptcy: false, blocks: 0 },
    history: 12,
  },
  '0099040017': {
    revenue: [300_000, 300_000],
    net: 50_000,
    debtSvc: 0,
    bki: { status: 'CLEAN', payments: 0 },
    fns: { bankruptcy: false, blocks: 0 },
    history: 4,
  },
  '0099050015': {
    revenue: [500_000, 500_000],
    net: 100_000,
    debtSvc: 0,
    bki: { status: 'CLEAN', payments: 0 },
    fns: { bankruptcy: false, blocks: 0 },
    history: 12,
  },
  '0099060013': {
    revenue: [500_000, 500_000],
    net: 100_000,
    debtSvc: 0,
    bki: { status: 'CLEAN', payments: 0 },
    fns: { bankruptcy: false, blocks: 2 },
    history: 12,
  },
  '009907001027': {
    revenue: [600_000, 600_000],
    net: 120_000,
    debtSvc: 100_000,
    bki: { status: 'CLEAN', payments: 100_000 },
    fns: { bankruptcy: false, blocks: 0 },
    history: 12,
  },
}

export interface ProductTerms {
  min_amount_rub: string
  max_amount_rub: string
  min_term_months: number
  max_term_months: number
  annual_rate_pct: string
}

export interface CompanyFacts {
  inn: string
  registered_at: string
  registry_status: 'ACTIVE' | 'LIQUIDATING' | 'LIQUIDATED'
}

const rub = (value: number) => formatKopecks(Math.round(value * 100))

function windowMonths(): string[] {
  return Array.from({ length: WINDOW_MONTHS }, (_, i) => {
    const date = new Date(Date.UTC(2025, 9 + i, 1))
    return date.toISOString().slice(0, 10)
  })
}

/** Помесячные ряды выписки; месяцы до начала истории не попадают в ряд. */
export function monthlySeries(data: CompanyData): Schemas['MonthlyFeature'][] {
  return windowMonths()
    .map((month, i) => {
      const revenue = data.revenue[i < 6 ? 0 : 1]
      const net =
        typeof data.net === 'number'
          ? data.net
          : i < 6
            ? data.net.first
            : (data.net.last[i - 6] ?? 0)
      return {
        month,
        revenue_rub: rub(revenue),
        opex_rub: rub(revenue - net),
        debt_svc_rub: rub(data.debtSvc),
      }
    })
    .slice(WINDOW_MONTHS - data.history)
}

function median(values: number[]) {
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? (sorted[mid] ?? 0) : ((sorted[mid - 1] ?? 0) + (sorted[mid] ?? 0)) / 2
}

/** Полные месяцы от регистрации до AS_OF_DATE. */
export function monthsBetween(from: string, to: string = AS_OF_DATE) {
  const [fy = 0, fm = 0, fd = 0] = from.split('-').map((part) => parseInt(part, 10))
  const [ty = 0, tm = 0, td = 0] = to.split('-').map((part) => parseInt(part, 10))
  return (ty - fy) * 12 + (tm - fm) - (td < fd ? 1 : 0)
}

function annuity(annualRatePct: string, months: number) {
  const r = parseFloat(annualRatePct) / 1200
  return r === 0 ? 1 / months : r / (1 - (1 + r) ** -months)
}

/** DSCR с двумя знаками через ROUND_DOWN: 0,99218… → «0.99», не «1.00». */
function showDscr(value: number) {
  return (Math.floor(value * 100 + 1e-9) / 100).toFixed(2)
}

export function stopFactors(facts: CompanyFacts, data: CompanyData | undefined) {
  const codes: Schemas['StopFactor'][] = []
  if (facts.registry_status !== 'ACTIVE') codes.push('COMPANY_INACTIVE')
  if (data?.fns.bankruptcy) codes.push('BANKRUPTCY_PROCEEDING')
  if (data && data.fns.blocks > 0) codes.push('ACCOUNT_BLOCKED_BY_FNS')
  if (!data || data.history < 6) codes.push('ACCOUNT_HISTORY_INSUFFICIENT')
  return codes
}

export interface RiskResult {
  scoring: Schemas['Scoring']
  /** Неокруглённый DSCR — пороги сравниваются по нему. */
  dscrRaw: number | null
  bkiStatus: CompanyData['bki']['status'] | null
}

/** Лимит на срок: вниз до 10 000 ₽, null вне продукта или ниже минимальной суммы. */
export function limitForTerm(pMax: number, term: number, product: ProductTerms) {
  if (term < product.min_term_months || term > product.max_term_months) return null
  const max = parseFloat(product.max_amount_rub)
  const limit = Math.floor(Math.min(pMax / annuity(product.annual_rate_pct, term), max) / 10_000)
  const value = limit * 10_000
  return value < parseFloat(product.min_amount_rub) ? null : value
}

/** RiskEngine: расчёт на условиях `amount` / `term`. */
export function assess(
  facts: CompanyFacts,
  terms: { amount: number; term: number; product: ProductTerms },
  kind: Schemas['Scoring']['kind'] = 'SUBMISSION',
): RiskResult {
  const data = COMPANY_DATA[facts.inn]
  const monthly = data ? monthlySeries(data) : []
  const h = data?.history ?? 0
  const k = Math.floor(h / 2)
  const age = monthsBetween(facts.registered_at)
  const revenues = monthly.map((item) => parseFloat(item.revenue_rub))
  const nets = monthly.map((item, i) => (revenues[i] ?? 0) - parseFloat(item.opex_rub))
  const debtSvc = monthly.map((item) => parseFloat(item.debt_svc_rub))
  const recentDebt = debtSvc.slice(-3)
  const debt = Math.max(
    recentDebt.length ? recentDebt.reduce((a, b) => a + b, 0) / recentDebt.length : 0,
    data?.bki.payments ?? 0,
  )
  const base = revenues.slice(-2 * k, -k).reduce((a, b) => a + b, 0)
  const common = {
    id: crypto.randomUUID(),
    kind,
    engine_version: 'risk-1.0.0',
    inputs_hash: '0'.repeat(64),
    existing_debt_payments_rub: rub(debt),
    business_age_months: age,
    account_history_months: h,
    monthly,
  }

  if (!data || h < 6 || base === 0) {
    return {
      dscrRaw: null,
      bkiStatus: data?.bki.status ?? null,
      scoring: {
        ...common,
        calculation_status: 'SKIPPED',
        monthly_payment_rub: null,
        dscr: null,
        score: null,
        factor_points: null,
        risk_level: null,
        reason_codes: [],
        positive_codes: [],
        limit_rub: null,
        cfads_monthly_rub: null,
        revenue_change_pct: null,
      },
    }
  }

  const cfads = median(nets.slice(-Math.min(6, h)))
  const revenueChange = (revenues.slice(-k).reduce((a, b) => a + b, 0) / base - 1) * 100
  const payment = terms.amount * annuity(terms.product.annual_rate_pct, terms.term)
  const dscr = cfads / (debt + payment)
  const pMax = Math.max(0, cfads / TARGET_DSCR - debt)
  const limit = limitForTerm(pMax, terms.term, terms.product)

  const reasons: Schemas['ReasonCode'][] = []
  const positives: Schemas['ReasonCode'][] = []
  const points = { dscr: 0, bki: 0, revenue: 0, age: 0 }

  if (dscr >= 1.5) points.dscr = 40
  else if (dscr >= TARGET_DSCR) points.dscr = 30
  else if (dscr >= 1) points.dscr = 10
  if (dscr < 1) reasons.push('DSCR_BELOW_ONE')
  else if (dscr < TARGET_DSCR) reasons.push('DSCR_BELOW_TARGET')
  else positives.push('DSCR_MEETS_TARGET')

  const bki = data.bki.status
  points.bki = { CLEAN: 30, UNKNOWN: 15, MINOR: 10, SERIOUS: 0 }[bki]
  if (bki === 'CLEAN') positives.push('CLEAN_CREDIT_HISTORY')
  else reasons.push(`CREDIT_HISTORY_${bki}`)

  if (revenueChange >= 0) {
    points.revenue = 15
    positives.push('REVENUE_STABLE_OR_GROWING')
  } else if (revenueChange >= -15) {
    points.revenue = 8
    reasons.push('REVENUE_DECLINE')
  } else {
    reasons.push('REVENUE_SHARP_DECLINE')
  }

  if (age >= 24) {
    points.age = 15
    positives.push('ESTABLISHED_BUSINESS')
  } else {
    points.age = age >= 12 ? 8 : 0
    reasons.push('YOUNG_BUSINESS')
  }

  const score = points.dscr + points.bki + points.revenue + points.age
  let risk: Schemas['RiskLevel'] =
    score >= 80 ? 'LOW' : score >= 60 ? 'MODERATE' : score >= 40 ? 'HIGH' : 'VERY_HIGH'
  if (dscr < 1 && (risk === 'LOW' || risk === 'MODERATE')) risk = 'HIGH'

  return {
    dscrRaw: dscr,
    bkiStatus: bki,
    scoring: {
      ...common,
      calculation_status: 'OK',
      monthly_payment_rub: rub(payment),
      dscr: showDscr(dscr),
      score,
      factor_points: points,
      risk_level: risk,
      reason_codes: reasons,
      positive_codes: positives,
      limit_rub: limit === null ? null : rub(limit),
      cfads_monthly_rub: rub(cfads),
      revenue_change_pct: revenueChange.toFixed(2),
    },
  }
}

/** DecisionPolicy: первое сработавшее правило задаёт рекомендацию, в trace — все пять. */
export function propose(risk: RiskResult, blocking: Schemas['StopFactor'][]): Schemas['Proposal'] {
  const { dscrRaw, bkiStatus, scoring } = risk
  const dscrText = scoring.dscr ?? '—'
  const rules: [Schemas['RuleTraceItem']['rule'], boolean, string, Schemas['SuggestedAction']][] = [
    [
      'R1',
      blocking.length > 0,
      blocking.length > 0 ? `Стоп-факторы: ${blocking.join(', ')}` : 'Стоп-факторов нет',
      'BLOCKED_BY_RULE',
    ],
    ['R2', bkiStatus === 'SERIOUS', `БКИ: ${bkiStatus ?? 'нет данных'}`, 'MANUAL_REVIEW'],
    [
      'R3',
      dscrRaw !== null && dscrRaw < TARGET_DSCR && scoring.limit_rub !== null,
      `DSCR ${dscrText}, лимит ${scoring.limit_rub ?? 'нет'}`,
      'COUNTER_OFFER_CANDIDATE',
    ],
    [
      'R4',
      dscrRaw !== null && dscrRaw >= TARGET_DSCR && (scoring.score ?? 0) >= 80,
      `DSCR ${dscrText}, score ${scoring.score ?? '—'}`,
      'ELIGIBLE_FOR_MANAGER_REVIEW',
    ],
    ['R5', true, 'Остальные случаи', 'MANUAL_REVIEW'],
  ]
  const first = rules.find(([, matched]) => matched)
  return {
    policy_version: 'policy-1.0.0',
    blocking_codes: blocking,
    suggested_action: first?.[3] ?? 'MANUAL_REVIEW',
    rule_trace: rules.map(([rule, matched, detail]) => ({ rule, matched, detail })),
  }
}

/** Сводки внешних источников для карточки менеджера — поля как у снимков ext-sim в API #7. */
export function externalSources(
  facts: CompanyFacts & {
    legal_form: 'LLC' | 'IE'
    director: { full_name: string; inn: string }
  },
  fetchedAt: string,
): Schemas['ExternalSource'][] {
  const data = COMPANY_DATA[facts.inn]
  const sources: Schemas['ExternalSource'][] = [
    {
      provider: facts.legal_form === 'IE' ? 'EGRIP' : 'EGRUL',
      fetched_at: fetchedAt,
      summary: { status: facts.registry_status, director: { ...facts.director } },
    },
  ]
  if (!data) return sources
  sources.push(
    {
      provider: 'FNS',
      fetched_at: fetchedAt,
      summary: { bankruptcy: data.fns.bankruptcy, active_account_blocks: data.fns.blocks },
    },
    {
      provider: 'BKI',
      fetched_at: fetchedAt,
      summary: {
        summary_status: data.bki.status,
        obligations:
          data.bki.payments > 0
            ? [
                {
                  creditor_name: 'АО «Демо-Банк»',
                  outstanding_rub: rub(data.bki.payments * 24),
                  monthly_payment_rub: rub(data.bki.payments),
                },
              ]
            : [],
        monthly_payments_total_rub: rub(data.bki.payments),
      },
    },
    {
      provider: 'BANK',
      fetched_at: fetchedAt,
      summary: {
        account_masked: `40702 •••• ${facts.inn.slice(-4)}`,
        from: '2025-10-01',
        to: '2026-09-30',
        transactions_count: data.history * 21,
      },
    },
  )
  return sources
}
