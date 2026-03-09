import type { ComponentType } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Loader2,
  PauseCircle,
  ShieldAlert,
} from 'lucide-react'

import type { ResearchRunNodeStatus, ResearchRunStatus } from '@/lib/api'
import { cn } from '@/lib/utils'

type ResearchRunLifecycleStatus = ResearchRunStatus | ResearchRunNodeStatus

const STATUS_META: Record<
  ResearchRunLifecycleStatus,
  {
    label: string
    className: string
    icon: ComponentType<{ className?: string }>
  }
> = {
  pending: {
    label: 'Pending',
    className: 'border-slate-700 bg-slate-900/80 text-slate-200',
    icon: Clock3,
  },
  running: {
    label: 'Running',
    className: 'border-sky-500/40 bg-sky-500/10 text-sky-200',
    icon: Loader2,
  },
  waiting_for_review: {
    label: 'Waiting For Review',
    className: 'border-amber-500/40 bg-amber-500/10 text-amber-200',
    icon: PauseCircle,
  },
  completed: {
    label: 'Completed',
    className: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
    icon: CheckCircle2,
  },
  failed: {
    label: 'Failed',
    className: 'border-red-500/40 bg-red-500/10 text-red-200',
    icon: ShieldAlert,
  },
  blocked: {
    label: 'Blocked',
    className: 'border-orange-500/40 bg-orange-500/10 text-orange-200',
    icon: AlertTriangle,
  },
}

export function getResearchRunStatusLabel(status: ResearchRunLifecycleStatus) {
  return STATUS_META[status]?.label || status
}

export function ResearchRunStatusBadge({
  status,
  className,
}: {
  status: ResearchRunLifecycleStatus
  className?: string
}) {
  const meta = STATUS_META[status] || STATUS_META.pending
  const Icon = meta.icon

  return (
    <span
      className={cn(
        'inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.25em]',
        meta.className,
        className,
      )}
    >
      <Icon className={cn('h-3.5 w-3.5', status === 'running' && 'animate-spin')} />
      {meta.label}
    </span>
  )
}
