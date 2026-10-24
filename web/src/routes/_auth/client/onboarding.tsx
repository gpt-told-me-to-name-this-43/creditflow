import { createFileRoute } from '@tanstack/react-router'
import { consentTextsQuery } from '@/api/queries/auth.ts'
import { CompanyBinding } from '@/features/onboarding/company-binding.tsx'

export const Route = createFileRoute('/_auth/client/onboarding')({
  loader: ({ context }) => context.queryClient.ensureQueryData(consentTextsQuery()),
  component: OnboardingPage,
})

function OnboardingPage() {
  return (
    <section className="grid gap-8">
      <div className="grid max-w-2xl gap-2">
        <h1 className="text-3xl font-bold">Подключите компанию</h1>
        <p className="text-muted-foreground">
          Укажите ИНН — найдём компанию в государственном реестре и проверим, что вы её руководитель
          или сами ведёте ИП. Подать заявку можно будет сразу после этого.
        </p>
      </div>
      <CompanyBinding />
    </section>
  )
}
