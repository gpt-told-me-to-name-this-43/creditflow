import type { components } from '@/api/schema.d.ts'
import { offerTexts } from '@/content/application.ts'
import { compareMoney, formatMoney, formatRate, subtractMoney } from '@/lib/money.ts'

type Application = components['schemas']['ClientApplicationView']
type Offer = components['schemas']['ClientOffer']

export interface OfferRow {
  label: string
  requested: string
  offered: string
  changed: boolean
}

// Ставка и суммы — строки с двумя знаками, сравниваем без перевода в числа.
const sameMoney = (a: string | null, b: string) => a !== null && compareMoney(a, b) === 0

/** «Вы просили → Банк предлагает»: только значения из API, отличия помечены. */
export function offerRows(application: Application, offer: Offer): OfferRow[] {
  const money = (value: string | null) => (value === null ? '—' : formatMoney(value))
  const { rows, months } = offerTexts
  return [
    {
      label: rows.amount,
      requested: money(application.requested_amount_rub),
      offered: formatMoney(offer.amount_rub),
      changed: !sameMoney(application.requested_amount_rub, offer.amount_rub),
    },
    {
      label: rows.term,
      requested: application.term_months === null ? '—' : months(application.term_months),
      offered: months(offer.term_months),
      changed: application.term_months !== offer.term_months,
    },
    {
      label: rows.rate,
      requested: application.annual_rate_pct ? formatRate(application.annual_rate_pct) : '—',
      offered: formatRate(offer.annual_rate_pct),
      changed: !sameMoney(application.annual_rate_pct, offer.annual_rate_pct),
    },
    {
      label: rows.payment,
      requested: money(application.monthly_payment_rub),
      offered: formatMoney(offer.monthly_payment_rub),
      changed: !sameMoney(application.monthly_payment_rub, offer.monthly_payment_rub),
    },
    {
      label: rows.overpayment,
      requested: money(application.overpayment_rub),
      offered: formatMoney(offer.overpayment_rub),
      changed: !sameMoney(application.overpayment_rub, offer.overpayment_rub),
    },
  ]
}

/**
 * Итог сравнения одной фразой: «Платёж меньше на N ₽, переплата больше на M ₽».
 * Единственная арифметика на фронте — разница двух сумм из API (web/CLAUDE.md).
 */
export function offerSummary(application: Application, offer: Offer): string | null {
  const parts: string[] = []
  const { monthly_payment_rub: payment, overpayment_rub: overpayment } = application
  if (payment && !sameMoney(payment, offer.monthly_payment_rub)) {
    const diff = subtractMoney(payment, offer.monthly_payment_rub)
    parts.push(
      compareMoney(diff, '0') > 0
        ? offerTexts.paymentLess(formatMoney(diff))
        : offerTexts.paymentMore(formatMoney(subtractMoney('0', diff))),
    )
  }
  if (overpayment && !sameMoney(overpayment, offer.overpayment_rub)) {
    const diff = subtractMoney(offer.overpayment_rub, overpayment)
    parts.push(
      compareMoney(diff, '0') > 0
        ? offerTexts.overpaymentMore(formatMoney(diff))
        : offerTexts.overpaymentLess(formatMoney(subtractMoney('0', diff))),
    )
  }
  if (parts.length === 0) return null
  const text = parts.join(', ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}
