import { PURPOSE_CODES, type PurposeCode } from '@/api/enums.ts'
import { purposeTexts } from '@/content/purposes.ts'
import { cn } from '@/lib/utils.ts'

interface PurposePickerProps {
  name: string
  value: PurposeCode | null
  onChange: (value: PurposeCode) => void
  onBlur?: () => void
  /** id подписи группы. */
  labelledBy: string
  describedBy?: string
  invalid?: boolean
}

/** Шесть карточек целей — радиогруппа: стрелки и пробел работают как у обычных радиокнопок. */
export function PurposePicker({
  name,
  value,
  onChange,
  onBlur,
  labelledBy,
  describedBy,
  invalid,
}: PurposePickerProps) {
  return (
    <div
      role="radiogroup"
      aria-labelledby={labelledBy}
      aria-describedby={describedBy}
      aria-invalid={invalid || undefined}
      className="grid grid-cols-3 gap-3"
    >
      {PURPOSE_CODES.map((code) => {
        const text = purposeTexts[code]
        const checked = value === code
        return (
          <label
            key={code}
            className={cn(
              'flex cursor-pointer flex-col gap-1 rounded-xl border p-4 transition-colors hover:bg-accent has-[:focus-visible]:ring-[3px] has-[:focus-visible]:ring-ring/50',
              checked && 'border-foreground bg-accent ring-1 ring-foreground',
            )}
          >
            <input
              type="radio"
              name={name}
              value={code}
              checked={checked}
              onChange={() => onChange(code)}
              onBlur={onBlur}
              className="sr-only"
            />
            <span className="font-semibold">{text.label}</span>
            <span className="text-sm text-muted-foreground">{text.example}</span>
          </label>
        )
      })}
    </div>
  )
}
