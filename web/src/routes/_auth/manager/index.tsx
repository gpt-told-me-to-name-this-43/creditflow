import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/_auth/manager/')({
  component: ManagerHome,
})

// Очередь и сводка — #10.
function ManagerHome() {
  return <h1 className="text-3xl font-bold">Заявки</h1>
}
