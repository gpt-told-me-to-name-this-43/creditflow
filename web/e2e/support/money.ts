/** Деньги из API — строки `^\d+\.\d{2}$`: считаем в копейках через BigInt, без float. */
export function kopecks(value: string): bigint {
  const [rubles = '0', fraction = '00'] = value.split('.')
  return BigInt(rubles) * 100n + BigInt(fraction.padEnd(2, '0').slice(0, 2))
}

export const sumKopecks = (values: string[]) => values.reduce((acc, v) => acc + kopecks(v), 0n)

/**
 * Как на экране, но с обычными пробелами: Playwright сравнивает текст с нормализацией
 * пробелов, NBSP из formatMoney совпадает с « ».
 */
export function rub(value: bigint, { kopecks: withKopecks = true } = {}): string {
  const rubles = (value / 100n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
  const rest = (value % 100n).toString().padStart(2, '0')
  return withKopecks || rest !== '00' ? `${rubles},${rest} ₽` : `${rubles} ₽`
}

/** Значение поля суммы: разряды разделены NBSP, toHaveValue пробелы не нормализует. */
export const amountValue = (digits: string) =>
  new RegExp(`^${digits.replace(/\B(?=(\d{3})+(?!\d))/g, '\\s')}$`)
