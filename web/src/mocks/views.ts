import type { ApplicationStatus, PurposeCode } from '@/api/enums.ts'
import type { components } from '@/api/schema.d.ts'
import {
  type ApplicationRow,
  type CompanyRow,
  type CreditProductRow,
  db,
  requestedTerms,
  type TermsRow,
  type UserRow,
} from './db.ts'
import { buildSchedule, formatKopecks, monthlyPayment, overpayment, toKopecks } from './finance.ts'

/* Ответы API из записей db: только публичные DTO из schema.d.ts, без внутренних полей. */

type Schemas = components['schemas']

export const PRODUCT_DISCLAIMER = 'Расчёт предварительный и не является решением банка'

/** Какие действия бэк разрешает клиенту в каждом статусе (кнопки — только по этому списку). */
const CLIENT_ACTIONS: Record<ApplicationStatus, Schemas['ClientAction'][]> = {
  DRAFT: ['EDIT', 'INTERPRET', 'SUBMIT'],
  UNDER_REVIEW: [],
  NEED_INFO: ['RESPOND_INFO'],
  COUNTER_OFFER: ['ACCEPT_OFFER', 'DECLINE_OFFER'],
  APPROVED: ['VIEW_CONTRACT', 'REQUEST_SIGN_CODE', 'SIGN'],
  SIGNED: ['VIEW_CONTRACT'],
  ISSUED: ['VIEW_CONTRACT'],
  REJECTED: [],
  DECLINED: [],
}

function quote(terms: TermsRow) {
  const amount = toKopecks(terms.amount_rub)
  const schedule = buildSchedule(amount, terms.term_months, terms.annual_rate_pct, '2000-01-01')
  return {
    monthly_payment_rub: formatKopecks(
      monthlyPayment(amount, terms.term_months, terms.annual_rate_pct),
    ),
    overpayment_rub: overpayment(schedule),
  }
}

/** Источник условий выводит бэк: LLM_CONFIRMED → RULES_CONFIRMED → MANUAL (docs/api.md). */
export function termsSource(application: ApplicationRow): Schemas['TermsSource'] {
  const sources = Object.values(application.terms_field_sources)
  if (sources.includes('LLM')) return 'LLM_CONFIRMED'
  if (sources.includes('RULES')) return 'RULES_CONFIRMED'
  return 'MANUAL'
}

export function toMe(user: UserRow): Schemas['Me'] {
  return { id: user.id, full_name: user.full_name, role: user.role, company_id: user.company_id }
}

export function toDemoAccount(user: UserRow, password: string): Schemas['DemoAccount'] {
  return {
    label: user.full_name,
    login: user.email,
    password,
    role: user.role,
    scenario: user.scenario,
  }
}

export function toCompany(company: CompanyRow): Schemas['Company'] {
  return { ...company }
}

export function toClientView(application: ApplicationRow): Schemas['ClientApplicationView'] {
  const terms = requestedTerms(application)
  const requested = terms && quote(terms)
  const offer = application.offer && { ...application.offer, ...quote(application.offer) }
  return {
    id: application.id,
    status: application.status,
    revision: application.revision,
    allowed_actions: CLIENT_ACTIONS[application.status],
    purpose_text: application.purpose_text,
    purpose_code: application.purpose_code,
    requested_amount_rub: application.requested_amount_rub,
    term_months: application.term_months,
    product_id: application.product_id,
    terms_field_sources: { ...application.terms_field_sources },
    terms_source: termsSource(application),
    annual_rate_pct: terms?.annual_rate_pct ?? null,
    monthly_payment_rub: requested?.monthly_payment_rub ?? null,
    overpayment_rub: requested?.overpayment_rub ?? null,
    submitted_at: application.submitted_at,
    client_reason_code: application.status === 'REJECTED' ? application.client_reason_code : null,
    info_request: application.info_request && { ...application.info_request },
    offer,
    timeline: db.listEvents(application.id).map(({ from_status, to_status, created_at }) => ({
      from_status,
      to_status,
      created_at,
    })),
  }
}

export interface ProductQuery {
  purpose?: PurposeCode
  amount?: number
  term?: number
}

export function unmetConstraints(
  product: CreditProductRow,
  { purpose, amount, term }: ProductQuery,
) {
  const unmet: Schemas['ProductConstraint'][] = []
  if (purpose && !product.allowed_purposes.includes(purpose)) unmet.push('PURPOSE_NOT_ALLOWED')
  if (amount !== undefined) {
    const kopecks = toKopecks(amount)
    if (kopecks < toKopecks(product.min_amount_rub)) unmet.push('AMOUNT_BELOW_PRODUCT_MIN')
    if (kopecks > toKopecks(product.max_amount_rub)) unmet.push('AMOUNT_ABOVE_PRODUCT_MAX')
  }
  if (term !== undefined) {
    if (term < product.min_term_months) unmet.push('TERM_BELOW_PRODUCT_MIN')
    if (term > product.max_term_months) unmet.push('TERM_ABOVE_PRODUCT_MAX')
  }
  return unmet
}

export function toProduct(
  product: CreditProductRow,
  query: ProductQuery,
): Schemas['CreditProduct'] {
  const unmet = unmetConstraints(product, query)
  const suitable = unmet.length === 0
  const payment =
    suitable && query.amount !== undefined && query.term !== undefined
      ? formatKopecks(monthlyPayment(toKopecks(query.amount), query.term, product.annual_rate_pct))
      : null
  return {
    ...product,
    disclaimer: PRODUCT_DISCLAIMER,
    suitable,
    unmet_constraints: unmet,
    monthly_payment_rub: payment,
  }
}

export function toContract(application: ApplicationRow): Schemas['ContractView'] {
  const contract = application.contract
  if (!contract) throw new Error('Договора ещё нет')
  const amount = toKopecks(contract.amount_rub)
  const schedule = buildSchedule(
    amount,
    contract.term_months,
    contract.annual_rate_pct,
    contract.approved_at.slice(0, 10),
  )
  const status =
    application.status === 'ISSUED'
      ? 'ISSUED'
      : application.status === 'SIGNED'
        ? 'SIGNED'
        : 'DRAFT'
  return {
    number: contract.number,
    status,
    amount_rub: contract.amount_rub,
    term_months: contract.term_months,
    annual_rate_pct: contract.annual_rate_pct,
    monthly_payment_rub: formatKopecks(
      monthlyPayment(amount, contract.term_months, contract.annual_rate_pct),
    ),
    overpayment_rub: overpayment(schedule),
    account_masked: '40702 •••• 4821',
    signed_at: application.signed_at,
    issued_at: application.issued_at,
    schedule,
    key_terms_markdown: [
      '- Платёж каждый месяц одинаковый, в дату из графика.',
      '- Досрочно погасить можно в любой день без комиссии.',
      '- При просрочке начисляется неустойка 0,1% от суммы просроченного платежа в день.',
    ].join('\n'),
  }
}
