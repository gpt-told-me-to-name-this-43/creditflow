import type * as React from 'react'
import { cn } from '@/lib/utils.ts'

interface EmptyStateProps {
  title: string
  description?: string
  /** Кнопка или ссылка «что делать дальше». */
  action?: React.ReactNode
  className?: string
}

export function EmptyState({ title, description, action, className }: EmptyStateProps) {
  return (
    <section
      className={cn(
        'flex flex-col items-center gap-3 rounded-xl border border-dashed px-6 py-12 text-center',
        className,
      )}
    >
      <h2 className="text-lg font-semibold">{title}</h2>
      {description && <p className="max-w-md text-muted-foreground">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </section>
  )
}
