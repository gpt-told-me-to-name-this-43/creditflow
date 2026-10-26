import { useForm, useStore } from '@tanstack/react-form'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckIcon, OctagonAlertIcon, SearchIcon } from 'lucide-react'
import { type ReactNode, useId, useState } from 'react'
import { toast } from 'sonner'
import { api, unwrap } from '@/api/client.ts'
import { CLIENT_REASON_CODES, type ClientReasonCode, type ManagerAction } from '@/api/enums.ts'
import { errorMessage, isApiError } from '@/api/errors.ts'
import { offerPreviewQuery } from '@/api/queries/manager.ts'
import { queryKeys } from '@/api/queries/keys.ts'
import type { components } from '@/api/schema.d.ts'
import { Button } from '@/components/ui/button.tsx'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog.tsx'
import { firstError, FormField } from '@/components/ui/form-field.tsx'
import { Input } from '@/components/ui/input.tsx'
import { MoneyInput } from '@/components/ui/money-input.tsx'
import {
  cardTexts,
  decisionTexts,
  MAX_DECISION_TEXT,
  riskLevelTexts,
  stopFactorReason,
  violationTexts,
} from '@/content/manager.ts'
import { reasonTexts } from '@/content/reasons.ts'
import { useIdempotentMutation } from '@/lib/idempotency.ts'
import { compareMoney, formatMoney, rublesToNumber, wholeRubles } from '@/lib/money.ts'
import { useDebouncedValue } from '@/lib/use-debounced-value.ts'
import { cn } from '@/lib/utils.ts'

type Schemas = components['schemas']
type Application = Schemas['ManagerApplicationView']
type DecisionBody =
  | Schemas['ApproveDecision']
  | Schemas['CounterOfferDecision']
  | Schemas['RequestInfoDecision']
  | Schemas['RejectDecision']

const ORDER: readonly ManagerAction[] = ['APPROVE', 'COUNTER_OFFER', 'REQUEST_INFO', 'REJECT']

/** Действие, совпадающее с рекомендацией, — главная кнопка; при ручном рассмотрении главной нет. */
const RECOMMENDED: Partial<Record<Schemas['SuggestedAction'], ManagerAction>> = {
  ELIGIBLE_FOR_MANAGER_REVIEW: 'APPROVE',
  COUNTER_OFFER_CANDIDATE: 'COUNTER_OFFER',
  BLOCKED_BY_RULE: 'REJECT',
}

const PREVIEW_DEBOUNCE_MS = 400

const textareaClass =
  'w-full rounded-md border border-input bg-background px-3 py-2 outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 aria-invalid:border-destructive'

/** Открытая форма решения; вопрос — когда дозапрос начат из AI-заключения. */
export interface DecisionRequest {
  action: ManagerAction
  question?: string
}

