import { MoonIcon, SunIcon } from 'lucide-react'
import { setTheme, useTheme } from '@/lib/theme.ts'
import { Button } from './button.tsx'

export function ThemeToggle() {
  const theme = useTheme()
  const next = theme === 'dark' ? 'light' : 'dark'
  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={() => setTheme(next)}
      aria-label={next === 'dark' ? 'Включить тёмную тему' : 'Включить светлую тему'}
    >
      {theme === 'dark' ? <SunIcon aria-hidden /> : <MoonIcon aria-hidden />}
    </Button>
  )
}
