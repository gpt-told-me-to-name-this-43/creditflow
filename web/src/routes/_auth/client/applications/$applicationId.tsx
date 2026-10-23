import { createFileRoute } from '@tanstack/react-router'

// Карточка заявки со статусом, таймлайном и действиями — фаза 6.
export const Route = createFileRoute('/_auth/client/applications/$applicationId')({
  component: ApplicationPage,
})

function ApplicationPage() {
  return <h1 className="text-3xl font-bold">Заявка</h1>
}
