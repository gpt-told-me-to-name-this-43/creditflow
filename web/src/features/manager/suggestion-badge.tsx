import type { SuggestedAction } from '@/api/enums.ts'
import { Badge } from '@/components/ui/badge.tsx'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip.tsx'
import { suggestedActionTexts } from '@/content/manager.ts'

// Рекомендация — не решение: нейтральные бейджи, стоп-фактор — контурный с акцентом ошибки.
const VARIANTS = {
  ELIGIBLE_FOR_MANAGER_REVIEW: 'success',
  COUNTER_OFFER_CANDIDATE: 'secondary',
  MANUAL_REVIEW: 'outline',
  BLOCKED_BY_RULE: 'destructive',
} as const satisfies Record<SuggestedAction, 'success' | 'secondary' | 'outline' | 'destructive'>

export function SuggestionBadge({ action }: { action: SuggestedAction }) {
  const text = suggestedActionTexts[action]
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={(event) => event.stopPropagation()}
          className="justify-self-start rounded-md outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
        >
          <Badge variant={VARIANTS[action]}>{text.label}</Badge>
        </button>
      </TooltipTrigger>
      <TooltipContent>{text.description}</TooltipContent>
    </Tooltip>
  )
}
