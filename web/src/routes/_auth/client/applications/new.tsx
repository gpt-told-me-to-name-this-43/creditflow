import { createFileRoute, redirect } from '@tanstack/react-router'
import { z } from 'zod'
import { api, unwrap } from '@/api/client.ts'
import { applicationQuery } from '@/api/queries/applications.ts'
import { consentTextsQuery } from '@/api/queries/auth.ts'
import { queryKeys } from '@/api/queries/keys.ts'
import { creditProductsQuery } from '@/api/queries/products.ts'
import { productParams } from '@/features/wizard/products.ts'
import { Wizard } from '@/features/wizard/wizard.tsx'
import { LAST_STEP, reachableStep } from '@/features/wizard/wizard-form.ts'

// Шаг мастера и id черновика переживают перезагрузку в адресе.
const searchSchema = z.object({
  step: z.number().int().min(1).max(LAST_STEP).optional().catch(undefined),
  applicationId: z.uuid().optional().catch(undefined),
})

export const Route = createFileRoute('/_auth/client/applications/new')({
  validateSearch: searchSchema,
  loaderDeps: ({ search }) => search,
  loader: async ({ context: { queryClient }, deps, preload }) => {
    if (!deps.applicationId) {
      // Наведение на «Подать заявку» не должно создавать черновик.
      if (preload) return
      // Черновик у клиента один: POST вернёт уже начатый, если он есть.
      const draft = await unwrap(api.POST('/api/v1/applications', { body: {} }))
      queryClient.setQueryData(applicationQuery(draft.id).queryKey, draft)
      void queryClient.invalidateQueries({ queryKey: queryKeys.applications.all, exact: true })
      throw redirect({
        to: '/client/applications/new',
        search: { applicationId: draft.id },
        replace: true,
      })
    }

    // Кэш мог устареть (заявку отправили, а ответ не дошёл): отдаём его сразу и
    // перечитываем в фоне — мастер сам уйдёт на страницу заявки по свежему статусу.
    const application = await queryClient.ensureQueryData({
      ...applicationQuery(deps.applicationId),
      revalidateIfStale: true,
    })
    // Отправленную заявку не редактируют — её страница со статусом.
    if (application.status !== 'DRAFT') {
      throw redirect({
        to: '/client/applications/$applicationId',
        params: { applicationId: application.id },
        replace: true,
      })
    }
    // Без шага — продолжаем с первого незаполненного; дальше сохранённого не пускаем.
    const reachable = reachableStep(application)
    const step = deps.step
      ? Math.min(deps.step, reachable)
      : application.purpose_text || application.purpose_code
        ? reachable
        : 1
    if (step !== deps.step) {
      throw redirect({
        to: '/client/applications/new',
        search: { applicationId: application.id, step },
        replace: true,
      })
    }

    await Promise.all([
      queryClient.ensureQueryData(creditProductsQuery()),
      queryClient.ensureQueryData(consentTextsQuery()),
      step === 3 && queryClient.ensureQueryData(creditProductsQuery(productParams(application))),
    ])
  },
  component: NewApplication,
})

function NewApplication() {
  const { applicationId, step } = Route.useSearch()
  // До редиректа лоадера (создание черновика) показывать нечего.
  if (!applicationId || !step) return null
  return (
    <section className="grid gap-8">
      <h1 className="text-3xl font-bold">Новая заявка</h1>
      <Wizard key={applicationId} applicationId={applicationId} step={step} />
    </section>
  )
}
