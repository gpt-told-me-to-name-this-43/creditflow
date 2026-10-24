import type * as React from 'react'
import { groupRubles, normalizeRubles } from '@/lib/money.ts'
import { cn } from '@/lib/utils.ts'
import { Input } from './input.tsx'

type MoneyInputProps = Omit<React.ComponentProps<'input'>, 'value' | 'onChange' | 'type'> & {
  /** Целые рубли строкой цифр: «3000000». */
  value: string
  onChange: (digits: string) => void
}

/** Сумма в целых рублях: на экране «3 000 000 ₽», в форме — строка цифр. */
export function MoneyInput({ value, onChange, className, ...props }: MoneyInputProps) {
  return (
    <div className={cn('relative', className)}>
      <Input
        {...props}
        inputMode="numeric"
        autoComplete="off"
        className="pr-10 text-lg"
        value={groupRubles(value)}
        onChange={(event) => onChange(normalizeRubles(event.target.value))}
      />
      <span
        aria-hidden
        className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-muted-foreground"
      >
        ₽
      </span>
    </div>
  )
}
