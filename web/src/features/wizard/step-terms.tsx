import { useSuspenseQuery } from '@tanstack/react-query'
import { useId } from 'react'
import { creditProductsQuery } from '@/api/queries/products.ts'
import { Button } from '@/components/ui/button.tsx'
import { firstError, FormField } from '@/components/ui/form-field.tsx'
import { Input } from '@/components/ui/input.tsx'
import { MoneyInput } from '@/components/ui/money-input.tsx'
import { SourceLabel } from '@/components/ui/source-label.tsx'
import { termsSourceTexts, termsTexts } from '@/content/wizard.ts'
import { compareMoney, formatMoney } from '@/lib/money.ts'
import { productRanges } from './products.ts'
import { PurposePicker } from './purpose-picker.tsx'
import { deriveTermsSource } from './terms-source.ts'
import type { WizardForm } from './wizard-form.ts'

const rubles = (value: string) => formatMoney(value, { kopecks: false })

interface StepTermsProps {
  form: WizardForm
  saving: boolean
  onBack: () => void
  onConfirm: () => void
}

export function StepTerms({ form, saving, onBack, onConfirm }: StepTermsProps) {
  const { data: products } = useSuspenseQuery(creditProductsQuery())
  const range = productRanges(products)
  const purposeId = useId()

  const validateAmount = ({ value }: { value: string }) => {
    if (!value) return termsTexts.errors.amountRequired
    if (!range) return undefined
    if (compareMoney(value, range.minAmount) < 0) {
      return termsTexts.errors.amountTooSmall(rubles(range.minAmount))
    }
    if (compareMoney(value, range.maxAmount) > 0) {
      return termsTexts.errors.amountTooLarge(rubles(range.maxAmount))
    }
    return undefined
  }

  const validateTerm = ({ value }: { value: string }) => {
    if (!value) return termsTexts.errors.termRequired
    const months = parseInt(value, 10)
    if (range && (months < range.minTerm || months > range.maxTerm)) {
      return termsTexts.errors.termOutOfRange(range.minTerm, range.maxTerm)
    }
    return undefined
  }

  // Правка поля снимает метку «распознано»/«предложено ИИ»: значение теперь от клиента.
  const markManual = (field: 'purpose_code' | 'requested_amount_rub' | 'term_months') =>
    form.setFieldValue('sources', (prev) => ({ ...prev, [field]: 'MANUAL' }))

  return (
    <section className="grid gap-8" aria-labelledby={`${purposeId}-title`}>
      <div className="grid gap-2">
        <h2 id={`${purposeId}-title`} className="text-2xl font-bold">
          {termsTexts.title}
        </h2>
        <p className="text-muted-foreground">{termsTexts.description}</p>
      </div>

      <form.Subscribe selector={(state) => state.values}>
        {({ sources, matched }) => (
          <div className="grid gap-8">
            <form.Field
              name="purpose_code"
              validators={{
                onSubmit: ({ value }) => (value ? undefined : termsTexts.errors.purposeRequired),
              }}
            >
              {(field) => {
                const error = firstError(field.state.meta.errors)
                return (
                  <div className="grid gap-3">
                    <div className="flex flex-wrap items-center gap-3">
                      <span id={purposeId} className="text-sm font-medium">
                        {termsTexts.purposeLabel}
                      </span>
                      {sources.purpose_code && (
                        <SourceLabel source={sources.purpose_code} matched={matched.purpose_code} />
                      )}
                    </div>
                    <PurposePicker
                      name="purpose_code"
                      labelledBy={purposeId}
                      describedBy={error ? `${purposeId}-error` : undefined}
                      invalid={Boolean(error)}
                      value={field.state.value}
                      onChange={(value) => {
                        field.handleChange(value)
                        markManual('purpose_code')
                      }}
                    />
                    {error && (
                      <p id={`${purposeId}-error`} className="text-sm font-medium text-destructive">
                        {error}
                      </p>
                    )}
                  </div>
                )
              }}
            </form.Field>

            <div className="grid max-w-3xl grid-cols-2 gap-6">
              <form.Field
                name="amount"
                validators={{ onBlur: validateAmount, onSubmit: validateAmount }}
              >
                {(field) => (
                  <div className="grid content-start gap-2">
                    <FormField
                      id="amount"
                      label={termsTexts.amountLabel}
                      addon={
                        sources.requested_amount_rub && (
                          <SourceLabel
                            source={sources.requested_amount_rub}
                            matched={matched.requested_amount_rub}
                          />
                        )
                      }
                      hint={
                        range
                          ? termsTexts.amountHint(rubles(range.minAmount), rubles(range.maxAmount))
                          : undefined
                      }
                      error={
                        field.state.meta.isTouched ? firstError(field.state.meta.errors) : undefined
                      }
                    >
                      {(props) => (
                        <MoneyInput
                          {...props}
                          value={field.state.value}
                          onChange={(digits) => {
                            field.handleChange(digits)
                            markManual('requested_amount_rub')
                          }}
                          onBlur={field.handleBlur}
                        />
                      )}
                    </FormField>
                  </div>
                )}
              </form.Field>

              <form.Field name="term" validators={{ onBlur: validateTerm, onSubmit: validateTerm }}>
                {(field) => (
                  <div className="grid content-start gap-2">
                    <FormField
                      id="term"
                      label={termsTexts.termLabel}
                      addon={
                        sources.term_months && (
                          <SourceLabel source={sources.term_months} matched={matched.term_months} />
                        )
                      }
                      hint={range ? termsTexts.termHint(range.minTerm, range.maxTerm) : undefined}
                      error={
                        field.state.meta.isTouched ? firstError(field.state.meta.errors) : undefined
                      }
                    >
                      {(props) => (
                        <Input
                          {...props}
                          inputMode="numeric"
                          autoComplete="off"
                          maxLength={3}
                          className="text-lg"
                          value={field.state.value}
                          onChange={(event) => {
                            field.handleChange(
                              event.target.value.replace(/\D/g, '').replace(/^0+/, ''),
                            )
                            markManual('term_months')
                          }}
                          onBlur={field.handleBlur}
                        />
                      )}
                    </FormField>
                  </div>
                )}
              </form.Field>
            </div>

            <p className="text-sm text-muted-foreground">
              {termsSourceTexts[deriveTermsSource(sources)]}
            </p>
          </div>
        )}
      </form.Subscribe>

      <div className="flex gap-3">
        <Button type="button" variant="outline" size="lg" onClick={onBack}>
          {termsTexts.back}
        </Button>
        <Button type="button" size="lg" disabled={saving} onClick={onConfirm}>
          {saving ? termsTexts.saving : termsTexts.confirm}
        </Button>
      </div>
    </section>
  )
}
