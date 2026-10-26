// Все даты показываем по Москве, независимо от пояса браузера.
const TIME_ZONE = 'Europe/Moscow'

const DATE_ONLY_RE = /^\d{4}-\d{2}-\d{2}$/

const dateFormat = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
  timeZone: TIME_ZONE,
})

// Календарная дата без времени ("2026-11-23", дата платежа) не должна сдвигаться по поясу.
const calendarDateFormat = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
  timeZone: 'UTC',
})

const dateTimeFormat = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  timeZone: TIME_ZONE,
})

/** "2026-10-23T21:30:00Z" → "24 октября 2026 г." (по Москве); "2026-11-23" → "23 ноября 2026 г.". */
export function formatDate(value: string): string {
  if (DATE_ONLY_RE.test(value)) return calendarDateFormat.format(new Date(`${value}T00:00:00Z`))
  return dateFormat.format(new Date(value))
}

/** Дата и время по Москве — для таймлайна событий. */
export function formatDateTime(value: string): string {
  return dateTimeFormat.format(new Date(value))
}

/** Сколько целых секунд осталось до момента из API; прошедший момент — 0. */
export function secondsUntil(value: string, now: number = Date.now()): number {
  return Math.max(0, Math.ceil((Date.parse(value) - now) / 1000))
}

/** 299 → «4:59» — таймер действия кода подтверждения. */
export function formatCountdown(seconds: number): string {
  const safe = Math.max(0, Math.floor(seconds))
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, '0')}`
}

/** Длительность словами для очереди и сводки: 45 → «1 мин», 5400 → «1 ч 30 мин», 2 дня → «2 дн». */
export function formatDuration(seconds: number): string {
  const minutes = Math.max(1, Math.round(seconds / 60))
  if (minutes < 60) return `${minutes} мин`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) {
    const rest = minutes % 60
    return rest ? `${hours} ч ${rest} мин` : `${hours} ч`
  }
  return `${Math.floor(hours / 24)} дн`
}

const monthFormat = new Intl.DateTimeFormat('ru-RU', { month: 'short', timeZone: 'UTC' })

/** Месяц выписки: "2025-10-01" → «окт. 2025» (календарная дата, без сдвига по поясу). */
export function formatMonth(value: string): string {
  const date = new Date(`${value.slice(0, 10)}T00:00:00Z`)
  return `${monthFormat.format(date)} ${date.getUTCFullYear()}`
}
