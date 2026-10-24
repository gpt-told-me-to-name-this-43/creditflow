import { useForm } from '@tanstack/react-form'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, unwrap } from '@/api/client.ts'
import type { PurposeCode } from '@/api/enums.ts'
import { applicationQuery, markSession, storeApplication } from '@/api/queries/applications.ts'
import { queryKeys } from '@/api/queries/keys.ts'
import type { components } from '@/api/schema.d.ts'
import { wholeRubles } from '@/lib/money.ts'

type Schemas = components['schemas']
export type Application = Schemas['ClientApplicationView']
export type TermsField = Schemas['TermsField']
export type FieldSource = Schemas['FieldSource']

export const LAST_STEP = 4

/**
 * Значения мастера. Сумма и срок — строки цифр, как в полях ввода. `sources` — откуда
 * взялось значение поля, `matched` — фрагмент текста клиента для подсказки у метки.
 */
export interface WizardValues {
  purpose_text: string
  purpose_code: PurposeCode | null
  amount: string
  term: string
  sources: Partial<Record<TermsField, FieldSource>>
  matched: Partial<Record<TermsField, string>>
  bki_consent: boolean
}

export function valuesFrom(application: Application): WizardValues {
  return {
    purpose_text: application.purpose_text ?? '',
    purpose_code: application.purpose_code,
    amount: application.requested_amount_rub ? wholeRubles(application.requested_amount_rub) : '',
    term: application.term_months ? String(application.term_months) : '',
    sources: { ...application.terms_field_sources },
    matched: {},
    bki_consent: false,
  }
}

/**
 * Одна форма на весь мастер. Начальные значения берутся из заявки один раз: опрос и
 * обновление кэша после 409 не затирают то, что клиент уже ввёл.
 */
export function useWizardForm(application: Application) {
  const [defaultValues] = useState(() => valuesFrom(application))
  return useForm({ defaultValues })
}

export type WizardForm = ReturnType<typeof useWizardForm>

/** Дальше какого шага пускать: параметры и продукт должны быть сохранены в заявке. */
export function reachableStep(application: Application): number {
  const { purpose_code, requested_amount_rub, term_months, product_id } = application
  if (!purpose_code || !requested_amount_rub || !term_months) return 2
  return product_id ? 4 : 3
}

/**
 * PATCH черновика с актуальной revision из кэша. Ответ — новая заявка, кладём её в кэш:
 * следующая запись пойдёт уже с новой revision. После 409 кэш обновится глобально.
 */
export function useSaveDraft(applicationId: string) {
  const queryClient = useQueryClient()
  const { queryKey } = applicationQuery(applicationId)
  return useMutation({
    mutationFn: (patch: Omit<Schemas['ApplicationPatch'], 'revision'>) => {
      const revision = queryClient.getQueryData(queryKey)?.revision ?? 0
      return unwrap(
        api.PATCH('/api/v1/applications/{application_id}', {
          params: { path: { application_id: applicationId } },
          body: { ...patch, revision },
        }),
      )
    },
    onMutate: markSession,
    onSuccess: (application, _patch, mark) => storeApplication(queryClient, application, mark),
    meta: { invalidates: [queryKeys.applications.all] },
  })
}
