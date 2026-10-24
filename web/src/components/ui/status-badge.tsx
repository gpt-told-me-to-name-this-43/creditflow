import type { ApplicationStatus } from '@/api/enums.ts'
import { statusTexts } from '@/content/statuses.ts'
import { Badge, type badgeVariants } from './badge.tsx'
import type { VariantProps } from 'class-variance-authority'

type Variant = NonNullable<VariantProps<typeof badgeVariants>['variant']>

// Бренд-красный — там, где ждём действия клиента; зелёный — деньги в пути или на счёте.
const VARIANTS: Record<ApplicationStatus, Variant> = {
  DRAFT: 'outline',
  UNDER_REVIEW: 'secondary',
  NEED_INFO: 'default',
  COUNTER_OFFER: 'default',
  APPROVED: 'default',
  SIGNED: 'success',
  ISSUED: 'success',
  REJECTED: 'outline',
  DECLINED: 'outline',
}

export function StatusBadge({ status }: { status: ApplicationStatus }) {
  return <Badge variant={VARIANTS[status]}>{statusTexts[status].label}</Badge>
}
