import type { CreditProductsParams } from '@/api/queries/products.ts'
import type { components } from '@/api/schema.d.ts'
import { compareMoney, rublesToNumber, wholeRubles } from '@/lib/money.ts'
import type { Application } from './wizard-form.ts'

type CreditProduct = components['schemas']['CreditProduct']

/** Параметры подбора — из сохранённой заявки, а не из формы: шаг 2 уже подтверждён. */
export function productParams(application: Application): CreditProductsParams {
  return {
    purpose: application.purpose_code ?? undefined,
    amount: application.requested_amount_rub
      ? rublesToNumber(wholeRubles(application.requested_amount_rub))
      : undefined,
    term: application.term_months ?? undefined,
  }
}

/** Пределы суммы и срока по всем продуктам — для подсказок и проверки ввода. */
export function productRanges(products: readonly CreditProduct[]) {
  const [first, ...rest] = products
  if (!first) return null
  return rest.reduce(
    (range, product) => ({
      minAmount:
        compareMoney(product.min_amount_rub, range.minAmount) < 0
          ? product.min_amount_rub
          : range.minAmount,
      maxAmount:
        compareMoney(product.max_amount_rub, range.maxAmount) > 0
          ? product.max_amount_rub
          : range.maxAmount,
      minTerm: Math.min(product.min_term_months, range.minTerm),
      maxTerm: Math.max(product.max_term_months, range.maxTerm),
    }),
    {
      minAmount: first.min_amount_rub,
      maxAmount: first.max_amount_rub,
      minTerm: first.min_term_months,
      maxTerm: first.max_term_months,
    },
  )
}
