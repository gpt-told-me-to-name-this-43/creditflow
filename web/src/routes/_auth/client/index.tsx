import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/_auth/client/')({
  component: ClientHome,
})

// Список заявок — фаза 4 плана.
function ClientHome() {
  return <h1 className="text-3xl font-bold">Мои заявки</h1>
}
