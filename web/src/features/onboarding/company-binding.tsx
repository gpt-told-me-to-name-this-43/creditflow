import { useForm } from '@tanstack/react-form'
import { useMutation, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useId } from 'react'
import { z } from 'zod'
import { api, unwrap } from '@/api/client.ts'
import { errorMessage, isApiError } from '@/api/errors.ts'
import { consentTextsQuery } from '@/api/queries/auth.ts'
import { queryKeys } from '@/api/queries/keys.ts'
import type { components } from '@/api/schema.d.ts'
import { Button } from '@/components/ui/button.tsx'
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card.tsx'
import { Checkbox } from '@/components/ui/checkbox.tsx'
import { firstError, FormField } from '@/components/ui/form-field.tsx'
import { Input } from '@/components/ui/input.tsx'
import { bindingErrors, errorMessages } from '@/content/errors.ts'
import { formatDate } from '@/lib/dates.ts'
import { isValidInn, normalizeInn } from '@/lib/inn.ts'

type Company = components['schemas']['Company']

const innSchema = z.string().refine(isValidInn, errorMessages.INVALID_INN)

const LEGAL_FORMS: Record<Company['legal_form'], string> = {
  LLC: 'Организация',
  IE: 'Индивидуальный предприниматель',
}

export function CompanyBinding() {
  const { data: consents } = useSuspenseQuery(consentTextsQuery())
  const consent = consents.find((item) => item.type === 'PD_PROCESSING')
  const queryClient = useQueryClient()
  const consentId = useId()

  const bind = useMutation({
    mutationFn: (inn: string) =>
      unwrap(
        api.POST('/api/v1/onboarding/company-binding', {
          body: { inn, pd_consent_version: consent?.version ?? '' },
        }),
      ),
    // Ошибки привязки объясняем на экране, рядом с формой, а не тостом.
    meta: { errorToast: false },
    onSuccess: async (company) => {
      queryClient.setQueryData(queryKeys.company, company)
      // GET /auth/me читает гард кабинета: без свежего company_id он вернёт сюда же.
      await queryClient.invalidateQueries({ queryKey: queryKeys.me, refetchType: 'all' })
    },
  })

  const form = useForm({
    defaultValues: { inn: '', consent: false },
    onSubmit: ({ value }) => bind.mutateAsync(value.inn).catch(() => undefined),
  })

  if (bind.isSuccess) return <CompanyFound company={bind.data} />

  const unavailable = isApiError(bind.error) && bind.error.status === 503

  return (
    <form
      noValidate
      className="grid max-w-xl gap-6"
      onSubmit={(event) => {
        event.preventDefault()
        void form.handleSubmit()
      }}
    >
      <form.Field name="inn" validators={{ onBlur: innSchema, onSubmit: innSchema }}>
        {(field) => (
          <FormField
            id="inn"
            label="ИНН компании или ИП"
            hint="10 цифр у организации, 12 — у индивидуального предпринимателя"
            error={field.state.meta.isTouched ? firstError(field.state.meta.errors) : undefined}
          >
            {(props) => (
              <Input
                {...props}
                inputMode="numeric"
                autoComplete="off"
                maxLength={12}
                className="max-w-xs text-lg tracking-wide"
                value={field.state.value}
                onChange={(event) => field.handleChange(normalizeInn(event.target.value))}
                onBlur={field.handleBlur}
              />
            )}
          </FormField>
        )}
      </form.Field>

      <form.Field name="consent">
        {(field) => (
          <div className="flex items-start gap-3">
            <Checkbox
              id={consentId}
              checked={field.state.value}
              onCheckedChange={(checked) => field.handleChange(checked === true)}
              className="mt-0.5"
            />
            <label htmlFor={consentId} className="text-sm leading-relaxed">
              {consent?.text}
            </label>
          </div>
        )}
      </form.Field>

      {bind.isError && (
        <div role="alert" className="grid justify-items-start gap-3">
          <p className="font-medium text-destructive">
            {unavailable ? bindingErrors.registryUnavailable : errorMessage(bind.error)}
          </p>
        </div>
      )}

      <form.Subscribe selector={(state) => state.values.consent}>
        {(consentGiven) => (
          <Button
            type="submit"
            size="lg"
            className="justify-self-start"
            disabled={!consentGiven || !consent || bind.isPending}
          >
            {bind.isPending
              ? 'Ищем компанию…'
              : unavailable
                ? bindingErrors.retry
                : 'Найти компанию'}
          </Button>
        )}
      </form.Subscribe>
    </form>
  )
}

function CompanyFound({ company }: { company: Company }) {
  return (
    <Card className="max-w-xl" role="status">
      <CardHeader>
        <CardTitle className="text-2xl">Мы нашли вашу компанию</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2">
          <dt className="text-muted-foreground">Название</dt>
          <dd className="font-semibold">{company.name}</dd>
          <dt className="text-muted-foreground">ИНН</dt>
          <dd>{company.inn}</dd>
          <dt className="text-muted-foreground">Форма</dt>
          <dd>{LEGAL_FORMS[company.legal_form]}</dd>
          <dt className="text-muted-foreground">Дата регистрации</dt>
          <dd>{formatDate(company.registered_at)}</dd>
        </dl>
      </CardContent>
      <CardFooter>
        <Button asChild size="lg">
          <Link to="/client">Перейти к заявкам</Link>
        </Button>
      </CardFooter>
    </Card>
  )
}
