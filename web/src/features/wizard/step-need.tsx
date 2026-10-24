import { useMutation } from '@tanstack/react-query'
import { InfoIcon } from 'lucide-react'
import { useId, useState } from 'react'
import { api, unwrap } from '@/api/client.ts'
import type { components } from '@/api/schema.d.ts'
import { Button } from '@/components/ui/button.tsx'
import { SourceLabel } from '@/components/ui/source-label.tsx'
import { purposeTexts } from '@/content/purposes.ts'
import { needExamples, needTexts, reviewTexts } from '@/content/wizard.ts'
import { formatMoney } from '@/lib/money.ts'
import { PurposePicker } from './purpose-picker.tsx'
import type { Application, TermsField, WizardForm } from './wizard-form.ts'

type InterpretResponse = components['schemas']['InterpretResponse']

const MAX_TEXT = 1000
const TERMS_FIELDS: TermsField[] = ['purpose_code', 'requested_amount_rub', 'term_months']

interface StepNeedProps {
  form: WizardForm
  application: Application
  saving: boolean
  onNext: (mode: 'text' | 'manual') => void
}

export function StepNeed({ form, application, saving, onNext }: StepNeedProps) {
  // Ручной режим, если цель уже выбрана вручную и текста нет (вернулись к черновику).
  const [mode, setMode] = useState<'text' | 'manual'>(
    !application.purpose_text && application.terms_field_sources.purpose_code === 'MANUAL'
      ? 'manual'
      : 'text',
  )
  const textId = useId()
  const manualTitleId = useId()

  // Распознавание ничего не сохраняет: значения попадают только в форму, с меткой источника.
  const interpret = useMutation({
    mutationFn: (purposeText: string) =>
      unwrap(
        api.POST('/api/v1/applications/{application_id}/interpret', {
          params: { path: { application_id: application.id } },
          body: { purpose_text: purposeText },
        }),
      ),
  })

  function applySuggestion({ suggestion }: InterpretResponse) {
    const { purpose_code, requested_amount_rub, term_months } = suggestion
    if (purpose_code) form.setFieldValue('purpose_code', purpose_code.value)
    if (requested_amount_rub) form.setFieldValue('amount', String(requested_amount_rub.value))
    if (term_months) form.setFieldValue('term', String(term_months.value))
    for (const field of TERMS_FIELDS) {
      const item = suggestion[field]
      if (!item) continue
      form.setFieldValue('sources', (prev) => ({ ...prev, [field]: item.source }))
      form.setFieldValue('matched', (prev) => ({ ...prev, [field]: item.matched_text ?? '' }))
    }
  }

  function runInterpret() {
    const text = form.getFieldValue('purpose_text').trim()
    if (!text) return
    // Колбэк вызова, а не хука: после «Заполнить вручную» (reset) ответ уже не применяется.
    interpret.mutate(text, { onSuccess: applySuggestion })
  }

  function switchToManual() {
    interpret.reset()
    setMode('manual')
  }

  return (
    <section className="grid gap-8" aria-labelledby={`${textId}-title`}>
      <div className="grid gap-2">
        <h2 id={`${textId}-title`} className="text-2xl font-bold">
          {needTexts.title}
        </h2>
        <p className="text-muted-foreground">{needTexts.description}</p>
      </div>

      <div role="group" aria-label={needTexts.title} className="flex gap-2">
        <Button
          type="button"
          variant={mode === 'text' ? 'secondary' : 'ghost'}
          aria-pressed={mode === 'text'}
          onClick={() => setMode('text')}
        >
          {needTexts.modeText}
        </Button>
        <Button
          type="button"
          variant={mode === 'manual' ? 'secondary' : 'ghost'}
          aria-pressed={mode === 'manual'}
          onClick={switchToManual}
        >
          {needTexts.modeManual}
        </Button>
      </div>

      {mode === 'text' ? (
        <div className="grid max-w-3xl gap-6">
          <form.Field name="purpose_text">
            {(field) => (
              <div className="grid gap-2">
                <label htmlFor={textId} className="text-sm font-medium">
                  {needTexts.textLabel}
                </label>
                <textarea
                  id={textId}
                  aria-describedby={`${textId}-hint ${textId}-count`}
                  maxLength={MAX_TEXT}
                  rows={4}
                  placeholder={needTexts.textPlaceholder}
                  value={field.state.value}
                  onChange={(event) => field.handleChange(event.target.value)}
                  onBlur={field.handleBlur}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-lg outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
                />
                <div className="flex justify-between gap-4 text-sm text-muted-foreground">
                  <p id={`${textId}-hint`}>{needTexts.textHint}</p>
                  <p id={`${textId}-count`} aria-live="polite">
                    {field.state.value.length} / {MAX_TEXT}
                  </p>
                </div>
              </div>
            )}
          </form.Field>

          <div className="grid gap-2">
            <p className="text-sm font-medium">{needTexts.examplesLabel}</p>
            <ul className="flex flex-wrap gap-2">
              {needExamples.map((example) => (
                <li key={example}>
                  <button
                    type="button"
                    onClick={() => form.setFieldValue('purpose_text', example)}
                    className="rounded-full border px-3 py-1 text-sm transition-colors outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50"
                  >
                    {example}
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <form.Subscribe selector={(state) => state.values.purpose_text.trim() !== ''}>
            {(hasText) => (
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  type="button"
                  variant="outline"
                  size="lg"
                  disabled={!hasText || interpret.isPending}
                  onClick={runInterpret}
                >
                  {interpret.isPending ? needTexts.interpreting : needTexts.interpret}
                </Button>
                {interpret.isPending && (
                  <Button type="button" variant="ghost" onClick={switchToManual}>
                    {needTexts.fillManually}
                  </Button>
                )}
              </div>
            )}
          </form.Subscribe>

          {interpret.data && <InterpretResult form={form} result={interpret.data} />}
        </div>
      ) : (
        <form.Field name="purpose_code">
          {(field) => (
            <div className="grid gap-3">
              <h3 id={manualTitleId} className="text-lg font-semibold">
                {needTexts.manualTitle}
              </h3>
              <PurposePicker
                name="purpose_code_manual"
                labelledBy={manualTitleId}
                value={field.state.value}
                onChange={(value) => {
                  field.handleChange(value)
                  form.setFieldValue('sources', (prev) => ({ ...prev, purpose_code: 'MANUAL' }))
                }}
              />
            </div>
          )}
        </form.Field>
      )}

      <div>
        <Button type="button" size="lg" disabled={saving} onClick={() => onNext(mode)}>
          {needTexts.next}
        </Button>
      </div>
    </section>
  )
}

function InterpretResult({ form, result }: { form: WizardForm; result: InterpretResponse }) {
  const { suggestion } = result
  const found = TERMS_FIELDS.some((field) => suggestion[field])
  return (
    <div className="grid gap-4 rounded-xl border p-5" role="status">
      {result.status === 'UNAVAILABLE' && (
        <p className="flex items-start gap-2 font-medium">
          <InfoIcon aria-hidden className="mt-0.5 size-4 shrink-0" />
          {needTexts.unavailable}
        </p>
      )}
      {result.status === 'NEEDS_CLARIFICATION' && result.clarification_question && (
        <p className="flex items-start gap-2 font-semibold">
          <InfoIcon aria-hidden className="mt-0.5 size-4 shrink-0" />
          {result.clarification_question}
        </p>
      )}
      {found ? (
        <>
          <div className="grid gap-1">
            <p className="font-semibold">{needTexts.recognized}</p>
            <p className="text-sm text-muted-foreground">{needTexts.recognizedHint}</p>
          </div>
          <form.Subscribe selector={(state) => state.values}>
            {(values) => (
              <dl className="grid grid-cols-[auto_1fr] items-center gap-x-6 gap-y-3">
                {suggestion.purpose_code && values.purpose_code && (
                  <Recognized
                    label={reviewTexts.purpose}
                    value={purposeTexts[values.purpose_code].label}
                    source={values.sources.purpose_code}
                    matched={values.matched.purpose_code}
                  />
                )}
                {suggestion.requested_amount_rub && values.amount && (
                  <Recognized
                    label={reviewTexts.amount}
                    value={formatMoney(values.amount, { kopecks: false })}
                    source={values.sources.requested_amount_rub}
                    matched={values.matched.requested_amount_rub}
                  />
                )}
                {suggestion.term_months && values.term && (
                  <Recognized
                    label={reviewTexts.term}
                    value={reviewTexts.months(Number(values.term))}
                    source={values.sources.term_months}
                    matched={values.matched.term_months}
                  />
                )}
              </dl>
            )}
          </form.Subscribe>
        </>
      ) : (
        <p className="text-muted-foreground">{needTexts.nothingRecognized}</p>
      )}
    </div>
  )
}

function Recognized({
  label,
  value,
  source,
  matched,
}: {
  label: string
  value: string
  source?: components['schemas']['FieldSource']
  matched?: string
}) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="flex flex-wrap items-center gap-3 font-semibold">
        {value}
        {source && <SourceLabel source={source} matched={matched} />}
      </dd>
    </>
  )
}
