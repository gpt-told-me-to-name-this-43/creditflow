import type { components } from '@/api/schema.d.ts'

/*
 * Расчёты «бэкенда» моков: аннуитетный платёж и график по формулам design.md §3.4.
 * Только для MSW — интерфейс платежи и переплату не считает, а показывает ответ API.
 * Суммы внутри — целые копейки (number безопасен до 2^53), наружу — строки «123.45».
 */

type ScheduleItem = components['schemas']['ScheduleItem']

/** «3000000.00» или 3000000 (целые рубли из запроса) → копейки. */
export function toKopecks(rub: string | number): number {
  if (typeof rub === 'number') return rub * 100
  const [whole = '0', fraction = ''] = rub.split('.')
  return parseInt(whole, 10) * 100 + parseInt(fraction.padEnd(2, '0').slice(0, 2), 10)
}

export function formatKopecks(kopecks: number): string {
  const sign = kopecks < 0 ? '-' : ''
  const abs = Math.abs(kopecks)
  return `${sign}${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, '0')}`
}

function monthlyRate(annualRatePct: string) {
  return toKopecks(annualRatePct) / 100 / 1200
}

/** Платёж P = S · r / (1 − (1 + r)^−n), округление до копейки. */
export function monthlyPayment(amountKopecks: number, termMonths: number, annualRatePct: string) {
  const r = monthlyRate(annualRatePct)
  const factor = r === 0 ? 1 / termMonths : r / (1 - (1 + r) ** -termMonths)
  return Math.round(amountKopecks * factor)
}

function addMonths(isoDate: string, months: number) {
  const date = new Date(`${isoDate}T00:00:00Z`)
  date.setUTCMonth(date.getUTCMonth() + months)
  return date.toISOString().slice(0, 10)
}

/** График: последний платёж закрывает остаток до копейки. */
export function buildSchedule(
  amountKopecks: number,
  termMonths: number,
  annualRatePct: string,
  startDate: string,
): ScheduleItem[] {
  const r = monthlyRate(annualRatePct)
  const payment = monthlyPayment(amountKopecks, termMonths, annualRatePct)
  let balance = amountKopecks
  return Array.from({ length: termMonths }, (_, i) => {
    const interest = Math.round(balance * r)
    const isLast = i === termMonths - 1
    const principal = isLast ? balance : payment - interest
    balance -= principal
    return {
      number: i + 1,
      due_date: addMonths(startDate, i + 1),
      payment_rub: formatKopecks(principal + interest),
      principal_rub: formatKopecks(principal),
      interest_rub: formatKopecks(interest),
      balance_after_rub: formatKopecks(balance),
    }
  })
}

export function overpayment(schedule: readonly ScheduleItem[]) {
  return formatKopecks(schedule.reduce((sum, item) => sum + toKopecks(item.interest_rub), 0))
}
