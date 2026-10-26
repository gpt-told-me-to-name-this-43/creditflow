import { useForm } from '@tanstack/react-form'
import { useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { CircleCheckIcon, LoaderCircleIcon } from 'lucide-react'
import { useId, useState } from 'react'
import { api, unwrap } from '@/api/client.ts'
import { markSession, storeApplication } from '@/api/queries/applications.ts'
import { queryKeys } from '@/api/queries/keys.ts'
import type { components } from '@/api/schema.d.ts'
import { Button } from '@/components/ui/button.tsx'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card.tsx'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog.tsx'
import { firstError } from '@/components/ui/form-field.tsx'
import { GlossaryTerm } from '@/components/ui/glossary-term.tsx'
import {
  applicationTexts,
  approvedTexts,
  declinedTexts,
  disbursementTexts,
  infoRequestTexts,
  offerTexts,
  rejectedTexts,
  reviewBlockTexts,
} from '@/content/application.ts'
import { glossary } from '@/content/glossary.ts'
import { reasonTexts } from '@/content/reasons.ts'
import { formatDate } from '@/lib/dates.ts'
import { useIdempotentMutation } from '@/lib/idempotency.ts'
import { formatMoney } from '@/lib/money.ts'
import { cn } from '@/lib/utils.ts'
import { offerRows, offerSummary } from './offer.ts'

type Schemas = components['schemas']
type Application = Schemas['ClientApplicationView']

const MAX_ANSWER = 2000

/** Действие с заявкой: ответ кладём в кэш карточки и обновляем список. */
function useApplicationAction<TBody>(
  request: (body: TBody, idempotencyKey: string) => Promise<Application>,
) {
  const queryClient = useQueryClient()
  return useIdempotentMutation({
    mutationFn: request,
    meta: { invalidates: [queryKeys.applications.all] },
    onMutate: markSession,
    onSuccess: (application, _body, mark) => storeApplication(queryClient, application, mark),
  })
}

function NewApplicationLink() {
  return (
    <Button asChild size="lg" className="justify-self-start">
      <Link to="/client/applications/new">{applicationTexts.newApplication}</Link>
    </Button>
  )
}

export function UnderReviewBlock({ application }: { application: Application }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{reviewBlockTexts.title}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-6">
        <ul className="grid gap-2">
          {reviewBlockTexts.checks.map((check) => (
            <li key={check} className="flex items-center gap-3">
              <LoaderCircleIcon aria-hidden className="size-4 animate-spin text-muted-foreground" />
              {check}
            </li>
          ))}
        </ul>
        {application.info_request?.answer_text && (
          <div className="grid gap-1 rounded-lg bg-muted p-4">
            <p className="text-sm text-muted-foreground">{reviewBlockTexts.yourAnswer}</p>
            <p className="whitespace-pre-line">{application.info_request.answer_text}</p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function InfoRequestBlock({ application }: { application: Application }) {
  const answerId = useId()
  const respond = useApplicationAction((body: Schemas['InfoResponseRequest'], idempotencyKey) =>
    unwrap(
      api.POST('/api/v1/applications/{application_id}/info-response', {
        params: {
          path: { application_id: application.id },
          header: { 'Idempotency-Key': idempotencyKey },
        },
        body,
      }),
    ),
  )
  const form = useForm({
    defaultValues: { answer: '' },
    onSubmit: ({ value }) =>
      respond
        .mutateAsync({ revision: application.revision, answer_text: value.answer.trim() })
        .catch(() => undefined),
  })
  const validateAnswer = ({ value }: { value: string }) =>
    value.trim() ? undefined : infoRequestTexts.answerRequired
  const canRespond = application.allowed_actions.includes('RESPOND_INFO')

  return (
    <Card>
      <CardHeader>
        <CardTitle>{infoRequestTexts.title}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-6">
        <p className="text-lg font-semibold whitespace-pre-line">
          {application.info_request?.question_text}
        </p>
        {canRespond && (
          <form
            noValidate
            className="grid max-w-3xl gap-4"
            onSubmit={(event) => {
              event.preventDefault()
              void form.handleSubmit()
            }}
          >
            <form.Field
              name="answer"
              validators={{ onBlur: validateAnswer, onSubmit: validateAnswer }}
            >
              {(field) => {
                const error = field.state.meta.isTouched
                  ? firstError(field.state.meta.errors)
                  : undefined
                return (
                  <div className="grid gap-2">
                    <label htmlFor={answerId} className="text-sm font-medium">
                      {infoRequestTexts.answerLabel}
                    </label>
                    <textarea
                      id={answerId}
                      rows={5}
                      maxLength={MAX_ANSWER}
                      aria-invalid={error ? true : undefined}
                      aria-describedby={[
                        error ? `${answerId}-error` : '',
                        `${answerId}-hint`,
                        `${answerId}-count`,
                      ]
                        .filter(Boolean)
                        .join(' ')}
                      value={field.state.value}
                      onChange={(event) => field.handleChange(event.target.value)}
                      onBlur={field.handleBlur}
                      className="w-full rounded-md border border-input bg-background px-3 py-2 outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 aria-invalid:border-destructive"
                    />
                    <div className="flex justify-between gap-4 text-sm text-muted-foreground">
                      <p id={`${answerId}-hint`}>{infoRequestTexts.answerHint}</p>
                      <p id={`${answerId}-count`} aria-live="polite" className="shrink-0">
                        {field.state.value.length} / {MAX_ANSWER}
                      </p>
                    </div>
                    {error && (
                      <p id={`${answerId}-error`} className="text-sm font-medium text-destructive">
                        {error}
                      </p>
                    )}
                  </div>
                )
              }}
            </form.Field>
            <Button
              type="submit"
              size="lg"
              className="justify-self-start"
              disabled={respond.isPending}
            >
              {respond.isPending ? infoRequestTexts.sending : infoRequestTexts.send}
            </Button>
          </form>
        )}
      </CardContent>
    </Card>
  )
}

export function OfferBlock({ application }: { application: Application }) {
  const offer = application.offer
  const [dialog, setDialog] = useState<'accept' | 'decline' | null>(null)

  const decide = useApplicationAction(
    ({ action, revision }: { action: 'accept' | 'decline'; revision: number }, idempotencyKey) => {
      const options = {
        params: {
          path: { application_id: application.id },
          header: { 'Idempotency-Key': idempotencyKey },
        },
        body: { revision },
      }
      return unwrap(
        action === 'accept'
          ? api.POST('/api/v1/applications/{application_id}/offer/accept', options)
          : api.POST('/api/v1/applications/{application_id}/offer/decline', options),
      )
    },
  )

  if (!offer) return null
  const rows = offerRows(application, offer)
  const summary = offerSummary(application, offer)
  const actions = application.allowed_actions

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xl">{offerTexts.title}</CardTitle>
        <p className="text-muted-foreground">{offerTexts.description}</p>
      </CardHeader>
      <CardContent className="grid gap-6">
        <table className="w-full max-w-3xl text-left">
          <thead>
            <tr className="border-b text-sm text-muted-foreground">
              <th scope="col" className="py-2 font-medium">
                <span className="sr-only">{offerTexts.condition}</span>
              </th>
              <th scope="col" className="py-2 font-medium">
                {offerTexts.requested}
              </th>
              <th scope="col" className="py-2 font-medium">
                {offerTexts.offered}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label} className="border-b last:border-0" data-changed={row.changed}>
                <th scope="row" className="py-3 pr-6 font-normal text-muted-foreground">
                  {row.label}
                </th>
                <td
                  className={cn('py-3 pr-6', row.changed && 'text-muted-foreground line-through')}
                >
                  {row.requested}
                </td>
                <td className={cn('py-3', row.changed && 'font-bold')}>
                  {row.offered}
                  {row.changed && (
                    <span className="ml-2 rounded-md bg-accent px-2 py-0.5 text-xs font-semibold">
                      {offerTexts.changed}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {summary && <p className="text-lg font-semibold">{summary}</p>}

        <div className="flex gap-3">
          {actions.includes('ACCEPT_OFFER') && (
            <Button size="lg" onClick={() => setDialog('accept')} disabled={decide.isPending}>
              {offerTexts.accept}
            </Button>
          )}
          {actions.includes('DECLINE_OFFER') && (
            <Button
              size="lg"
              variant="outline"
              onClick={() => setDialog('decline')}
              disabled={decide.isPending}
            >
              {offerTexts.decline}
            </Button>
          )}
        </div>
      </CardContent>

      <Dialog open={dialog !== null} onOpenChange={(open) => !open && setDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {dialog === 'accept' ? offerTexts.acceptTitle : offerTexts.declineTitle}
            </DialogTitle>
            <DialogDescription>
              {dialog === 'accept' ? offerTexts.acceptDescription : offerTexts.declineDescription}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline">{offerTexts.cancel}</Button>
            </DialogClose>
            <Button
              variant={dialog === 'accept' ? 'default' : 'secondary'}
              disabled={decide.isPending}
              onClick={() => {
                if (!dialog) return
                decide.mutate(
                  { action: dialog, revision: application.revision },
                  { onSettled: () => setDialog(null) },
                )
              }}
            >
              {dialog === 'accept' ? offerTexts.confirmAccept : offerTexts.confirmDecline}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}

export function ApprovedBlock() {
  return (
    <Card role="status">
      <CardHeader>
        <CardTitle className="flex items-center gap-3 text-xl">
          <CircleCheckIcon aria-hidden className="size-6 text-success" />
          {approvedTexts.title}
        </CardTitle>
        <p className="text-muted-foreground">{approvedTexts.description}</p>
      </CardHeader>
    </Card>
  )
}

export function RejectedBlock({ application }: { application: Application }) {
  const reason = application.client_reason_code && reasonTexts[application.client_reason_code]
  return (
    <Card>
      <CardContent className="grid gap-6">
        {reason && (
          <dl className="grid gap-4">
            <div className="grid gap-1">
              <dt className="text-sm text-muted-foreground">{rejectedTexts.title}</dt>
              <dd className="text-lg font-semibold">{reason.reason}</dd>
            </div>
            <div className="grid gap-1">
              <dt className="text-sm text-muted-foreground">{rejectedTexts.whatToDo}</dt>
              <dd>{reason.whatToDo}</dd>
            </div>
          </dl>
        )}
        <NewApplicationLink />
      </CardContent>
    </Card>
  )
}

export function DeclinedBlock() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xl">{declinedTexts.title}</CardTitle>
        <p className="text-muted-foreground">{declinedTexts.description}</p>
      </CardHeader>
      <CardContent>
        <NewApplicationLink />
      </CardContent>
    </Card>
  )
}

export function SignedBlock() {
  return (
    <Card role="status" aria-live="polite">
      <CardHeader>
        <CardTitle className="flex items-center gap-3 text-xl">
          <LoaderCircleIcon aria-hidden className="size-6 animate-spin" />
          {disbursementTexts.signedTitle}
        </CardTitle>
        <p className="text-muted-foreground">{disbursementTexts.signedDescription}</p>
      </CardHeader>
    </Card>
  )
}

export function IssuedBlock({ contract }: { contract: Schemas['ContractView'] }) {
  const first = contract.schedule[0]
  return (
    <Card role="status">
      <CardHeader>
        <CardTitle className="flex items-center gap-3 text-2xl">
          <CircleCheckIcon aria-hidden className="size-7 text-success" />
          {disbursementTexts.issuedTitle}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-4 gap-6">
          <div className="grid gap-1">
            <dt className="text-sm text-muted-foreground">{disbursementTexts.amount}</dt>
            <dd className="text-2xl font-bold">{formatMoney(contract.amount_rub)}</dd>
          </div>
          <div className="grid gap-1">
            <dt className="text-sm text-muted-foreground">{disbursementTexts.account}</dt>
            <dd className="text-lg font-semibold">{contract.account_masked}</dd>
          </div>
          {first && (
            <div className="grid gap-1">
              <dt className="text-sm text-muted-foreground">{disbursementTexts.firstPayment}</dt>
              <dd className="text-lg font-semibold">{formatDate(first.due_date)}</dd>
            </div>
          )}
          <div className="grid gap-1">
            <dt className="text-sm text-muted-foreground">
              <GlossaryTerm
                label={disbursementTexts.monthlyPayment}
                hint={glossary.monthlyPayment.text}
              />
            </dt>
            <dd className="text-lg font-semibold">{formatMoney(contract.monthly_payment_rub)}</dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  )
}
