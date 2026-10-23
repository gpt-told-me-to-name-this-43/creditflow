import { z } from 'zod'
import { ROLES } from '@/api/enums.ts'

// Сессия живёт в sessionStorage: у каждой вкладки своя, поэтому на демо можно открыть
// клиента и менеджера рядом. Роль — из GET /auth/me после входа.
const sessionSchema = z.object({
  token: z.string().min(1),
  role: z.enum(ROLES),
})

export type Session = z.infer<typeof sessionSchema>
export type Role = Session['role']

const STORAGE_KEY = 'creditflow.session'

export const auth = {
  getSession(): Session | null {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY)
      if (!raw) return null
      const parsed = sessionSchema.safeParse(JSON.parse(raw))
      return parsed.success ? parsed.data : null
    } catch {
      return null
    }
  },

  setSession(session: Session) {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session))
  },

  clear() {
    sessionStorage.removeItem(STORAGE_KEY)
  },
}

export type Auth = typeof auth

interface SessionDeps {
  router: { invalidate: () => Promise<unknown> }
  queryClient: { clear: () => void }
}

// Кэш чистим целиком: данные прошлой учётки не должны мелькнуть у следующей.
// router.invalidate() перезапускает beforeLoad: гарды сами уведут на нужную страницу.
export async function signIn(session: Session, { router, queryClient }: SessionDeps) {
  auth.setSession(session)
  queryClient.clear()
  await router.invalidate()
}

export async function signOut({ router, queryClient }: SessionDeps) {
  auth.clear()
  queryClient.clear()
  await router.invalidate()
}

/** Стартовая страница кабинета для роли. */
export function homeFor(role: Role) {
  return role === 'CLIENT' ? ('/client' as const) : ('/manager' as const)
}
