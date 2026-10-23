import { queryOptions } from '@tanstack/react-query'
import { api, unwrap } from '../client.ts'
import { queryKeys } from './keys.ts'

export const companyQuery = () =>
  queryOptions({
    queryKey: queryKeys.company,
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/company', { signal })),
  })
