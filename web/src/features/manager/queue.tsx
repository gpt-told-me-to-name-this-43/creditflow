import { useSuspenseQuery } from '@tanstack/react-query'
import { createColumnHelper, tableFeatures, useTable } from '@tanstack/react-table'
import { Link, useNavigate } from '@tanstack/react-router'
import { OctagonAlertIcon } from 'lucide-react'
import { useMemo } from 'react'
import { managerQueueQuery, managerStatsQuery } from '@/api/queries/manager.ts'
import type { components } from '@/api/schema.d.ts'
import { EmptyState } from '@/components/ui/empty-state.tsx'
import { StatusBadge } from '@/components/ui/status-badge.tsx'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip.tsx'
import {
  cardTexts,
  queueTabs,
  queueTexts,
  type QueueStatus,
  stopFactorTexts,
} from '@/content/manager.ts'
import { formatDateTime, formatDuration } from '@/lib/dates.ts'
import { formatMoney } from '@/lib/money.ts'
import { useNow } from '@/lib/use-now.ts'
import { cn } from '@/lib/utils.ts'
import { productName } from '@/content/manager.ts'
import { SuggestionBadge } from './suggestion-badge.tsx'

type QueueItem = components['schemas']['QueueItem']

const features = tableFeatures({})
const helper = createColumnHelper<typeof features, QueueItem>()

/** Вкладки статусов с количеством из сводки; активная — в адресе (`?status=`). */
export function QueueTabs({ current }: { current: QueueStatus }) {
  const { data: stats } = useSuspenseQuery(managerStatsQuery())
  return (
    <nav aria-label={queueTexts.tabsLabel}>
      <ul className="flex flex-wrap gap-2">
        {queueTabs.map((tab) => {
          const count = stats.applications_by_status[tab.status] ?? 0
          const active = tab.status === current
          return (
            <li key={tab.status}>
              <Link
                to="/manager"
                search={{ status: tab.status }}
                aria-current={active ? 'page' : undefined}
                className={cn(
                  'flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-semibold outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50',
                  active && 'border-foreground bg-foreground text-background hover:bg-foreground',
                )}
              >
                {tab.label}
                <span
                  className={cn(
                    'rounded-full px-2 text-xs tabular-nums',
                    active ? 'bg-background text-foreground' : 'bg-muted',
                  )}
                >
                  {count}
                </span>
              </Link>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}

/**
 * Очередь по статусу: старые сверху. Строка открывается кликом и с клавиатуры —
 * название компании это ссылка на карточку.
 */
export function Queue({ status }: { status: QueueStatus }) {
  const { data } = useSuspenseQuery(managerQueueQuery(status))
  const navigate = useNavigate()
  const now = useNow(30_000)

  const rows = useMemo(
    () => [...data].sort((a, b) => (a.submitted_at ?? '').localeCompare(b.submitted_at ?? '')),
    [data],
  )

  const columns = useMemo(
    () =>
      helper.columns([
        helper.accessor('company_name', {
          header: queueTexts.company,
          cell: ({ row }) => (
            <div className="grid gap-0.5">
              <Link
                to="/manager/applications/$applicationId"
                params={{ applicationId: row.original.id }}
                className="font-semibold outline-none hover:underline focus-visible:ring-[3px] focus-visible:ring-ring/50"
                onClick={(event) => event.stopPropagation()}
              >
                {row.original.company_name}
              </Link>
              <span className="text-sm text-muted-foreground">
                {queueTexts.inn(row.original.company_inn)}
              </span>
            </div>
          ),
        }),
        helper.accessor('requested_amount_rub', {
          header: queueTexts.request,
          cell: ({ row }) => {
            const { requested_amount_rub: amount, term_months: term, product_id } = row.original
            return (
              <div className="grid gap-0.5">
                <span className="font-semibold tabular-nums">
                  {amount ? formatMoney(amount, { kopecks: false }) : '—'}
                  {term ? ` · ${cardTexts.months(term)}` : ''}
                </span>
                <span className="text-sm text-muted-foreground">{productName(product_id)}</span>
              </div>
            )
          },
        }),
        helper.accessor('status', {
          header: queueTexts.status,
          cell: (info) => <StatusBadge status={info.getValue()} />,
        }),
        helper.accessor('suggested_action', {
          header: queueTexts.suggestion,
          cell: (info) => {
            const value = info.getValue()
            return value ? (
              <SuggestionBadge action={value} />
            ) : (
              <span className="text-sm text-muted-foreground">{queueTexts.noSuggestion}</span>
            )
          },
        }),
        helper.accessor('blocking_codes', {
          header: queueTexts.stopFactors,
          cell: (info) => {
            const codes = info.getValue()
            if (codes.length === 0) {
              return (
                <span className="text-sm text-muted-foreground">{queueTexts.noStopFactors}</span>
              )
            }
            const text = codes.map((code) => stopFactorTexts[code]).join('; ')
            return (
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    // Видимое число входит в имя (WCAG 2.5.3 «label in name»).
                    aria-label={`${queueTexts.stopFactors} ${codes.length}: ${text}`}
                    onClick={(event) => event.stopPropagation()}
                    className="flex items-center gap-1 rounded-md font-semibold text-destructive outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
                  >
                    <OctagonAlertIcon aria-hidden className="size-5" />
                    {codes.length}
                  </button>
                </TooltipTrigger>
                <TooltipContent>{text}</TooltipContent>
              </Tooltip>
            )
          },
        }),
        helper.accessor('submitted_at', {
          header: queueTexts.submitted,
          cell: (info) => {
            const value = info.getValue()
            if (!value) return '—'
            return (
              <div className="grid gap-0.5">
                <time dateTime={value} className="text-sm">
                  {formatDateTime(value)}
                </time>
                <span className="text-sm text-muted-foreground">
                  {queueTexts.waiting(formatDuration((now - Date.parse(value)) / 1000))}
                </span>
              </div>
            )
          },
        }),
      ]),
    [now],
  )

  const table = useTable({ features, columns, data: rows })

  if (rows.length === 0) return <EmptyState title={queueTexts.empty[status]} />

  return (
    <div className="overflow-hidden rounded-xl border">
      <table className="w-full text-left" aria-label={queueTexts.tableLabel}>
        <thead className="bg-muted text-sm text-muted-foreground">
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id}>
              {group.headers.map((header) => (
                <th key={header.id} scope="col" className="px-4 py-3 font-medium">
                  {header.isPlaceholder ? null : <table.FlexRender header={header} />}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr
              key={row.id}
              className="cursor-pointer border-t transition-colors hover:bg-accent"
              onClick={() =>
                void navigate({
                  to: '/manager/applications/$applicationId',
                  params: { applicationId: row.original.id },
                })
              }
            >
              {row.getAllCells().map((cell) => (
                <td key={cell.id} className="px-4 py-3 align-top">
                  <table.FlexRender cell={cell} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
