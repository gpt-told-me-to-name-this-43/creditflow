import { queryOptions } from '@tanstack/react-query'
import { api, unwrap } from '../client.ts'
import { queryKeys } from './keys.ts'

export const healthQuery = () =>
  queryOptions({
    queryKey: queryKeys.health,
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/health', { signal })),
  })
