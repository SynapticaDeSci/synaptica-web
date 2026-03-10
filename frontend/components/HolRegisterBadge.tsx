'use client'

import { Badge } from '@/components/ui/badge'

interface HolRegisterBadgeProps {
  holUaid?: string | null
  holStatus?: string | null
}

export function HolRegisterBadge({ holUaid, holStatus }: HolRegisterBadgeProps) {
  if (!holUaid && !holStatus) return null

  const status = (holStatus || '').toLowerCase()
  const label =
    status === 'ok' || status === 'registered'
      ? 'HOL: Registered'
      : status === 'pending'
        ? 'HOL: Pending'
        : null

  if (!label) return null

  return (
    <Badge variant="outline" className="border-sky-400/60 bg-sky-500/10 text-[10px] text-sky-100">
      {label}
    </Badge>
  )
}
