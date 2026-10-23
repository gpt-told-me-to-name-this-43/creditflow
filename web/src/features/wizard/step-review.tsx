import { useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { type ReactNode, useId } from 'react'
import { api, unwrap } from '@/api/client.ts'
import { errorMessage, isApiError } from '@/api/errors.ts'
import { applicationQuery } from '@/api/queries/applications.ts'
import { consentTextsQuery } from '@/api/queries/auth.ts'
import { queryKeys } from '@/api/queries/keys.ts'
import { creditProductsQuery } from '@/api/queries/products.ts'
import type { components } from '@/api/schema.d.ts'
import { Button } from '@/components/ui/button.tsx'
import { Checkbox } from '@/components/ui/checkbox.tsx'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip.tsx'
import { glossary } from '@/content/glossary.ts'
import { purposeTexts } from '@/content/purposes.ts'
import { fieldTexts, reviewTexts } from '@/content/wizard.ts'
import { useIdempotentMutation } from '@/lib/idempotency.ts'
import { formatMoney, formatRate } from '@/lib/money.ts'
import type { Application, WizardForm } from './wizard-form.ts'

type Schemas = components['schemas']

interface StepReviewProps {
  form: WizardForm
  application: Application
  onEdit: (step: number) => void
}

/** Поля из деталей 422: `missing_fields` или `fields[].field` вида `body.term_months`. */
function problemFields(error: unknown): string[] {
  if (!isApiError(error)) return []
  const details = error.details as
    Partial<Schemas['ApplicationIncompleteDetails'] & Schemas['ValidationDetails']> | undefined
  if (details?.missing_fields) return details.missing_fields
  return (details?.fields ?? []).map((item) => item.field.replace(/^body\./, ''))
}

export function StepReview({ form, application, onEdit }: StepReviewProps) {
  const { data: consents } = useSuspenseQuery(consentTextsQuery())
  const { data: products } = useSuspenseQuery(creditProductsQuery())
  const consent = consents.find((item) => item.type === 'BKI_REQUEST')
  const product = products.find((item) => item.id === application.product_id)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const consentId = useId()
  const titleId = useId()

  const submit = useIdempotentMutation({
    mutationFn: (body: Schemas['SubmitRequest'], idempotencyKey: string) =>
      unwrap(
        api.POST('/api/v1/applications/{application_id}/submit', {
          params: {
            path: { application_id: application.id },
            header: { 'Idempotency-Key': idempotencyKey },
          },
          body,
        }),
      ),
    // Ошибки отправки объясняем под кнопкой; 409 REVISION_CONFLICT всё равно покажет тост.
    meta: { invalidates: [queryKeys.applications.all], errorToast: false },
    onSuccess: async (submitted) => {
      queryClient.setQueryData(applicationQuery(submitted.id).queryKey, submitted)
      await navigate({
        to: '/client/applications/$applicationId',
        params: { applicationId: submitted.id },
      })
    },
  })

  const canSubmit = application.allowed_actions.includes('SUBMIT')
  const error = submit.error
  const unavailable = isApiError(error) && error.status === 503
  const fields = problemFields(error)

  return (
    <section className="grid gap-8" aria-labelledby={titleId}>
      <div className="grid gap-2">
        <h2 id={titleId} className="text-2xl font-bold">
          {reviewTexts.title}
        </h2>
        <p className="text-muted-foreground">{reviewTexts.description}</p>
      </div>

      <div className="grid max-w-3xl gap-6 rounded-xl border p-6">
        <dl className="grid grid-cols-[auto_1fr_auto] items-baseline gap-x-8 gap-y-3">
          {application.purpose_text && (
            <Row label={reviewTexts.purposeText} onEdit={() => onEdit(1)}>
              {application.purpose_text}
            </Row>
          )}
          <Row label={reviewTexts.purpose} onEdit={() => onEdit(2)}>
            {application.purpose_code && purposeTexts[application.purpose_code].label}
          </Row>
          <Row label={reviewTexts.amount} onEdit={() => onEdit(2)}>
            {application.requested_amount_rub &&
              formatMoney(application.requested_amount_rub, { kopecks: false })}
          </Row>
          <Row label={reviewTexts.term} onEdit={() => onEdit(2)}>
            {application.term_months && reviewTexts.months(application.term_months)}
          </Row>
          <Row label={reviewTexts.product} onEdit={() => onEdit(3)}>
            {product?.name}
          </Row>
          {application.annual_rate_pct && (
            <Row label={reviewTexts.rate}>{formatRate(application.annual_rate_pct)}</Row>
          )}
          {application.monthly_payment_rub && (
            <Row label={reviewTexts.payment} hint={glossary.monthlyPayment.text}>
              <span className="text-xl font-bold">
                {formatMoney(application.monthly_payment_rub)}
              </span>
            </Row>
          )}
          {application.overpayment_rub && (
            <Row label={reviewTexts.overpayment} hint={glossary.overpayment.text}>
              {formatMoney(application.overpayment_rub)}
            </Row>
          )}
        </dl>
        <p className="text-sm text-muted-foreground">{reviewTexts.estimate}</p>
      </div>

      <div className="grid max-w-3xl gap-3">
        <h3 className="text-lg font-semibold">{reviewTexts.nextTitle}</h3>
        <ol className="grid list-decimal gap-1 pl-5">
          {reviewTexts.nextSteps.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ol>
      </div>

      <form.Field name="bki_consent">
        {(field) => (
          <div className="flex max-w-3xl items-start gap-3">
            <Checkbox
              id={consentId}
              checked={field.state.value}
              onCheckedChange={(checked) => field.handleChange(checked === true)}
              className="mt-0.5"
            />
            <label htmlFor={consentId} className="grid gap-1 text-sm leading-relaxed">
              <span>{consent?.text}</span>
              <span className="text-muted-foreground">{glossary.bkiConsent.text}</span>
            </label>
          </div>
        )}
      </form.Field>

      {submit.isError && (
        <div role="alert" className="grid max-w-3xl justify-items-start gap-2">
          <p className="font-medium text-destructive">
            {unavailable
              ? reviewTexts.savedRetry
              : isApiError(error, 'PRODUCT_NOT_ELIGIBLE')
                ? reviewTexts.productNotEligible
                : errorMessage(error)}
          </p>
          {isApiError(error, 'PRODUCT_NOT_ELIGIBLE') && (
            <Button type="button" variant="outline" onClick={() => onEdit(3)}>
              {reviewTexts.goToStep}
            </Button>
          )}
          {fields.length > 0 && (
            <>
              <p>{reviewTexts.incomplete}</p>
              <ul className="grid gap-1">
                {fields.flatMap((name) => {
                  const text = fieldTexts[name]
                  if (!text) return []
                  return (
                    <li key={name} className="flex items-center gap-3">
                      {text.label}
                      <Button
                        type="button"
                        variant="link"
                        className="h-auto p-0"
                        onClick={() => onEdit(text.step)}
                      >
                        {reviewTexts.goToStep}
                      </Button>
                    </li>
                  )
                })}
              </ul>
            </>
          )}
        </div>
      )}

      {canSubmit && (
        <form.Subscribe selector={(state) => state.values.bki_consent}>
          {(consentGiven) => (
            <div className="flex gap-3">
              <Button type="button" variant="outline" size="lg" onClick={() => onEdit(3)}>
                {reviewTexts.back}
              </Button>
              <Button
                type="button"
                size="lg"
                disabled={!consentGiven || !consent || submit.isPending}
                onClick={() =>
                  submit.mutate({
                    revision: application.revision,
                    bki_consent_version: consent?.version ?? '',
                  })
                }
              >
                {submit.isPending ? reviewTexts.submitting : reviewTexts.submit}
              </Button>
            </div>
          )}
        </form.Subscribe>
      )}
    </section>
  )
}

function Row({
  label,
  hint,
  onEdit,
  children,
}: {
  label: string
  hint?: string
  onEdit?: () => void
  children: ReactNode
}) {
  return (
    <>
      <dt className="text-muted-foreground">
        {hint ? (
          <Tooltip>
            <TooltipTrigger className="cursor-help underline decoration-dotted underline-offset-4">
              {label}
            </TooltipTrigger>
            <TooltipContent>{hint}</TooltipContent>
          </Tooltip>
        ) : (
          label
        )}
      </dt>
      <dd className="font-semibold">{children}</dd>
      <dd>
        {onEdit && (
          <Button
            type="button"
            variant="link"
            className="h-auto p-0"
            onClick={onEdit}
            aria-label={`${reviewTexts.edit}: ${label}`}
          >
            {reviewTexts.edit}
          </Button>
        )}
      </dd>
    </>
  )
}
