import { queryOptions } from '@tanstack/react-query'
import { api, unwrap } from '../client.ts'
import type { components } from '../schema.d.ts'
import { queryKeys } from './keys.ts'

export interface CreditProductsParams {
  purpose?: components['schemas']['PurposeCode']
  amount?: number
  term?: number
}

/** Продукты под условия заявки; без параметров — все продукты с их пределами. */
export const creditProductsQuery = (params: CreditProductsParams = {}) =>
  queryOptions({
    queryKey: queryKeys.creditProducts(params),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/credit-products', { params: { query: params }, signal })),
    staleTime: 60_000,
  })
