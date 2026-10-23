import type { components } from '@/api/schema.d.ts'
import { timelineText, timelineTitle } from '@/content/application.ts'
import { formatDateTime } from '@/lib/dates.ts'

type TimelineEvent = components['schemas']['TimelineEvent']

/** История заявки из событий бэка: новые сверху. */
export function Timeline({ events }: { events: TimelineEvent[] }) {
  const ordered = [...events].reverse()
  return (
    <section className="grid content-start gap-4" aria-labelledby="timeline-title">
      <h2 id="timeline-title" className="text-lg font-semibold">
        {timelineTitle}
      </h2>
      <ol className="grid gap-4 border-l pl-6">
        {ordered.map((event, index) => (
          <li key={`${event.created_at}-${event.to_status}`} className="relative grid gap-0.5">
            <span
              aria-hidden
              className={
                index === 0
                  ? 'absolute top-1.5 -left-[1.95rem] size-3 rounded-full bg-primary'
                  : 'absolute top-1.5 -left-[1.95rem] size-3 rounded-full border-2 border-border bg-background'
              }
            />
            <span className={index === 0 ? 'font-semibold' : undefined}>
              {timelineText(event.from_status, event.to_status)}
            </span>
            <time dateTime={event.created_at} className="text-sm text-muted-foreground">
              {formatDateTime(event.created_at)}
            </time>
          </li>
        ))}
      </ol>
    </section>
  )
}
