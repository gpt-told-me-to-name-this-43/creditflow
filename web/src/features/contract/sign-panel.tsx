import { useMutation, useQueryClient } from '@tanstack/react-query'
import { InfoIcon } from 'lucide-react'
import { useId, useRef, useState } from 'react'
import { api, unwrap } from '@/api/client.ts'
import { errorMessage, isApiError, isStaleSession } from '@/api/errors.ts'
import { markSession, storeApplication } from '@/api/queries/applications.ts'
import { queryKeys } from '@/api/queries/keys.ts'
import type { components } from '@/api/schema.d.ts'
import { Button } from '@/components/ui/button.tsx'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card.tsx'
import { Checkbox } from '@/components/ui/checkbox.tsx'
import { CodeInput } from '@/components/ui/code-input.tsx'
import { signTexts } from '@/content/contract.ts'
import { formatCountdown, secondsUntil } from '@/lib/dates.ts'
import { useIdempotentMutation } from '@/lib/idempotency.ts'
import { useNow } from '@/lib/use-now.ts'

type Schemas = components['schemas']
type Application = Schemas['ClientApplicationView']

function challengeError(error: unknown): string {
  if (isApiError(error, 'TOO_MANY_ATTEMPTS')) {
    const details = error.details as Partial<Schemas['TooManyAttemptsDetails']> | undefined
    if (details?.scope === 'CHALLENGE_ISSUE' && details.retry_after_seconds) {
      return signTexts.tooManyCodes(details.retry_after_seconds)
    }
  }
  return errorMessage(error)
}

/**
 * Подписание: согласие → код (`sign/challenge`) → ввод → `sign`. Демо-код показываем только
 * из `demo_code` ответа. Таймер — до `expires_at`, остаток попыток — из ответа и из 422.
 */
export function SignPanel({ application }: { application: Application }) {
  const queryClient = useQueryClient()
  const agreeId = useId()
  const codeId = useId()
  const [agreed, setAgreed] = useState(false)
  const [challenge, setChallenge] = useState<Schemas['SignChallenge'] | null>(null)
  // Когда пришёл код: таймер не должен показывать время до его получения.
  const [issuedAt, setIssuedAt] = useState(0)
  const [code, setCode] = useState('')
  const [attempts, setAttempts] = useState(0)
  // Код погашен: попытки кончились или бэк сказал, что он истёк.
  const [burned, setBurned] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const now = useNow(1000, challenge !== null && !burned)
  // Действующий challenge: ответ sign для заменённого кода не должен менять текущий.
  const currentChallenge = useRef<string | null>(null)

  const requestCode = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/applications/{application_id}/sign/challenge', {
          params: { path: { application_id: application.id } },
          body: { revision: application.revision },
        }),
      ),
    meta: { errorToast: false, invalidates: [queryKeys.applications.detail(application.id)] },
    onSuccess: (issued) => {
      currentChallenge.current = issued.challenge_id
      setChallenge(issued)
      setIssuedAt(Date.now())
      setAttempts(issued.attempts_remaining)
      setCode('')
      setBurned(false)
      setError(null)
    },
    onError: (failure) => {
      if (!isStaleSession(failure)) setError(challengeError(failure))
    },
  })

  const sign = useIdempotentMutation({
    mutationFn: (body: Schemas['SignRequest'], idempotencyKey: string) =>
      unwrap(
        api.POST('/api/v1/applications/{application_id}/sign', {
          params: {
            path: { application_id: application.id },
            header: { 'Idempotency-Key': idempotencyKey },
          },
          body,
        }),
      ),
    meta: { errorToast: false, invalidates: [queryKeys.applications.all] },
    onMutate: markSession,
    onSuccess: (signed, _body, mark) => {
      storeApplication(queryClient, signed, mark)
    },
    onError: (failure, { challenge_id }) => {
      if (challenge_id !== currentChallenge.current) return
      setCode('')
      if (isApiError(failure, 'SIGN_CODE_INVALID')) {
        const details = failure.details as Partial<Schemas['SignCodeInvalidDetails']> | undefined
        const left = details?.remaining_attempts ?? Math.max(0, attempts - 1)
        setAttempts(left)
        setError(signTexts.wrongCode(left))
      } else if (isApiError(failure, 'TOO_MANY_ATTEMPTS')) {
        setAttempts(0)
        setBurned(true)
        setError(signTexts.tooManyAttempts)
      } else if (isApiError(failure, 'SIGN_CHALLENGE_EXPIRED')) {
        setBurned(true)
        setError(signTexts.expired)
      } else {
        setError(errorMessage(failure))
      }
    },
  })

  const actions = application.allowed_actions
  if (!actions.includes('SIGN') && !actions.includes('REQUEST_SIGN_CODE')) return null

  const left = challenge ? secondsUntil(challenge.expires_at, Math.max(now, issuedAt)) : 0
  const expired = challenge !== null && (burned || left === 0)
  // Sign и запрос кода взаимоисключающие: новый код заменяет тот, что сейчас проверяется.
  const busy = sign.isPending || requestCode.isPending
  const canSign = agreed && challenge && !expired && code.length === 6 && !busy

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xl">{signTexts.title}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-6">
        <div className="flex items-start gap-3">
          <Checkbox
            id={agreeId}
            checked={agreed}
            onCheckedChange={(checked) => setAgreed(checked === true)}
            className="mt-0.5"
          />
          <label htmlFor={agreeId} className="leading-relaxed">
            {signTexts.agree}
          </label>
        </div>

        {challenge && (
          <div className="grid gap-4">
            <p>{signTexts.codeSent}</p>
            {challenge.demo_code && (
              <p className="flex items-center gap-2 justify-self-start rounded-lg border border-dashed px-4 py-2 font-semibold">
                <InfoIcon aria-hidden className="size-4" />
                {signTexts.demoBanner(challenge.demo_code)}
              </p>
            )}
            <div className="grid gap-2">
              <label htmlFor={codeId} className="text-sm font-medium">
                {signTexts.codeLabel}
              </label>
              <CodeInput
                id={codeId}
                value={code}
                onChange={setCode}
                disabled={expired}
                aria-invalid={error ? true : undefined}
                aria-describedby={`${codeId}-status${error ? ` ${codeId}-error` : ''}`}
              />
              <p id={`${codeId}-status`} className="text-sm text-muted-foreground">
                {expired
                  ? signTexts.expired
                  : `${signTexts.codeHint}. ${signTexts.expiresIn(formatCountdown(left))}. ${signTexts.attemptsLeft(attempts)}`}
              </p>
            </div>
          </div>
        )}

        {error && (
          <p id={`${codeId}-error`} role="alert" className="font-medium text-destructive">
            {error}
          </p>
        )}

        <div className="flex flex-wrap gap-3">
          {challenge ? (
            <>
              <Button
                size="lg"
                disabled={!canSign}
                onClick={() =>
                  sign.mutate({
                    challenge_id: challenge.challenge_id,
                    code,
                    revision: Math.max(challenge.revision, application.revision),
                  })
                }
              >
                {sign.isPending ? signTexts.signing : signTexts.sign}
              </Button>
              <Button
                size="lg"
                variant="outline"
                disabled={busy}
                onClick={() => requestCode.mutate()}
              >
                {signTexts.newCode}
              </Button>
            </>
          ) : (
            <Button
              size="lg"
              disabled={!agreed || requestCode.isPending}
              onClick={() => requestCode.mutate()}
            >
              {requestCode.isPending ? signTexts.requesting : signTexts.requestCode}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
