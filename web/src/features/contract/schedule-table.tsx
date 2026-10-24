import { createColumnHelper, tableFeatures, useTable } from '@tanstack/react-table'
import { useState } from 'react'
import type { components } from '@/api/schema.d.ts'
import { Button } from '@/components/ui/button.tsx'
import { scheduleTexts } from '@/content/contract.ts'
import { formatDate } from '@/lib/dates.ts'
import { formatMoney, sumMoney } from '@/lib/money.ts'
import { cn } from '@/lib/utils.ts'

type ScheduleItem = components['schemas']['ScheduleItem']

const COLLAPSED_ROWS = 3

const features = tableFeatures({})
const helper = createColumnHelper<typeof features, ScheduleItem>()
const money = (value: string) => formatMoney(value)

const columns = helper.columns([
  helper.accessor('number', { header: scheduleTexts.number }),
  helper.accessor('due_date', {
    header: scheduleTexts.dueDate,
    cell: (info) => formatDate(info.getValue()),
  }),
  helper.accessor('payment_rub', {
    header: scheduleTexts.payment,
    cell: (info) => money(info.getValue()),
  }),
  helper.accessor('principal_rub', {
    header: scheduleTexts.principal,
    cell: (info) => money(info.getValue()),
  }),
  helper.accessor('interest_rub', {
    header: scheduleTexts.interest,
    cell: (info) => money(info.getValue()),
  }),
  helper.accessor('balance_after_rub', {
    header: scheduleTexts.balance,
    cell: (info) => money(info.getValue()),
  }),
])

const NUMERIC = new Set(['payment_rub', 'principal_rub', 'interest_rub', 'balance_after_rub'])

/**
 * График платежей из договора: первые три строки, «Показать весь график» и итог.
 * Итог — сумма строк графика из API (точно, в копейках), сам график не пересчитываем.
 */
export function ScheduleTable({ schedule }: { schedule: ScheduleItem[] }) {
  const [expanded, setExpanded] = useState(false)
  const table = useTable({ features, columns, data: schedule })
  const rows = table.getRowModel().rows
  const visible = expanded ? rows : rows.slice(0, COLLAPSED_ROWS)
  const totals = {
    payment: sumMoney(schedule.map((item) => item.payment_rub)),
    principal: sumMoney(schedule.map((item) => item.principal_rub)),
    interest: sumMoney(schedule.map((item) => item.interest_rub)),
  }

  return (
    <div className="grid gap-3">
      <table className="w-full text-left tabular-nums" aria-label={scheduleTexts.title}>
        <thead>
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id} className="border-b text-sm text-muted-foreground">
              {group.headers.map((header) => (
                <th
                  key={header.id}
                  scope="col"
                  className={cn('py-2 pr-4 font-medium', NUMERIC.has(header.id) && 'text-right')}
                >
                  {header.isPlaceholder ? null : <table.FlexRender header={header} />}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {visible.map((row) => (
            <tr key={row.id} className="border-b">
              {row.getAllCells().map((cell) => (
                <td
                  key={cell.id}
                  className={cn('py-2 pr-4', NUMERIC.has(cell.column.id) && 'text-right')}
                >
                  <table.FlexRender cell={cell} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="font-bold">
            <th scope="row" colSpan={2} className="py-2 pr-4">
              {scheduleTexts.total}
            </th>
            <td className="py-2 pr-4 text-right">{money(totals.payment)}</td>
            <td className="py-2 pr-4 text-right">{money(totals.principal)}</td>
            <td className="py-2 pr-4 text-right">{money(totals.interest)}</td>
            <td />
          </tr>
        </tfoot>
      </table>
      {rows.length > COLLAPSED_ROWS && (
        <Button
          type="button"
          variant="outline"
          className="justify-self-start"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? scheduleTexts.collapse : scheduleTexts.showAll(rows.length)}
        </Button>
      )}
    </div>
  )
}
