import { useForm, useStore } from '@tanstack/react-form'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRouter } from '@tanstack/react-router'
import { Check } from 'lucide-react'
import { z } from 'zod'
import { errorMessage } from '@/api/errors.ts'
import { demoAccountsQuery } from '@/api/queries/auth.ts'
import type { components } from '@/api/schema.d.ts'
import { Button } from '@/components/ui/button.tsx'
import { firstError, FormField } from '@/components/ui/form-field.tsx'
import { Input } from '@/components/ui/input.tsx'
import { loginTexts } from '@/content/auth.ts'
import { demoScenarioTexts, demoTexts } from '@/content/demo.ts'
import { signIn } from '@/lib/auth.ts'
import { cn } from '@/lib/utils.ts'
import { logIn } from './log-in.ts'

type DemoAccount = components['schemas']['DemoAccount']

const schema = z.object({
  login: z.string().trim().min(1, 'Введите логин'),
  password: z.string().min(1, 'Введите пароль'),
})

export function LoginForm() {
  const router = useRouter()
  const queryClient = useQueryClient()
  // После входа гард /login сам уводит на redirect или в кабинет роли.
  const login = useMutation({
    mutationFn: logIn,
    meta: { errorToast: false },
    onSuccess: (session) => signIn(session, { router, queryClient }),
  })

  const form = useForm({
    defaultValues: { login: '', password: '' },
    validators: { onBlur: schema, onSubmit: schema },
    onSubmit: ({ value }) =>
      // Ошибку показывает login.error под формой.
      login
        .mutateAsync({ login: value.login.trim(), password: value.password })
        .catch(() => undefined),
  })

  const selectedLogin = useStore(form.store, (state) => state.values.login)

  const fillDemo = (account: DemoAccount) => {
    form.setFieldValue('login', account.login)
    form.setFieldValue('password', account.password)
    login.reset()
  }

  return (
    <div className="grid gap-10">
      <div className="mx-auto grid w-full max-w-md gap-8 rounded-2xl border bg-card p-10 text-card-foreground shadow-sm">
        <div className="grid gap-3 text-center">
          <span aria-hidden className="mx-auto h-1 w-12 rounded-full bg-primary" />
          <h1 className="text-3xl font-bold">{loginTexts.title}</h1>
          <p className="text-muted-foreground">{loginTexts.description}</p>
        </div>
        <form
          noValidate
          className="grid gap-5"
          onSubmit={(event) => {
            event.preventDefault()
            void form.handleSubmit()
          }}
        >
          <form.Field name="login">
            {(field) => (
              <FormField
                id="login"
                label="Логин"
                error={field.state.meta.isTouched ? firstError(field.state.meta.errors) : undefined}
              >
                {(props) => (
                  <Input
                    {...props}
                    autoComplete="username"
                    value={field.state.value}
                    onChange={(event) => field.handleChange(event.target.value)}
                    onBlur={field.handleBlur}
                  />
                )}
              </FormField>
            )}
          </form.Field>
          <form.Field name="password">
            {(field) => (
              <FormField
                id="password"
                label="Пароль"
                error={field.state.meta.isTouched ? firstError(field.state.meta.errors) : undefined}
              >
                {(props) => (
                  <Input
                    {...props}
                    type="password"
                    autoComplete="current-password"
                    value={field.state.value}
                    onChange={(event) => field.handleChange(event.target.value)}
                    onBlur={field.handleBlur}
                  />
                )}
              </FormField>
            )}
          </form.Field>
          {login.isError && (
            <p role="alert" className="font-medium text-destructive">
              {errorMessage(login.error)}
            </p>
          )}
          <Button type="submit" size="lg" className="mt-1 w-full" disabled={login.isPending}>
            {login.isPending ? loginTexts.submitting : loginTexts.submit}
          </Button>
        </form>
      </div>
      <DemoAccounts selected={selectedLogin} onPick={fillDemo} />
    </div>
  )
}

/** Демо-учётки есть только при DEMO_AUTH_ENABLED: при ошибке блок просто не показываем. */
function DemoAccounts({
  selected,
  onPick,
}: {
  selected: string
  onPick: (account: DemoAccount) => void
}) {
  const { data: accounts } = useQuery({ ...demoAccountsQuery(), retry: false })
  if (!accounts?.length) return null
  const groups = [
    { title: demoTexts.clients, items: accounts.filter((account) => account.role !== 'MANAGER') },
    { title: demoTexts.managers, items: accounts.filter((account) => account.role === 'MANAGER') },
  ].filter((group) => group.items.length > 0)

  return (
    <section aria-labelledby="demo-title" className="mx-auto grid w-full max-w-5xl gap-6">
      <div className="flex items-center gap-4">
        <span aria-hidden className="h-px flex-1 bg-border" />
        <div className="grid gap-1 text-center">
          <h2 id="demo-title" className="text-lg font-semibold">
            {demoTexts.title}
          </h2>
          <p className="text-sm text-muted-foreground">{demoTexts.description}</p>
        </div>
        <span aria-hidden className="h-px flex-1 bg-border" />
      </div>
      {groups.map((group) => (
        <div key={group.title} className="grid gap-3">
          <h3 className="text-sm font-semibold text-muted-foreground">{group.title}</h3>
          <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {group.items.map((account) => (
              <li key={account.login}>
                <DemoAccountButton
                  account={account}
                  active={account.login === selected.trim()}
                  onPick={onPick}
                />
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  )
}

function DemoAccountButton({
  account,
  active,
  onPick,
}: {
  account: DemoAccount
  active: boolean
  onPick: (account: DemoAccount) => void
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={() => onPick(account)}
      className={cn(
        'flex h-full w-full items-center gap-3 rounded-xl border bg-card px-4 py-3 text-left transition-colors outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50',
        active && 'border-primary',
      )}
    >
      <span
        aria-hidden
        className="grid size-10 shrink-0 place-items-center rounded-full bg-secondary text-sm font-bold text-secondary-foreground"
      >
        {initials(account.label)}
      </span>
      <span className="grid min-w-0 flex-1 gap-0.5">
        <span className="truncate font-semibold">{account.label}</span>
        <span className="text-sm text-muted-foreground">
          {demoScenarioTexts[account.scenario] ?? account.scenario}
        </span>
      </span>
      {active && <Check aria-hidden className="size-5 shrink-0 text-primary-text" />}
    </button>
  )
}

/** «Иванов Пётр Сергеевич» → «ИП». */
function initials(name: string) {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((word) => word.charAt(0))
    .join('')
    .toUpperCase()
}
