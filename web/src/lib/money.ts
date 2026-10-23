// Деньги приходят из API строками с двумя знаками ("2340000.00"). Арифметика только
// в копейках через BigInt: никаких parseFloat/Number — иначе теряются копейки.

const MONEY_RE = /^(-)?(\d+)(?:\.(\d{1,2}))?$/
const NBSP = ' '
const MINUS = '−'

export function toKopecks(value: string): bigint {
  const match = MONEY_RE.exec(value.trim())
  if (!match) throw new Error(`Некорректная сумма: ${value}`)
  const [, sign, rubles = '0', kopecks = ''] = match
  const total = BigInt(rubles) * 100n + BigInt(kopecks.padEnd(2, '0'))
  return sign ? -total : total
}

export function fromKopecks(total: bigint): string {
  const abs = total < 0n ? -total : total
  const kopecks = (abs % 100n).toString().padStart(2, '0')
  return `${total < 0n ? '-' : ''}${abs / 100n}.${kopecks}`
}

export function compareMoney(a: string, b: string): -1 | 0 | 1 {
  const diff = toKopecks(a) - toKopecks(b)
  return diff === 0n ? 0 : diff > 0n ? 1 : -1
}

/** a − b, например «переплата больше на N ₽» из двух сумм API. */
export function subtractMoney(a: string, b: string): string {
  return fromKopecks(toKopecks(a) - toKopecks(b))
}

function groupThousands(digits: string) {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP)
}

/**
 * "2340000.00" → "2 340 000,00 ₽" (разделители — неразрывные пробелы).
 * `kopecks: false` скрывает нулевые копейки: "3000000" → "3 000 000 ₽"; ненулевые видны всегда.
 */
export function formatMoney(value: string, { kopecks = true }: { kopecks?: boolean } = {}): string {
  const total = toKopecks(value)
  const abs = total < 0n ? -total : total
  const rubles = groupThousands((abs / 100n).toString())
  const rest = (abs % 100n).toString().padStart(2, '0')
  const fraction = kopecks || rest !== '00' ? `,${rest}` : ''
  return `${total < 0n ? MINUS : ''}${rubles}${fraction}${NBSP}₽`
}

// Ввод суммы в мастере — целые рубли (design §3.3: `requested_amount_rub` в целых рублях).
// В форме сумма живёт строкой цифр, числом становится только в теле запроса.
const MAX_RUBLE_DIGITS = 12

/** Ввод в поле суммы: только цифры без ведущих нулей, «3 000 000 ₽» → «3000000». */
export function normalizeRubles(input: string): string {
  return input.replace(/\D/g, '').replace(/^0+/, '').slice(0, MAX_RUBLE_DIGITS)
}

/** «3000000» → «3 000 000» для поля ввода (без знака ₽ и копеек). */
export function groupRubles(digits: string): string {
  return groupThousands(digits)
}

/** Сумма из API → строка цифр для формы: «3000000.00» → «3000000». Копейки отбрасываются. */
export function wholeRubles(value: string): string {
  const total = toKopecks(value)
  return (total / 100n).toString()
}

/**
 * Целые рубли из формы → число для тела запроса: контракт принимает `requested_amount_rub`
 * и `amount` как integer. Не больше 12 цифр — число точное (меньше 2^53), копеек нет.
 */
export function rublesToNumber(digits: string): number {
  if (!/^\d{1,12}$/.test(digits)) throw new Error(`Некорректная сумма в рублях: ${digits}`)
  return parseInt(digits, 10)
}

/** Ставка из API строкой: «24.00» → «24 % годовых», «24.50» → «24,5 % годовых». */
export function formatRate(pct: string): string {
  const [whole = '0', fraction = ''] = pct.trim().split('.')
  const trimmed = fraction.replace(/0+$/, '')
  return `${whole}${trimmed ? `,${trimmed}` : ''}${NBSP}%${NBSP}годовых`
}
