import { describe, expect, it } from 'vitest'
import { buildSchedule, formatKopecks, monthlyPayment, overpayment, toKopecks } from './finance.ts'

describe('расчёты моков', () => {
  it('копейки туда и обратно', () => {
    expect(toKopecks('2340000.00')).toBe(234_000_000)
    expect(toKopecks('0.5')).toBe(50)
    expect(toKopecks(3_000_000)).toBe(300_000_000)
    expect(formatKopecks(9_180_488)).toBe('91804.88')
    expect(formatKopecks(-5)).toBe('-0.05')
  })

  // Эталоны из docs/demo-data.md (ветка #6).
  it.each([
    [2_000_000, 36, '24.00', '78465.71'],
    [3_000_000, 36, '24.00', '117698.56'],
    [2_340_000, 36, '24.00', '91804.88'],
    [800_000, 12, '25.00', '76035.36'],
    [1_500_000, 18, '25.00', '100787.72'],
  ])('платёж %i ₽ / %i мес. под %s%% = %s', (amount, term, rate, expected) => {
    expect(formatKopecks(monthlyPayment(toKopecks(amount), term, rate))).toBe(expected)
  })

  it('график гасит долг полностью', () => {
    const schedule = buildSchedule(toKopecks(2_340_000), 36, '24.00', '2026-10-21')
    expect(schedule).toHaveLength(36)
    expect(schedule[0]).toMatchObject({
      number: 1,
      due_date: '2026-11-21',
      payment_rub: '91804.88',
    })
    expect(schedule.at(-1)?.balance_after_rub).toBe('0.00')
    const principal = schedule.reduce((sum, item) => sum + toKopecks(item.principal_rub), 0)
    expect(principal).toBe(toKopecks(2_340_000))
    expect(toKopecks(overpayment(schedule))).toBeGreaterThan(0)
  })
})
