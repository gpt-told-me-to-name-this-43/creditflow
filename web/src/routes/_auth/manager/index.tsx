import { createFileRoute } from '@tanstack/react-router'
import { z } from 'zod'
import { managerQueueQuery, managerStatsQuery } from '@/api/queries/manager.ts'
import { queueTabs, queueTexts } from '@/content/manager.ts'
import { Queue, QueueTabs } from '@/features/manager/queue.tsx'
import { StatsSummary } from '@/features/manager/stats.tsx'

const STATUSES = queueTabs.map((tab) => tab.status) as [
  (typeof queueTabs)[number]['status'],
  ...(typeof queueTabs)[number]['status'][],
]

// Вкладка очереди — в адресе: ссылкой можно поделиться, перезагрузка её не теряет.
const searchSchema = z.object({
  status: z.enum(STATUSES).catch('UNDER_REVIEW'),
})

export const Route = createFileRoute('/_auth/manager/')({
  validateSearch: searchSchema,
  loaderDeps: ({ search }) => ({ status: search.status }),
  loader: ({ context: { queryClient }, deps }) =>
    Promise.all([
      queryClient.ensureQueryData(managerStatsQuery()),
      queryClient.ensureQueryData(managerQueueQuery(deps.status)),
    ]),
  component: ManagerHome,
})

function ManagerHome() {
  const { status } = Route.useSearch()
  return (
    <section className="grid gap-8">
      <h1 className="text-3xl font-bold">{queueTexts.title}</h1>
      <StatsSummary />
      <div className="grid gap-4">
        <QueueTabs current={status} />
        <Queue status={status} />
      </div>
    </section>
  )
}
