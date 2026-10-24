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
