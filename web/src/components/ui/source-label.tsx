import { SparklesIcon, WandIcon } from 'lucide-react'
import type { components } from '@/api/schema.d.ts'
import { sourceLabels } from '@/content/wizard.ts'
import { Badge } from './badge.tsx'
import { Tooltip, TooltipContent, TooltipTrigger } from './tooltip.tsx'

type FieldSource = components['schemas']['FieldSource']

/**
 * Метка поля, заполненного автоматически: правилами (`RULES`) или ИИ (`LLM`).
 * У ручного значения (`MANUAL`) метки нет. В подсказке — фрагмент текста клиента.
 */
export function SourceLabel({ source, matched }: { source: FieldSource; matched?: string | null }) {
  if (source === 'MANUAL') return null
  const text = sourceLabels[source]
  const Icon = source === 'LLM' ? SparklesIcon : WandIcon
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className="rounded-md outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
        >
          <Badge variant="secondary">
            <Icon aria-hidden className="size-3" />
            {text.label}
          </Badge>
        </button>
      </TooltipTrigger>
      <TooltipContent>{matched ? text.tooltip(matched) : sourceLabels.noMatch}</TooltipContent>
    </Tooltip>
  )
}
