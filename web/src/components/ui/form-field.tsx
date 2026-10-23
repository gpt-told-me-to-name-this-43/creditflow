import type * as React from 'react'
import { cn } from '@/lib/utils.ts'
import { Label } from './label.tsx'

/** Текст первой ошибки поля TanStack Form: строка или issue из zod (Standard Schema). */
export function firstError(errors: readonly unknown[]): string | undefined {
  for (const error of errors) {
    if (typeof error === 'string' && error) return error
    if (error && typeof error === 'object' && 'message' in error) return String(error.message)
  }
  return undefined
}

interface FormFieldProps {
  id: string
  label: string
  /** Подсказка под полем, видна всегда. */
  hint?: string
  /** Ошибка показывается после blur — решает вызывающий. */
  error?: string
  className?: string
  /** Поле получает `id`, `aria-describedby` и `aria-invalid` из `field`. */
  children: (field: {
    id: string
    'aria-describedby'?: string
    'aria-invalid'?: boolean
  }) => React.ReactNode
}

export function FormField({ id, label, hint, error, className, children }: FormFieldProps) {
  const hintId = hint ? `${id}-hint` : undefined
  const errorId = error ? `${id}-error` : undefined
  const describedBy = [errorId, hintId].filter(Boolean).join(' ') || undefined
  return (
    <div className={cn('grid gap-2', className)}>
      <Label htmlFor={id}>{label}</Label>
      {children({ id, 'aria-describedby': describedBy, 'aria-invalid': error ? true : undefined })}
      {hint && (
        <p id={hintId} className="text-sm text-muted-foreground">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="text-sm font-medium text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}
