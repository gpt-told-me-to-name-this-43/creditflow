import type * as React from 'react'
import { Toaster as Sonner, type ToasterProps } from 'sonner'
import { useTheme } from '@/lib/theme.ts'

// Цвета тостов — из токенов темы, тема — из lib/theme.
function Toaster(props: ToasterProps) {
  const theme = useTheme()
  return (
    <Sonner
      theme={theme}
      position="top-right"
      style={
        {
          '--normal-bg': 'var(--popover)',
          '--normal-text': 'var(--popover-foreground)',
          '--normal-border': 'var(--border)',
        } as React.CSSProperties
      }
      {...props}
    />
  )
}

export { Toaster }
