// ИНН: 10 цифр у организации, 12 — у ИП. Проверка контрольных цифр по алгоритму ФНС,
// чтобы опечатку видно было сразу, без запроса. Окончательно ИНН проверяет бэк (INVALID_INN).

const WEIGHTS_10 = [2, 4, 10, 3, 5, 9, 4, 6, 8]
const WEIGHTS_11 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
const WEIGHTS_12 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]

/** Ввод в поле: только цифры, не больше 12 (вставка «7707 083 893» → «7707083893»). */
export function normalizeInn(input: string): string {
  return input.replace(/\D/g, '').slice(0, 12)
}

function checkDigit(digits: readonly number[], weights: readonly number[]): number {
  const sum = weights.reduce((acc, weight, i) => acc + weight * (digits[i] ?? 0), 0)
  return (sum % 11) % 10
}

export function isValidInn(inn: string): boolean {
  if (!/^(\d{10}|\d{12})$/.test(inn)) return false
  const digits = [...inn].map((char) => char.charCodeAt(0) - 48)
  if (digits.length === 10) return checkDigit(digits, WEIGHTS_10) === digits[9]
  return (
    checkDigit(digits, WEIGHTS_11) === digits[10] && checkDigit(digits, WEIGHTS_12) === digits[11]
  )
}
