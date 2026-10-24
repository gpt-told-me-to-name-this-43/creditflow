import type { ApplicationStatus } from '@/api/enums.ts'

const FINAL_STATUSES: ReadonlySet<ApplicationStatus> = new Set(['REJECTED', 'DECLINED', 'ISSUED'])

export const POLL_INTERVAL_MS = 5000
// После подписания выдача занимает 3–5 с (design §3.3) — опрашиваем чаще.
export const DISBURSEMENT_POLL_INTERVAL_MS = 2000

export function isFinal(status: ApplicationStatus | undefined): boolean {
  return status !== undefined && FINAL_STATUSES.has(status)
}

/**
 * Для `refetchInterval: (q) => applicationRefetchInterval(q.state.data?.status)`.
 * Фоновые вкладки не опрашиваются: `refetchIntervalInBackground` по умолчанию false.
 */
export function applicationRefetchInterval(status: ApplicationStatus | undefined): number | false {
  if (isFinal(status)) return false
  return status === 'SIGNED' ? DISBURSEMENT_POLL_INTERVAL_MS : POLL_INTERVAL_MS
}
