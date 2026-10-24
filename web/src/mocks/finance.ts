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

/*
 * Повторяем серверный Decimal (api/app/scoring/money.py): каждая операция округляется
 * до 34 значащих цифр (ROUND_HALF_EVEN), деньги — до копейки ROUND_HALF_UP.
 * Число — дробь num/den на BigInt; float не участвует, иначе на «половинках копейки»
 * и в последнем платеже моки расходятся с сервером.
 */
const PREC = 34n
type Ratio = { num: bigint; den: bigint }

const abs = (n: bigint) => (n < 0n ? -n : n)
const ratio = (num: bigint, den = 1n): Ratio => (den < 0n ? { num: -num, den: -den } : { num, den })

function parseDecimal(value: string): Ratio {
  const [whole = '0', fraction = ''] = value.split('.')
  return ratio(BigInt(whole + fraction), 10n ** BigInt(fraction.length))
}

/** Округление до 34 значащих цифр, как контекст Decimal(prec=34). */
function context(x: Ratio): Ratio {
  if (x.num === 0n) return ratio(0n)
  const n = abs(x.num)
  let shift = BigInt(PREC) - BigInt((n / x.den).toString().length)
  if (n < x.den) {
    // |x| < 1: считаем ведущие нули дробной части
    let lead = 0n
    for (let probe = n * 10n; probe < x.den; probe *= 10n) lead += 1n
    shift = PREC + lead
  }
  const scale = (k: bigint) => (k >= 0n ? [n * 10n ** k, x.den] : [n, x.den * 10n ** -k])
  const [num, den] = scale(shift) as [bigint, bigint]
  let q = num / den
  const twice = (num % den) * 2n
  if (twice > den || (twice === den && q % 2n === 1n)) q += 1n
  const sign = x.num < 0n ? -1n : 1n
  return shift >= 0n ? ratio(sign * q, 10n ** shift) : ratio(sign * q * 10n ** -shift)
}

const add = (a: Ratio, b: Ratio) => context(ratio(a.num * b.den + b.num * a.den, a.den * b.den))
const sub = (a: Ratio, b: Ratio) => add(a, ratio(-b.num, b.den))
const mul = (a: Ratio, b: Ratio) => context(ratio(a.num * b.num, a.den * b.den))
const div = (a: Ratio, b: Ratio) => context(ratio(a.num * b.den, a.den * b.num))
/** a^−n: точная степень и одно округление — как Decimal ** int. */
const powNeg = (a: Ratio, n: number) => context(ratio(a.den ** BigInt(n), a.num ** BigInt(n)))

/** round_money: до копейки ROUND_HALF_UP (половина — от нуля). */
function toCents(x: Ratio): number {
  const num = abs(x.num) * 100n
  let q = num / x.den
  if ((num % x.den) * 2n >= x.den) q += 1n
  return Number(x.num < 0n ? -q : q)
}

const fromKopecks = (kopecks: number) => ratio(BigInt(kopecks), 100n)
const monthlyRate = (annualRatePct: string) => div(parseDecimal(annualRatePct), ratio(1200n))

/** Платёж P = round_half_up(S · r / (1 − (1 + r)^−n)); при 0% — S / n. */
export function monthlyPayment(amountKopecks: number, termMonths: number, annualRatePct: string) {
  const r = monthlyRate(annualRatePct)
  const factor =
    r.num === 0n
      ? div(ratio(1n), ratio(BigInt(termMonths)))
      : div(r, sub(ratio(1n), powNeg(add(ratio(1n), r), termMonths)))
  return toCents(mul(fromKopecks(amountKopecks), factor))
}

/** Всегда от исходной даты, а не от предыдущего платежа: 31.01 → 28/29.02 → 31.03. */
function addMonths(isoDate: string, months: number) {
  const [year = 0, month = 1, day = 1] = isoDate.split('-').map(Number)
  const target = new Date(Date.UTC(year, month - 1 + months, 1))
  const lastDay = new Date(
    Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0),
  ).getUTCDate()
  target.setUTCDate(Math.min(day, lastDay))
  return target.toISOString().slice(0, 10)
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
    const interest = toCents(mul(fromKopecks(balance), r))
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
