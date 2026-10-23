import { createFileRoute } from '@tanstack/react-router'
import { z } from 'zod'

// Шаг мастера и id черновика переживают перезагрузку в адресе. Сам мастер — фаза 5.
const searchSchema = z.object({
  step: z.number().int().min(1).max(4).optional().catch(undefined),
  applicationId: z.uuid().optional().catch(undefined),
})

export const Route = createFileRoute('/_auth/client/applications/new')({
  validateSearch: searchSchema,
  component: NewApplication,
})

function NewApplication() {
  return <h1 className="text-3xl font-bold">Новая заявка</h1>
}
