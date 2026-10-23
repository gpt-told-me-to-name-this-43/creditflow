import type * as React from 'react'
import { cn } from '@/lib/utils.ts'

const CODE_LENGTH = 6

type CodeInputProps = Omit<React.ComponentProps<'input'>, 'value' | 'onChange' | 'type'> & {
  value: string
  onChange: (code: string) => void
}

/**
 * Код подтверждения: одно поле на 6 цифр — вставка из SMS и автозаполнение
 * (`one-time-code`) работают как есть, лишние символы отбрасываются.
 */
export function CodeInput({ value, onChange, className, ...props }: CodeInputProps) {
  return (
    <input
      {...props}
      type="text"
      inputMode="numeric"
      autoComplete="one-time-code"
      maxLength={CODE_LENGTH}
      value={value}
      onChange={(event) => onChange(normalizeCode(event.target.value))}
      onPaste={(event) => {
        event.preventDefault()
        onChange(normalizeCode(event.clipboardData.getData('text')))
      }}
      className={cn(
        'h-14 w-56 rounded-md border border-input bg-background px-4 text-center font-mono text-3xl tracking-[0.5em] outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive',
        className,
      )}
    />
  )
}

/** Только цифры и не больше шести: «12 34-56» → «123456». */
function normalizeCode(input: string): string {
  return input.replace(/\D/g, '').slice(0, CODE_LENGTH)
}
