import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { SparklesIcon, ThumbsDownIcon, ThumbsUpIcon } from 'lucide-react'
import { type ReactNode, useId, useState } from 'react'
import { api, unwrap } from '@/api/client.ts'
import { queryKeys } from '@/api/queries/keys.ts'
import { managerAiReportQuery } from '@/api/queries/manager.ts'
import type { components } from '@/api/schema.d.ts'
import { Badge } from '@/components/ui/badge.tsx'
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
import { Skeleton } from '@/components/ui/skeleton.tsx'
import { aiTexts, MAX_DECISION_TEXT } from '@/content/manager.ts'
import { formatDateTime } from '@/lib/dates.ts'
import { cn } from '@/lib/utils.ts'

type Schemas = components['schemas']
type Report = Schemas['AiReportView']
type Verdict = Schemas['AiFeedbackRequest']['verdict']

/**
 * AI-заключение (#8): пересказ расчёта и вопросы клиенту. Не влияет на статус и действия —
 * поэтому стоит отдельным блоком, а решение остаётся в панели справа.
 */
export function AiReport({ applicationId, initial }: { applicationId: string; initial: Report }) {
  const queryClient = useQueryClient()
  const query = managerAiReportQuery(applicationId)
  const { data: report = initial } = useQuery({ ...query, initialData: initial })
  const [confirming, setConfirming] = useState(false)

  const regenerate = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/manager/applications/{application_id}/ai-report', {
          params: { path: { application_id: applicationId }, query: { regenerate: true } },
        }),
      ),
    // Регенерация удаляет оценки прежнего текста — сводка 👍 меняется.
    meta: { invalidates: [queryKeys.manager.stats] },
    onSuccess: (next) => {
      queryClient.setQueryData(query.queryKey, next)
      setConfirming(false)
    },
  })

  const pending = report.status === 'PENDING'

  return (
    <section aria-labelledby="ai-title" className="grid gap-5 rounded-xl border bg-card p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="grid gap-1">
          <h2 id="ai-title" className="flex items-center gap-2 text-xl font-semibold">
            <SparklesIcon aria-hidden className="size-5" />
            {aiTexts.title}
          </h2>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">{aiTexts.opinion}</Badge>
            {report.status === 'FALLBACK' && (
              <Badge variant="secondary">{aiTexts.templateBadge}</Badge>
            )}
          </div>
          <p className="text-sm text-muted-foreground">{aiTexts.hint}</p>
        </div>
        <Button
          variant="outline"
          size="sm"
          disabled={pending || regenerate.isPending}
          onClick={() => setConfirming(true)}
        >
          {regenerate.isPending ? aiTexts.regenerating : aiTexts.regenerate}
        </Button>
      </div>

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{aiTexts.regenerateTitle}</DialogTitle>
            <DialogDescription>{aiTexts.regenerateDescription}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                {aiTexts.cancel}
              </Button>
            </DialogClose>
            <Button disabled={regenerate.isPending} onClick={() => regenerate.mutate()}>
              {regenerate.isPending ? aiTexts.regenerating : aiTexts.regenerateConfirm}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {report.status === 'FALLBACK' && (
        <p className="rounded-lg bg-muted p-3 text-sm font-medium">
          {report.fallback_reason
            ? aiTexts.fallback[report.fallback_reason]
            : aiTexts.fallbackUnknown}
        </p>
      )}

      {pending || !report.report ? (
        <div className="grid gap-2" aria-busy="true">
          <p className="text-sm text-muted-foreground" aria-live="polite">
            {aiTexts.pending}
          </p>
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      ) : (
        <>
          <p className="text-base leading-relaxed">{report.report.summary}</p>
          <div className="grid grid-cols-2 gap-6">
            <Factors title={aiTexts.risks} factors={report.report.risk_factors} />
            <Factors title={aiTexts.positives} factors={report.report.positive_factors} />
          </div>
          {report.report.manager_questions.length > 0 && (
            <div className="grid gap-2">
              <h3 className="text-sm font-medium text-muted-foreground">{aiTexts.questions}</h3>
              <ul className="grid list-disc gap-1 pl-5 text-sm">
                {report.report.manager_questions.map((question) => (
                  <li key={question}>{question}</li>
                ))}
              </ul>
            </div>
          )}
          <Feedback key={report.id} applicationId={applicationId} report={report} />
        </>
      )}

      <p className="text-xs text-muted-foreground">
        {aiTexts.meta(
          report.model_id ?? aiTexts.template,
          report.prompt_version,
          formatDateTime(report.updated_at),
        )}
      </p>
    </section>
  )
}

