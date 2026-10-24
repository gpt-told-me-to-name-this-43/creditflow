import { CheckIcon } from 'lucide-react'
import { cn } from '@/lib/utils.ts'

interface StepperProps {
  steps: readonly { title: string; description?: string }[]
  /** Текущий шаг, с единицы. */
  current: number
  /** Шаги, на которые можно вернуться (пройденные). */
  canOpen: (step: number) => boolean
  onOpen: (step: number) => void
}

export function Stepper({ steps, current, canOpen, onOpen }: StepperProps) {
  return (
    <nav aria-label="Шаги заявки">
      <ol className="grid grid-cols-4 gap-4">
        {steps.map((step, index) => {
          const number = index + 1
          const state = number < current ? 'done' : number === current ? 'current' : 'next'
          const open = number !== current && canOpen(number)
          const content = (
            <>
              <span
                className={cn(
                  'flex size-8 shrink-0 items-center justify-center rounded-full border text-sm font-bold',
                  state === 'current' && 'border-primary bg-primary text-primary-foreground',
                  state === 'done' && 'border-foreground bg-foreground text-background',
                  state === 'next' && 'text-muted-foreground',
                )}
              >
                {state === 'done' ? <CheckIcon aria-hidden className="size-4" /> : number}
              </span>
              <span className="grid text-left">
                <span className={cn('font-semibold', state === 'next' && 'text-muted-foreground')}>
                  {step.title}
                </span>
                {step.description && (
                  <span className="text-sm text-muted-foreground">{step.description}</span>
                )}
              </span>
            </>
          )
          return (
            <li
              key={step.title}
              aria-current={state === 'current' ? 'step' : undefined}
              className={cn(
                'border-t-4 pt-3',
                state === 'next' ? 'border-border' : 'border-foreground',
                state === 'current' && 'border-primary',
              )}
            >
              {open ? (
                <button
                  type="button"
                  onClick={() => onOpen(number)}
                  className="flex items-start gap-3 rounded-md outline-none hover:opacity-80 focus-visible:ring-[3px] focus-visible:ring-ring/50"
                >
                  {content}
                </button>
              ) : (
                <div className="flex items-start gap-3">{content}</div>
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
