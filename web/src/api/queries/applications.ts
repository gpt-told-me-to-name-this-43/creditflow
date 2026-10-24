import { queryOptions } from '@tanstack/react-query'
import { applicationRefetchInterval, isFinal, POLL_INTERVAL_MS } from '@/lib/polling.ts'
import { api, unwrap } from '../client.ts'
import { queryKeys } from './keys.ts'

export const applicationsQuery = () =>
  queryOptions({
    queryKey: queryKeys.applications.all,
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/applications', { signal })),
    // Список обновляется, пока хоть одна отправленная заявка ждёт решения или выдачи.
    refetchInterval: (query) =>
      query.state.data?.some((item) => item.status !== 'DRAFT' && !isFinal(item.status))
        ? POLL_INTERVAL_MS
        : false,
  })

export const applicationQuery = (id: string) =>
  queryOptions({
    queryKey: queryKeys.applications.detail(id),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/applications/{application_id}', {
          params: { path: { application_id: id } },
          signal,
        }),
      ),
    // Черновик меняет только сам клиент — опрашивать нечего; дальше решение приходит с бэка.
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'DRAFT' ? false : applicationRefetchInterval(status)
    },
  })

export const contractQuery = (id: string) =>
  queryOptions({
    queryKey: queryKeys.applications.contract(id),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/applications/{application_id}/contract', {
          params: { path: { application_id: id } },
          signal,
        }),
      ),
  })
