import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

// Склейка классов Tailwind без конфликтов (соглашение shadcn/ui).
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