function Factors({ title, factors }: { title: string; factors: Schemas['AiFactor'][] }) {
  return (
    <div className="grid content-start gap-2">
      <h3 className="text-sm font-medium text-muted-foreground">{title}</h3>
      {factors.length === 0 ? (
        <p className="text-sm text-muted-foreground">{aiTexts.noFactors}</p>
      ) : (
        <ul className="grid gap-1 text-sm">
          {factors.map((factor) => (
            <li key={factor.code}>{factor.text}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** 👍/👎 и необязательный комментарий. Повторная оценка заменяет прошлую (UPSERT). */
function Feedback({ applicationId, report }: { applicationId: string; report: Report }) {
  const commentId = useId()
  // Оценка видна сразу (оптимистично); при ошибке возвращаем прежнюю.
  const [verdict, setVerdict] = useState<Verdict | null>(null)
  const [comment, setComment] = useState('')
  const [commentSent, setCommentSent] = useState(false)

  const send = useMutation({
    mutationFn: (body: Schemas['AiFeedbackRequest']) =>
      unwrap(
        api.POST('/api/v1/manager/applications/{application_id}/ai-feedback', {
          params: { path: { application_id: applicationId } },
          body,
        }),
      ),
    meta: { invalidates: [queryKeys.manager.stats] },
    onMutate: (body) => {
      const previous = verdict
      setVerdict(body.verdict)
      return { previous }
    },
    onError: (_error, _body, context) => setVerdict(context?.previous ?? null),
    onSuccess: (_data, body) => setCommentSent(Boolean(body.comment)),
  })

  const rate = (next: Verdict) =>
    send.mutate({ ai_report_id: report.id, verdict: next, comment: comment.trim() || null })

  return (
    <div className="grid gap-3 border-t pt-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm font-medium">{aiTexts.rateTitle}</span>
        <VerdictButton
          active={verdict === 'UP'}
          disabled={send.isPending}
          onClick={() => rate('UP')}
          icon={<ThumbsUpIcon aria-hidden className="size-4" />}
          label={aiTexts.up}
        />
        <VerdictButton
          active={verdict === 'DOWN'}
          disabled={send.isPending}
          onClick={() => rate('DOWN')}
          icon={<ThumbsDownIcon aria-hidden className="size-4" />}
          label={aiTexts.down}
        />
        {verdict && (
          <Badge variant="outline" aria-live="polite">
            {aiTexts.thanks}
          </Badge>
        )}
      </div>
      {verdict && (
        <div className="grid gap-2">
          <label htmlFor={commentId} className="text-sm font-medium">
            {aiTexts.commentLabel}
          </label>
          <textarea
            id={commentId}
            rows={2}
            maxLength={MAX_DECISION_TEXT}
            aria-describedby={`${commentId}-hint`}
            value={comment}
            onChange={(event) => {
              setComment(event.target.value)
              setCommentSent(false)
            }}
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
          />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p id={`${commentId}-hint`} className="text-xs text-muted-foreground">
              {commentSent ? aiTexts.commentSent : aiTexts.commentHint}
            </p>
            <Button
              size="sm"
              variant="outline"
              disabled={!comment.trim() || commentSent || send.isPending}
              onClick={() => rate(verdict)}
            >
              {aiTexts.commentSend}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

function VerdictButton({
  active,
  disabled,
  onClick,
  icon,
  label,
}: {
  active: boolean
  disabled: boolean
  onClick: () => void
  icon: ReactNode
  label: string
}) {
  return (
    <Button
      size="sm"
      variant="outline"
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
      className={cn(active && 'border-foreground bg-accent')}
    >
      {icon}
      {label}
    </Button>
  )
}
