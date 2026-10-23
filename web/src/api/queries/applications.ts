import { queryOptions } from '@tanstack/react-query'
import { isFinal, POLL_INTERVAL_MS } from '@/lib/polling.ts'
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
