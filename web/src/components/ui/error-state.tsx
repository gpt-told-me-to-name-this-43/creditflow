import { CircleAlertIcon } from 'lucide-react'
import { pageErrors } from '@/content/errors.ts'
import { Button } from './button.tsx'

interface ErrorStateProps {
  title?: string
  description?: string
  onRetry?: () => void
}

export function ErrorState({
  title = pageErrors.unexpected.title,
  description = pageErrors.unexpected.description,
  onRetry,
}: ErrorStateProps) {
  return (
    <section role="alert" className="flex flex-col items-center gap-3 px-6 py-12 text-center">
      <CircleAlertIcon className="size-8 text-destructive" aria-hidden />
      <h2 className="text-lg font-semibold">{title}</h2>
      <p className="max-w-md text-muted-foreground">{description}</p>
      {onRetry && (
        <Button variant="outline" onClick={onRetry} className="mt-2">
          {pageErrors.unexpected.action}
        </Button>
      )}
    </section>
  )
}
