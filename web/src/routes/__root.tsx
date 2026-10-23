import { type QueryClient, useQueryClient } from '@tanstack/react-query'
import { createRootRouteWithContext, Link, Outlet, useRouter } from '@tanstack/react-router'
import { Button } from '@/components/ui/button.tsx'
import { EmptyState } from '@/components/ui/empty-state.tsx'
import { ErrorState } from '@/components/ui/error-state.tsx'
import { Toaster } from '@/components/ui/sonner.tsx'
import { ThemeToggle } from '@/components/ui/theme-toggle.tsx'
import { TooltipProvider } from '@/components/ui/tooltip.tsx'
import { pageErrors } from '@/content/errors.ts'
import { type Auth, auth, signOut } from '@/lib/auth.ts'
import type { ReactNode } from 'react'

interface RouterContext {
  queryClient: QueryClient
  auth: Auth
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: RootLayout,
  errorComponent: RootError,
  notFoundComponent: NotFound,
})

function Shell({ children }: { children: ReactNode }) {
  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex min-h-screen flex-col">
        <header className="border-b">
          <div className="mx-auto flex h-16 w-full max-w-screen-2xl items-center justify-between px-8">
            {/* Логотип — только официальный файл из public/brand/; пока его нет, текстовая заглушка. */}
            <Link to="/" className="text-xl font-bold tracking-tight">
              CreditFlow
            </Link>
            <div className="flex items-center gap-2">
              <SignOutButton />
              <ThemeToggle />
            </div>
          </div>
        </header>
        <main className="mx-auto w-full max-w-screen-2xl flex-1 px-8 py-10">{children}</main>
      </div>
      <Toaster />
    </TooltipProvider>
  )
}

// Сессия читается при каждом рендере: после входа/выхода router.invalidate() перерисует шапку.
function SignOutButton() {
  const router = useRouter()
  const queryClient = useQueryClient()
  if (!auth.getSession()) return null
  return (
    <Button variant="ghost" onClick={() => void signOut({ router, queryClient })}>
      Выйти
    </Button>
  )
}

function RootLayout() {
  return (
    <Shell>
      <Outlet />
    </Shell>
  )
}

function RootError({ reset }: { reset: () => void }) {
  const router = useRouter()
  return (
    <Shell>
      <ErrorState
        onRetry={() => {
          reset()
          void router.invalidate()
        }}
      />
    </Shell>
  )
}

function NotFound() {
  return (
    <EmptyState
      title={pageErrors.notFound.title}
      description={pageErrors.notFound.description}
      action={
        <Button asChild variant="outline">
          <Link to="/">{pageErrors.notFound.action}</Link>
        </Button>
      }
    />
  )
}
