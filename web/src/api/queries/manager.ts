import { queryOptions } from '@tanstack/react-query'
import type { ApplicationStatus } from '../enums.ts'
import { api, unwrap } from '../client.ts'
import { queryKeys } from './keys.ts'

/** Очередь и сводка обновляются раз в 10 с (#10): решения принимают и другие менеджеры. */
export const MANAGER_POLL_INTERVAL_MS = 10_000

export const managerQueueQuery = (status: ApplicationStatus) =>
  queryOptions({
    queryKey: queryKeys.manager.queue(status),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/manager/applications', { params: { query: { status } }, signal })),
    refetchInterval: MANAGER_POLL_INTERVAL_MS,
  })

export const managerStatsQuery = () =>
  queryOptions({
    queryKey: queryKeys.manager.stats,
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/manager/stats', { signal })),
    refetchInterval: MANAGER_POLL_INTERVAL_MS,
  })

export const managerApplicationQuery = (id: string) =>
  queryOptions({
    queryKey: queryKeys.manager.detail(id),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/manager/applications/{application_id}', {
          params: { path: { application_id: id } },
          signal,
        }),
      ),
    refetchInterval: MANAGER_POLL_INTERVAL_MS,
  })

/** Пока заключение готовится, опрашиваем раз в 3 с; READY и FALLBACK опрос останавливают. */
export const AI_REPORT_POLL_INTERVAL_MS = 3000

export const managerAiReportQuery = (id: string) =>
  queryOptions({
    queryKey: queryKeys.manager.aiReport(id),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/manager/applications/{application_id}/ai-report', {
          params: { path: { application_id: id } },
          signal,
        }),
      ),
    refetchInterval: (query) =>
      query.state.data?.status === 'PENDING' ? AI_REPORT_POLL_INTERVAL_MS : false,
  })

/** Предпросмотр оффера ничего не пишет: это чтение, хотя и POST (design.md §3.5). */
export const offerPreviewQuery = (id: string, amount: number, term: number) =>
  queryOptions({
    queryKey: queryKeys.manager.offerPreview(id, amount, term),
    queryFn: ({ signal }) =>
      unwrap(
        api.POST('/api/v1/manager/applications/{application_id}/offer-preview', {
          params: { path: { application_id: id } },
          body: { amount_rub: amount, term_months: term },
          signal,
        }),
      ),
    retry: false,
  })
