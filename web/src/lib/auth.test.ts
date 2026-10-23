import { describe, expect, it, vi } from 'vitest'
import { auth, homeFor, signIn, signOut } from './auth.ts'

const deps = () => ({
  router: { invalidate: vi.fn(async () => {}) },
  queryClient: { clear: vi.fn() },
})

describe('auth', () => {
  it('хранит сессию в sessionStorage', () => {
    auth.setSession({ token: 'abc', role: 'CLIENT' })
    expect(auth.getSession()).toEqual({ token: 'abc', role: 'CLIENT' })
    auth.clear()
    expect(auth.getSession()).toBeNull()
  })

  it('битая или чужая запись — нет сессии', () => {
    sessionStorage.setItem('creditflow.session', '{oops')
    expect(auth.getSession()).toBeNull()
    sessionStorage.setItem('creditflow.session', JSON.stringify({ token: 'x', role: 'ADMIN' }))
    expect(auth.getSession()).toBeNull()
  })

  it('signIn и signOut чистят кэш и перезапускают гарды', async () => {
    const d = deps()
    await signIn({ token: 'abc', role: 'MANAGER' }, d)
    expect(auth.getSession()?.role).toBe('MANAGER')
    await signOut(d)
    expect(auth.getSession()).toBeNull()
    expect(d.queryClient.clear).toHaveBeenCalledTimes(2)
    expect(d.router.invalidate).toHaveBeenCalledTimes(2)
  })

  it('homeFor ведёт в кабинет роли', () => {
    expect(homeFor('CLIENT')).toBe('/client')
    expect(homeFor('MANAGER')).toBe('/manager')
  })
})