/** Кнопки решений из `allowed_actions` и диалог с формой выбранного решения. */
export function DecisionPanel({
  application,
  request,
  onRequest,
}: {
  application: Application
  request: DecisionRequest | null
  onRequest: (request: DecisionRequest | null) => void
}) {
  const action = request?.action ?? null
  const setAction = (next: ManagerAction | null) => onRequest(next && { action: next })
  const allowed = ORDER.filter((item) => application.allowed_actions.includes(item))
  const recommended = application.proposal && RECOMMENDED[application.proposal.suggested_action]

  return (
    <div className="grid gap-3 border-t pt-5">
      <h3 className="text-sm font-medium text-muted-foreground">{cardTexts.allowedActions}</h3>
      {allowed.length === 0 ? (
        <p className="text-sm text-muted-foreground">{cardTexts.noActions}</p>
      ) : (
        <div className="grid gap-2">
          {allowed.map((item) => (
            <Button
              key={item}
              size="lg"
              variant={item === recommended ? 'default' : 'outline'}
              onClick={() => setAction(item)}
            >
              {decisionTexts.open[item]}
            </Button>
          ))}
        </div>
      )}
      {allowed.length === 1 &&
        allowed[0] === 'REJECT' &&
        (application.proposal?.blocking_codes.length ?? 0) > 0 && (
          <p className="text-sm">{cardTexts.onlyReject}</p>
        )}
      <p className="text-xs text-muted-foreground">{cardTexts.decisionOwner}</p>

      <Dialog open={action !== null} onOpenChange={(open) => !open && setAction(null)}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
          {action && (
            <>
              <DialogHeader>
                <DialogTitle>{decisionTexts.dialogTitle[action]}</DialogTitle>
                <DialogDescription>{decisionTexts.dialogDescription[action]}</DialogDescription>
              </DialogHeader>
              <DecisionForm
                key={action}
                action={action}
                application={application}
                question={request?.question}
                onDone={() => setAction(null)}
              />
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}

function useDecision(application: Application, action: ManagerAction, onDone: () => void) {
  return useIdempotentMutation({
    mutationFn: (body: DecisionBody, idempotencyKey) =>
      unwrap(
        api.POST('/api/v1/manager/applications/{application_id}/decisions', {
          params: {
            path: { application_id: application.id },
            header: { 'Idempotency-Key': idempotencyKey },
          },
          body,
        }),
      ),
    // Ошибку показывает форма; конфликт ревизии — ещё и тостом с обновлением данных.
    meta: { invalidates: [queryKeys.manager.all], errorToast: false },
    onSuccess: () => {
      toast.success(decisionTexts.done[action])
      onDone()
    },
  })
}

interface FormProps {
  application: Application
  onDone: () => void
}

function DecisionForm({
  action,
  question,
  ...props
}: FormProps & { action: ManagerAction; question?: string }) {
  switch (action) {
    case 'APPROVE':
      return <ApproveForm {...props} />
    case 'COUNTER_OFFER':
      return <CounterOfferForm {...props} />
    case 'REQUEST_INFO':
      return <RequestInfoForm {...props} question={question} />
    case 'REJECT':
      return <RejectForm {...props} />
  }
}

function requestedSummary(application: Application) {
  const amount = application.requested_amount_rub
    ? formatMoney(application.requested_amount_rub, { kopecks: false })
    : '—'
  const term = application.term_months ? cardTexts.months(application.term_months) : '—'
  return `${amount} · ${term}`
}

function ApproveForm({ application, onDone }: FormProps) {
  const decide = useDecision(application, 'APPROVE', onDone)
  // Одобрение вопреки рекомендации требует обоснования (design.md §3.5).
  const needsComment = application.proposal?.suggested_action !== 'ELIGIBLE_FOR_MANAGER_REVIEW'
  const form = useForm({
    defaultValues: { comment: '' },
    onSubmit: ({ value }) =>
      decide
        .mutateAsync({
          action: 'APPROVE',
          revision: application.revision,
          comment: value.comment.trim() || null,
        })
        .catch(() => undefined),
  })

  return (
    <FormShell form={form} decide={decide} action="APPROVE">
      <p>
        <span className="text-muted-foreground">{decisionTexts.requested}: </span>
        <span className="font-semibold tabular-nums">{requestedSummary(application)}</span>
      </p>
      <ClientSees>{decisionTexts.clientSeesApprove(requestedSummary(application))}</ClientSees>
      {needsComment && (
        <p className="flex gap-2 text-sm font-medium">
          <OctagonAlertIcon aria-hidden className="size-4 shrink-0 translate-y-0.5" />
          {decisionTexts.approveAgainst}
        </p>
      )}
      <form.Field
        name="comment"
        validators={{
          onBlur: ({ value }) => commentError(value, needsComment),
          onSubmit: ({ value }) => commentError(value, needsComment),
        }}
      >
        {(field) => <CommentField field={field} />}
      </form.Field>
    </FormShell>
  )
}

function CounterOfferForm({ application, onDone }: FormProps) {
  const decide = useDecision(application, 'COUNTER_OFFER', onDone)
  const constraints = application.offer_constraints
  const limit = application.scoring?.limit_rub ?? null
  const requested = application.requested_amount_rub
  // Подставляем лимит на запрошенный срок, если он меньше запроса: чаще всего это и есть оффер.
  const initialAmount =
    limit && requested && compareMoney(limit, requested) < 0
      ? wholeRubles(limit)
      : requested
        ? wholeRubles(requested)
        : ''

  const form = useForm({
    defaultValues: {
      amount: initialAmount,
      term: application.term_months ? String(application.term_months) : '',
      reason: 'HIGH_DEBT_LOAD' as ClientReasonCode,
      comment: '',
    },
    onSubmit: ({ value }) =>
      decide
        .mutateAsync({
          action: 'COUNTER_OFFER',
          revision: application.revision,
          amount_rub: rublesToNumber(value.amount),
          term_months: parseInt(value.term, 10),
          client_reason_code: value.reason,
          comment: value.comment.trim(),
        })
        .catch(() => undefined),
  })

  const amount = useStore(form.store, (state) => state.values.amount)
  const term = useStore(form.store, (state) => state.values.term)
  const terms = useDebouncedValue({ amount, term }, PREVIEW_DEBOUNCE_MS)
  const ready = /^\d{1,12}$/.test(terms.amount) && /^\d{1,3}$/.test(terms.term)
  const preview = useOfferPreview(
    application.id,
    ready ? rublesToNumber(terms.amount) : 0,
    ready ? parseInt(terms.term, 10) : 0,
    ready && terms.term !== '0',
  )
  // Отправить можно только то, что backend только что проверил на этих же условиях.
  const settled = terms.amount === amount && terms.term === term && !preview.isPlaceholderData
  const valid = settled && preview.data?.valid === true && !preview.isFetching
  const findTerm = useFindTerm(application)

  return (
    <FormShell form={form} decide={decide} action="COUNTER_OFFER" canSubmit={valid}>
      <p>
        <span className="text-muted-foreground">{decisionTexts.requested}: </span>
        <span className="font-semibold tabular-nums">{requestedSummary(application)}</span>
      </p>
      <div className="grid grid-cols-[2fr_1fr] gap-4">
        <form.Field
          name="amount"
          validators={{
            onBlur: ({ value }) => (value ? undefined : decisionTexts.amountRequired),
            onSubmit: ({ value }) => (value ? undefined : decisionTexts.amountRequired),
          }}
        >
          {(field) => (
            <FormField
              id="offer-amount"
              label={decisionTexts.amount}
              hint={
                constraints
                  ? decisionTexts.amountHint(
                      formatMoney(constraints.min_amount_rub, { kopecks: false }),
                      formatMoney(constraints.max_amount_rub, { kopecks: false }),
                    )
                  : undefined
              }
              error={field.state.meta.isTouched ? firstError(field.state.meta.errors) : undefined}
            >
              {(props) => (
                <MoneyInput
                  {...props}
                  value={field.state.value}
                  onChange={field.handleChange}
                  onBlur={field.handleBlur}
                />
              )}
            </FormField>
          )}
        </form.Field>
        <form.Field
          name="term"
          validators={{
            onBlur: ({ value }) => (value ? undefined : decisionTexts.termRequired),
            onSubmit: ({ value }) => (value ? undefined : decisionTexts.termRequired),
          }}
        >
          {(field) => (
            <FormField
              id="offer-term"
              label={decisionTexts.term}
              hint={
                constraints
                  ? decisionTexts.termHint(constraints.min_term_months, constraints.max_term_months)
                  : undefined
              }
              error={field.state.meta.isTouched ? firstError(field.state.meta.errors) : undefined}
            >
              {(props) => (
                <Input
                  {...props}
                  inputMode="numeric"
                  autoComplete="off"
                  className="text-lg"
                  value={field.state.value}
                  onChange={(event) =>
                    field.handleChange(event.target.value.replace(/\D/g, '').slice(0, 3))
                  }
                  onBlur={field.handleBlur}
                />
              )}
            </FormField>
          )}
        </form.Field>
      </div>

      {requested && constraints && (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={findTerm.searching}
            onClick={() =>
              void findTerm.run().then((found) => {
                if (found === null) return
                form.setFieldValue('amount', wholeRubles(requested))
                form.setFieldValue('term', String(found))
              })
            }
          >
            <SearchIcon aria-hidden className="size-4" />
            {findTerm.searching ? decisionTexts.findingTerm : decisionTexts.findTerm}
          </Button>
          <span aria-live="polite" className="text-muted-foreground">
            {findTerm.result === 'none'
              ? decisionTexts.termNotFound(formatMoney(requested, { kopecks: false }))
              : typeof findTerm.result === 'number'
                ? decisionTexts.termFound(
                    formatMoney(requested, { kopecks: false }),
                    findTerm.result,
                  )
                : null}
          </span>
        </div>
      )}

      <OfferPreview
        preview={preview.data}
        loading={!settled || preview.isFetching}
        failed={preview.isError}
        onUseLimit={(value) => form.setFieldValue('amount', wholeRubles(value))}
      />

      {/^\d{1,12}$/.test(amount) && /^\d{1,3}$/.test(term) && (
        <ClientSees>
          {decisionTexts.clientSeesOffer(
            `${formatMoney(String(rublesToNumber(amount)), { kopecks: false })} · ${cardTexts.months(parseInt(term, 10))}`,
          )}
        </ClientSees>
      )}

      <form.Field name="reason">
        {(field) => (
          <ReasonPicker value={field.state.value} onChange={(code) => field.handleChange(code)} />
        )}
      </form.Field>
      <form.Field
        name="comment"
        validators={{
          onBlur: ({ value }) => commentError(value, true),
          onSubmit: ({ value }) => commentError(value, true),
        }}
      >
        {(field) => <CommentField field={field} />}
      </form.Field>
    </FormShell>
  )
}

/** Сроки проверяются пачками, чтобы не ждать до 60 последовательных запросов. */
const FIND_TERM_BATCH = 6

/**
 * «Та же сумма, найти срок»: минимальный срок в границах продукта, на котором запрошенная сумма
 * проходит проверку offer-preview. Правила проверяет только backend — здесь лишь перебор.
 */
function useFindTerm(application: Application) {
  const queryClient = useQueryClient()
  const [searching, setSearching] = useState(false)
  const [result, setResult] = useState<number | 'none' | null>(null)
  const constraints = application.offer_constraints
  const requested = application.requested_amount_rub

  const run = async (): Promise<number | null> => {
    if (!constraints || !requested) return null
    const amount = rublesToNumber(wholeRubles(requested))
    const terms: number[] = []
    for (let t = constraints.min_term_months; t <= constraints.max_term_months; t += 1) {
      if (t !== application.term_months) terms.push(t)
    }
    setSearching(true)
    setResult(null)
    try {
      for (let i = 0; i < terms.length; i += FIND_TERM_BATCH) {
        const batch = terms.slice(i, i + FIND_TERM_BATCH)
        const previews = await Promise.all(
          batch.map((t) => queryClient.fetchQuery(offerPreviewQuery(application.id, amount, t))),
        )
        const found = batch.find((_, index) => previews[index]?.valid)
        if (found !== undefined) {
          setResult(found)
          return found
        }
      }
      setResult('none')
      return null
    } catch {
      setResult(null)
      toast.error(decisionTexts.previewError)
      return null
    } finally {
      setSearching(false)
    }
  }

  return { run, searching, result }
}

/** Прошлый расчёт остаётся на экране, пока считается новый: блок не прыгает при вводе. */
function useOfferPreview(id: string, amount: number, term: number, enabled: boolean) {
  return useQuery({
    ...offerPreviewQuery(id, amount, term),
    enabled,
    placeholderData: keepPreviousData,
  })
}

type PreviewData = ReturnType<typeof useOfferPreview>['data']

function OfferPreview({
  preview,
  loading,
  failed,
  onUseLimit,
}: {
  preview: PreviewData
  loading: boolean
  failed: boolean
  onUseLimit: (limit: string) => void
}) {
  return (
    <section
      aria-labelledby="preview-title"
      aria-busy={loading}
      className="grid gap-3 rounded-lg border bg-muted/50 p-4"
    >
      <div className="flex items-center justify-between gap-4">
        <h3 id="preview-title" className="font-semibold">
          {decisionTexts.preview}
        </h3>
        {loading && (
          <span className="text-sm text-muted-foreground">{decisionTexts.previewLoading}</span>
        )}
      </div>
      {failed && !preview ? (
        <p className="text-sm">{decisionTexts.previewError}</p>
      ) : !preview ? null : preview.calculation_status === 'SKIPPED' ? (
        <p className="text-sm">{decisionTexts.previewSkipped}</p>
      ) : (
        <>
          <dl className={cn('grid grid-cols-4 gap-3', loading && 'opacity-60')}>
            <PreviewFigure
              label={decisionTexts.payment}
              value={formatMoney(preview.monthly_payment_rub)}
            />
            <PreviewFigure label={cardTexts.dscr} value={preview.dscr} />
            <PreviewFigure label={cardTexts.score} value={String(preview.score)} />
            <PreviewFigure label={cardTexts.risk} value={riskLevelTexts[preview.risk_level]} />
          </dl>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span className="text-muted-foreground">{decisionTexts.limitForTerm}:</span>
            <span className="font-semibold tabular-nums">
              {preview.limit_for_term_rub
                ? formatMoney(preview.limit_for_term_rub, { kopecks: false })
                : cardTexts.noLimit}
            </span>
            {preview.limit_for_term_rub && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => onUseLimit(preview.limit_for_term_rub ?? '0')}
              >
                {decisionTexts.useLimit(
                  formatMoney(preview.limit_for_term_rub, { kopecks: false }),
                )}
              </Button>
            )}
          </div>
        </>
      )}
      {preview && !loading && (
        <div aria-live="polite">
          {preview.valid ? (
            <p className="flex items-center gap-2 text-sm font-medium">
              <CheckIcon aria-hidden className="size-4" />
              {decisionTexts.previewValid}
            </p>
          ) : (
            <ul className="grid gap-1">
              {preview.violations.map((violation) => (
                <li key={violation} className="flex gap-2 text-sm font-medium text-destructive">
                  <OctagonAlertIcon aria-hidden className="size-4 shrink-0 translate-y-0.5" />
                  {violationTexts[violation]}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}

function PreviewFigure({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-0.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-semibold tabular-nums">{value}</dd>
    </div>
  )
}

function RequestInfoForm({ application, onDone, question }: FormProps & { question?: string }) {
  const decide = useDecision(application, 'REQUEST_INFO', onDone)
  const questionId = useId()
  const suggestions = application.ai_report?.report?.manager_questions ?? []
  const form = useForm({
    defaultValues: { question: question ?? '', comment: '' },
    onSubmit: ({ value }) =>
      decide
        .mutateAsync({
          action: 'REQUEST_INFO',
          revision: application.revision,
          question_text: value.question.trim(),
          comment: value.comment.trim() || null,
        })
        .catch(() => undefined),
  })
  const questionError = ({ value }: { value: string }) =>
    value.trim() ? undefined : decisionTexts.questionRequired

  return (
    <FormShell form={form} decide={decide} action="REQUEST_INFO">
      <form.Field name="question" validators={{ onBlur: questionError, onSubmit: questionError }}>
        {(field) => {
          const error = field.state.meta.isTouched ? firstError(field.state.meta.errors) : undefined
          return (
            <div className="grid gap-2">
              <label htmlFor={questionId} className="text-sm font-medium">
                {decisionTexts.question}
              </label>
              {suggestions.length > 0 && (
                <div className="grid gap-2">
                  <span className="text-xs text-muted-foreground">{decisionTexts.aiQuestions}</span>
                  <ul className="flex flex-wrap gap-2">
                    {suggestions.map((suggestion) => (
                      <li key={suggestion}>
                        <button
                          type="button"
                          onClick={() => field.handleChange(suggestion)}
                          className="rounded-full border px-3 py-1 text-left text-sm outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50"
                        >
                          {suggestion}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <textarea
                id={questionId}
                rows={4}
                maxLength={MAX_DECISION_TEXT}
                aria-invalid={error ? true : undefined}
                aria-describedby={[error ? `${questionId}-error` : '', `${questionId}-hint`]
                  .filter(Boolean)
                  .join(' ')}
                value={field.state.value}
                onChange={(event) => field.handleChange(event.target.value)}
                onBlur={field.handleBlur}
                className={textareaClass}
              />
              <div className="flex justify-between gap-4 text-sm text-muted-foreground">
                <p id={`${questionId}-hint`}>{decisionTexts.questionHint}</p>
                <p aria-live="polite" className="shrink-0">
                  {field.state.value.length} / {MAX_DECISION_TEXT}
                </p>
              </div>
              {error && (
                <p id={`${questionId}-error`} className="text-sm font-medium text-destructive">
                  {error}
                </p>
              )}
            </div>
          )
        }}
      </form.Field>
      <ClientSees>{decisionTexts.clientSeesQuestion}</ClientSees>
      <form.Field
        name="comment"
        validators={{
          onBlur: ({ value }) => commentError(value, false),
          onSubmit: ({ value }) => commentError(value, false),
        }}
      >
        {(field) => <CommentField field={field} />}
      </form.Field>
    </FormShell>
  )
}

function RejectForm({ application, onDone }: FormProps) {
  const decide = useDecision(application, 'REJECT', onDone)
  const [stop] = application.proposal?.blocking_codes ?? []
  const form = useForm({
    defaultValues: {
      reason: (stop ? stopFactorReason[stop] : null) as ClientReasonCode | null,
      comment: '',
    },
    onSubmit: ({ value }) =>
      value.reason
        ? decide
            .mutateAsync({
              action: 'REJECT',
              revision: application.revision,
              client_reason_code: value.reason,
              comment: value.comment.trim(),
            })
            .catch(() => undefined)
        : undefined,
  })
  const reasonError = ({ value }: { value: ClientReasonCode | null }) =>
    value ? undefined : decisionTexts.reasonRequired

  return (
    <FormShell form={form} decide={decide} action="REJECT">
      <form.Field name="reason" validators={{ onSubmit: reasonError, onChange: reasonError }}>
        {(field) => (
          <ReasonPicker
            value={field.state.value}
            onChange={(code) => field.handleChange(code)}
            error={field.state.meta.errors.length ? firstError(field.state.meta.errors) : undefined}
          />
        )}
      </form.Field>
      <form.Field
        name="comment"
        validators={{
          onBlur: ({ value }) => commentError(value, true),
          onSubmit: ({ value }) => commentError(value, true),
        }}
      >
        {(field) => <CommentField field={field} />}
      </form.Field>
    </FormShell>
  )
}

/** Причина для клиента: радиокнопки и сразу видно, что прочитает клиент. */
function ReasonPicker({
  value,
  onChange,
  error,
}: {
  value: ClientReasonCode | null
  onChange: (code: ClientReasonCode) => void
  error?: string
}) {
  const name = useId()
  return (
    <fieldset className="grid gap-2" aria-describedby={error ? `${name}-error` : undefined}>
      <legend className="mb-2 text-sm font-medium">{decisionTexts.reason}</legend>
      <div className="grid grid-cols-2 gap-2">
        {CLIENT_REASON_CODES.map((code) => (
          <label
            key={code}
            className={cn(
              'flex cursor-pointer gap-3 rounded-lg border p-3 text-sm has-[:focus-visible]:ring-[3px] has-[:focus-visible]:ring-ring/50',
              value === code && 'border-foreground',
            )}
          >
            <input
              type="radio"
              name={name}
              value={code}
              checked={value === code}
              onChange={() => onChange(code)}
              className="mt-0.5 accent-foreground"
            />
            {reasonTexts[code].reason}
          </label>
        ))}
      </div>
      {value && (
        <ClientSees>
          {reasonTexts[value].reason}. {reasonTexts[value].whatToDo}
        </ClientSees>
      )}
      {error && (
        <p id={`${name}-error`} className="text-sm font-medium text-destructive">
          {error}
        </p>
      )}
    </fieldset>
  )
}

/** Что попадёт клиенту: менеджер подтверждает решение, видя его глазами клиента. */
function ClientSees({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-lg bg-muted p-3 text-sm">
      <span className="font-medium">{decisionTexts.clientSees}: </span>
      {children}
    </p>
  )
}

function commentError(value: string, required: boolean) {
  if (required && !value.trim()) return decisionTexts.commentRequired
  return undefined
}

interface CommentFieldApi {
  state: { value: string; meta: { isTouched: boolean; errors: readonly unknown[] } }
  handleChange: (value: string) => void
  handleBlur: () => void
}

function CommentField({ field }: { field: CommentFieldApi }) {
  const id = useId()
  const error = field.state.meta.isTouched ? firstError(field.state.meta.errors) : undefined
  return (
    <FormField id={id} label={decisionTexts.comment} hint={decisionTexts.commentHint} error={error}>
      {(props) => (
        <textarea
          {...props}
          rows={3}
          maxLength={MAX_DECISION_TEXT}
          value={field.state.value}
          onChange={(event) => field.handleChange(event.target.value)}
          onBlur={field.handleBlur}
          className={textareaClass}
        />
      )}
    </FormField>
  )
}

interface FormApi {
  handleSubmit: () => Promise<void>
}

/** Общая обёртка формы решения: ошибка API, «Отмена» и кнопка отправки. */
function FormShell({
  form,
  decide,
  action,
  canSubmit = true,
  children,
}: {
  form: FormApi
  decide: ReturnType<typeof useDecision>
  action: ManagerAction
  canSubmit?: boolean
  children: ReactNode
}) {
  const queryClient = useQueryClient()
  // Конфликт ревизии или статуса: данные уже перезапрошены (query-client), ввод формы остаётся.
  const conflict =
    isApiError(decide.error, 'REVISION_CONFLICT') ||
    isApiError(decide.error, 'INVALID_STATUS_TRANSITION')
  return (
    <form
      noValidate
      className="grid gap-5"
      onSubmit={(event) => {
        event.preventDefault()
        void form.handleSubmit()
      }}
    >
      {children}
      {conflict ? (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-3">
          <p className="font-medium text-destructive">{decisionTexts.conflict}</p>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => {
              decide.reset()
              void queryClient.invalidateQueries({ queryKey: queryKeys.manager.all })
            }}
          >
            {decisionTexts.refresh}
          </Button>
        </div>
      ) : (
        decide.isError && (
          <p role="alert" className="font-medium text-destructive">
            {errorMessage(decide.error)}
          </p>
        )
      )}
      <DialogFooter>
        <DialogClose asChild>
          <Button type="button" variant="outline">
            {decisionTexts.cancel}
          </Button>
        </DialogClose>
        <Button
          type="submit"
          variant={action === 'REJECT' ? 'secondary' : 'default'}
          disabled={decide.isPending || !canSubmit}
        >
          {decide.isPending ? decisionTexts.submitting : decisionTexts.submit[action]}
        </Button>
      </DialogFooter>
    </form>
  )
}
