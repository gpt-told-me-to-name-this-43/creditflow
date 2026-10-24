import { describe, expect, it } from 'vitest'
import { buildSchedule, formatKopecks, monthlyPayment, overpayment, toKopecks } from './finance.ts'
import serverSchedules from './fixtures/server-schedules.json'

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

/*
 * Эталоны — вывод серверного api/app/scoring/schedule.py (Decimal, prec=34, ROUND_HALF_UP).
 * Пересобрать:
 * build_schedule(Decimal(amount), Decimal(rate), term, date.fromisoformat(start)).
 */
describe('моки совпадают с серверным Decimal', () => {
  it.each(
    serverSchedules.map((c) => [`${c.amount} ₽ / ${c.term} мес. / ${c.rate}% с ${c.start}`, c]),
  )('%s', (_, c) => {
    const schedule = buildSchedule(toKopecks(c.amount), c.term, c.rate, c.start)
    expect(schedule).toEqual(c.schedule)
    expect(overpayment(schedule)).toBe(c.overpayment)
    expect(formatKopecks(monthlyPayment(toKopecks(c.amount), c.term, c.rate))).toBe(
      c.schedule[0]?.payment_rub,
    )
  })

  it.each([
    ['2026-01-29', ['2026-02-28', '2026-03-29', '2026-04-29']],
    ['2026-01-30', ['2026-02-28', '2026-03-30', '2026-04-30']],
    ['2026-01-31', ['2026-02-28', '2026-03-31', '2026-04-30']],
    ['2024-01-29', ['2024-02-29', '2024-03-29', '2024-04-29']],
    ['2024-01-31', ['2024-02-29', '2024-03-31', '2024-04-30']],
  ])('даты платежей от %s: исходное число, не больше конца месяца', (start, expected) => {
    const dates = buildSchedule(toKopecks(300_000), 3, '25', start).map((item) => item.due_date)
    expect(dates).toEqual(expected)
  })
})
