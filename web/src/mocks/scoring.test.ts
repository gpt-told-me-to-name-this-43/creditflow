import { describe, expect, it } from 'vitest'
import { db } from './db.ts'
import { assess, COMPANY_DATA, propose, stopFactors } from './scoring.ts'

// Эталоны — ручной расчёт docs/demo-data.md §5 (ветка #6) на запрошенных условиях.
function run(inn: string, amount: number, term: number, productId: string) {
  const registry = db.findRegistry(inn)
  const product = db.findProduct(productId)
  if (!registry || !product) throw new Error(inn)
  const facts = { inn, registered_at: registry.registered_at, registry_status: registry.status }
  const risk = assess(facts, { amount, term, product })
  return { ...risk.scoring, proposal: propose(risk, stopFactors(facts, COMPANY_DATA[inn])) }
}

describe('мок-расчёт по эталонам demo-data', () => {
  it('C1 «ТехСервис»: DSCR 3.11, score 100, одобрение', () => {
    const result = run('0099010012', 2_000_000, 36, 'investment')
    expect(result).toMatchObject({
      monthly_payment_rub: '78465.71',
      dscr: '3.11',
      score: 100,
      risk_level: 'LOW',
      limit_rub: '5000000.00',
      cfads_monthly_rub: '400000.00',
      revenue_change_pct: '5.00',
      business_age_months: 60,
    })
    expect(result.proposal.suggested_action).toBe('ELIGIBLE_FOR_MANAGER_REVIEW')
  })

  it('C2 «Пекарня Плюс»: DSCR 1.10, score 63 = 10 + 30 + 8 + 15, лимит 2 340 000', () => {
    const result = run('0099020010', 3_000_000, 36, 'investment')
    expect(result).toMatchObject({
      monthly_payment_rub: '117698.56',
      dscr: '1.10',
      score: 63,
      factor_points: { dscr: 10, bki: 30, revenue: 8, age: 15 },
      risk_level: 'MODERATE',
      limit_rub: '2340000.00',
      cfads_monthly_rub: '240000.00',
      revenue_change_pct: '-8.00',
      reason_codes: ['DSCR_BELOW_TARGET', 'REVENUE_DECLINE'],
      positive_codes: ['CLEAN_CREDIT_HISTORY', 'ESTABLISHED_BUSINESS'],
    })
    expect(result.proposal.suggested_action).toBe('COUNTER_OFFER_CANDIDATE')
    expect(
      result.proposal.rule_trace.filter((item) => item.matched).map((item) => item.rule),
    ).toEqual(['R3', 'R5'])
  })

  it('C3 Соколова: БКИ SERIOUS — ручное рассмотрение при высоком DSCR', () => {
    const result = run('009903001040', 800_000, 12, 'working_capital')
    expect(result).toMatchObject({ monthly_payment_rub: '76035.36', dscr: '3.94', score: 70 })
    expect(result.limit_rub).toBe('2520000.00')
    expect(result.proposal.suggested_action).toBe('MANUAL_REVIEW')
  })

  it('C4 «Новый Старт»: 4 месяца истории — расчёт пропущен, стоп-фактор', () => {
    const result = run('0099040017', 500_000, 24, 'investment')
    expect(result).toMatchObject({
      calculation_status: 'SKIPPED',
      dscr: null,
      score: null,
      account_history_months: 4,
    })
    expect(result.monthly).toHaveLength(4)
    expect(result.proposal).toMatchObject({
      suggested_action: 'BLOCKED_BY_RULE',
      blocking_codes: ['ACCOUNT_HISTORY_INSUFFICIENT'],
    })
  })

  it('C5 и C6: компания в ликвидации, блокировки ФНС — стоп-факторы', () => {
    expect(run('0099050015', 1_000_000, 12, 'working_capital').proposal.blocking_codes).toEqual([
      'COMPANY_INACTIVE',
    ])
    const c6 = run('0099060013', 1_500_000, 18, 'working_capital')
    expect(c6.dscr).toBe('0.99')
    expect(c6.risk_level).toBe('HIGH')
    expect(c6.proposal.blocking_codes).toEqual(['ACCOUNT_BLOCKED_BY_FNS'])
  })

  it('C7 Орлов: DSCR 0.86, лимита нет — ручное рассмотрение', () => {
    const result = run('009907001027', 1_000_000, 36, 'investment')
    expect(result).toMatchObject({ dscr: '0.86', score: 60, risk_level: 'HIGH', limit_rub: null })
    expect(result.proposal.suggested_action).toBe('MANUAL_REVIEW')
  })
})
