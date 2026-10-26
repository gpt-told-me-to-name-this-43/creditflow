import { Tooltip, TooltipContent, TooltipTrigger } from './tooltip.tsx'

/**
 * Термин с подсказкой из `content/glossary.ts`. Триггер — кнопка: подсказка открывается
 * и с клавиатуры (фокус), а не только наведением.
 */
export function GlossaryTerm({ label, hint }: { label: string; hint: string }) {
  return (
    <Tooltip>
      <TooltipTrigger
        type="button"
        className="cursor-help rounded-sm text-left underline decoration-dotted underline-offset-4 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
      >
        {label}
      </TooltipTrigger>
      <TooltipContent>{hint}</TooltipContent>
    </Tooltip>
  )
}
