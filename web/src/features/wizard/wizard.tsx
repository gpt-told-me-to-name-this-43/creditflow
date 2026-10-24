import { useSuspenseQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { isApiError } from '@/api/errors.ts'
import { applicationQuery } from '@/api/queries/applications.ts'
import type { components } from '@/api/schema.d.ts'
import { Stepper } from '@/components/ui/stepper.tsx'
import { errorMessages } from '@/content/errors.ts'
import { wizardSteps } from '@/content/wizard.ts'
import { rublesToNumber, wholeRubles } from '@/lib/money.ts'
import { StepNeed } from './step-need.tsx'
import { StepProduct } from './step-product.tsx'
import { StepReview } from './step-review.tsx'
import { StepTerms } from './step-terms.tsx'
import { reachableStep, useSaveDraft, useWizardForm, type WizardValues } from './wizard-form.ts'

type ApplicationPatch = Omit<components['schemas']['ApplicationPatch'], 'revision'>

const TERMS_FORM_FIELDS = ['purpose_code', 'amount', 'term'] as const

// Поле заявки из деталей 422 → поле формы шага 2.
const FORM_FIELD_BY_API: Record<string, (typeof TERMS_FORM_FIELDS)[number]> = {
  'body.purpose_code': 'purpose_code',
  'body.requested_amount_rub': 'amount',
  'body.term_months': 'term',
}

/**
 * Мастер заявки. Шаг и id черновика — в адресе (переживают перезагрузку), значения — в одной
 * форме. Сохраняем PATCH-ем при переходе вперёд: шаг 1 — текст (и цель, выбранную вручную),
 * шаг 2 — подтверждённые параметры с источниками, шаг 3 — продукт. Шаг 4 — отправка.
 */
export function Wizard({ applicationId, step }: { applicationId: string; step: number }) {
  const { data: application } = useSuspenseQuery(applicationQuery(applicationId))
  const form = useWizardForm(application)
  const save = useSaveDraft(applicationId)
  const navigate = useNavigate()

  const goTo = (next: number) =>
    navigate({ to: '/client/applications/new', search: { applicationId, step: next } })

  async function saveAndGo(patch: ApplicationPatch, next: number) {
    if (Object.keys(patch).length > 0) {
      const saved = await save.mutateAsync(patch).catch((error: unknown) => {
        showFieldErrors(error)
        return null
      })
      if (!saved) return
    }
    await goTo(next)
  }

  function showFieldErrors(error: unknown) {
    if (!isApiError(error, 'VALIDATION_ERROR')) return
    const details = error.details as components['schemas']['ValidationDetails'] | undefined
    for (const { field } of details?.fields ?? []) {
      const name = FORM_FIELD_BY_API[field]
      if (!name) continue
      form.setFieldMeta(name, (meta) => ({
        ...meta,
        isTouched: true,
        errorMap: { ...meta.errorMap, onSubmit: errorMessages.VALIDATION_ERROR },
      }))
    }
  }

  function needPatch(mode: 'text' | 'manual'): ApplicationPatch {
    const patch: ApplicationPatch = {}
    const text = form.getFieldValue('purpose_text').trim()
    if (text !== (application.purpose_text ?? '')) patch.purpose_text = text || null
    const purpose = form.getFieldValue('purpose_code')
    // Цель, выбранная карточкой, — явный выбор клиента; предложенную ИИ сохраним на шаге 2.
    if (mode === 'manual' && purpose && purpose !== application.purpose_code) {
      patch.purpose_code = purpose
      patch.terms_field_sources = { ...application.terms_field_sources, purpose_code: 'MANUAL' }
    }
    return patch
  }

  function termsPatch({ purpose_code, amount, term, sources }: WizardValues): ApplicationPatch {
    const requested = rublesToNumber(amount)
    const months = parseInt(term, 10)
    const changed =
      purpose_code !== application.purpose_code ||
      amount !==
        (application.requested_amount_rub ? wholeRubles(application.requested_amount_rub) : '') ||
      months !== application.term_months
    return {
      purpose_code,
      requested_amount_rub: requested,
      term_months: months,
      terms_field_sources: {
        purpose_code: sources.purpose_code ?? 'MANUAL',
        requested_amount_rub: sources.requested_amount_rub ?? 'MANUAL',
        term_months: sources.term_months ?? 'MANUAL',
      },
      // Условия поменялись — выбранный кредит мог перестать подходить, выбираем заново.
      ...(changed && application.product_id ? { product_id: null } : {}),
    }
  }

  async function confirmTerms() {
    await form.validateAllFields('submit')
    const invalid = TERMS_FORM_FIELDS.some(
      (name) => (form.getFieldMeta(name)?.errors.length ?? 0) > 0,
    )
    if (invalid) return
    await saveAndGo(termsPatch(form.state.values), 3)
  }

  return (
    <div className="grid gap-10">
      <Stepper
        steps={wizardSteps}
        current={step}
        canOpen={(number) => number <= reachableStep(application)}
        onOpen={(number) => void goTo(number)}
      />

      {step === 1 && (
        <StepNeed
          form={form}
          application={application}
          saving={save.isPending}
          onNext={(mode) => void saveAndGo(needPatch(mode), 2)}
        />
      )}
      {step === 2 && (
        <StepTerms
          form={form}
          saving={save.isPending}
          onBack={() => void goTo(1)}
          onConfirm={() => void confirmTerms()}
        />
      )}
      {step === 3 && (
        <StepProduct
          application={application}
          saving={save.isPending}
          onChoose={(productId) => void saveAndGo({ product_id: productId }, 4)}
          onChangeTerms={() => void goTo(2)}
          onNext={() => void goTo(4)}
        />
      )}
      {step === 4 && (
        <StepReview form={form} application={application} onEdit={(number) => void goTo(number)} />
      )}
    </div>
  )
}
