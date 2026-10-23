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
