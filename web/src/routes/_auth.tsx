import { createFileRoute, redirect } from '@tanstack/react-router'

// Всё под _auth — только с сессией. Сессия попадает в context дочерних роутов.
export const Route = createFileRoute('/_auth')({
  beforeLoad: ({ context, location }) => {
    const session = context.auth.getSession()
    if (!session) throw redirect({ to: '/login', search: { redirect: location.href } })
    return { session }
  },
})
