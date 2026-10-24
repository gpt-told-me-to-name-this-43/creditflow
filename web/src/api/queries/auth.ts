import { queryOptions } from '@tanstack/react-query'
import { api, unwrap } from '../client.ts'
import { queryKeys } from './keys.ts'

export const meQuery = () =>
  queryOptions({
    queryKey: queryKeys.me,
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/auth/me', { signal })),
  })

// Список учёток и тексты согласий не меняются за время сессии.
export const demoAccountsQuery = () =>
  queryOptions({
    queryKey: queryKeys.demoAccounts,
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/auth/demo-accounts', { signal })),
    staleTime: Infinity,
  })

export const consentTextsQuery = () =>
  queryOptions({
    queryKey: queryKeys.consentTexts,
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/consents/texts', { signal })),
    staleTime: Infinity,
  })
