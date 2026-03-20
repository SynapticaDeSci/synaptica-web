'use client'

import { Loader2, Pause, Play, Slash } from 'lucide-react'

import { Button } from '@/components/ui/button'
import type { ResearchRunResponse } from '@/lib/api'

import { ResearchRunStatusBadge } from '../ResearchRunStatusBadge'
import { formatBudget, formatCreditBudget, formatDateTime, TERMINAL_RUN_STATUSES } from './shared'

export function RunHeader({
  researchRun,
  controlAction,
  controlError,
  onRunControl,
}: {
  researchRun: ResearchRunResponse
  controlAction: 'pause' | 'resume' | 'cancel' | null
  controlError: string | null
  onRunControl: (action: 'pause' | 'resume' | 'cancel') => void
}) {
  const canPause = researchRun.status === 'running'
  const canResume = researchRun.status === 'paused'
  const canCancel = !TERMINAL_RUN_STATUSES.has(researchRun.status)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 space-y-1">
          <h1 className="text-2xl font-semibold text-white">{researchRun.title}</h1>
          {researchRun.description && (
            <p className="max-w-2xl text-sm text-slate-300">{researchRun.description}</p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {canPause && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={controlAction !== null}
              onClick={() => onRunControl('pause')}
              className="border-white/15 bg-white/5 text-white hover:bg-white/10 hover:text-white"
            >
              {controlAction === 'pause' ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Pause className="mr-1.5 h-3.5 w-3.5" />
              )}
              Pause
            </Button>
          )}
          {canResume && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={controlAction !== null}
              onClick={() => onRunControl('resume')}
              className="border-emerald-400/20 bg-emerald-400/10 text-emerald-100 hover:bg-emerald-400/20 hover:text-emerald-50"
            >
              {controlAction === 'resume' ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Play className="mr-1.5 h-3.5 w-3.5" />
              )}
              Resume
            </Button>
          )}
          {canCancel && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={controlAction !== null}
              onClick={() => onRunControl('cancel')}
              className="border-rose-500/30 bg-rose-500/10 text-rose-100 hover:bg-rose-500/20 hover:text-rose-50"
            >
              {controlAction === 'cancel' ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Slash className="mr-1.5 h-3.5 w-3.5" />
              )}
              Cancel
            </Button>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <ResearchRunStatusBadge status={researchRun.status} />
        <span className="inline-flex items-center gap-1 rounded-full border border-amber-400/20 bg-amber-400/10 px-3 py-1 text-xs text-amber-200">
          ⚡ {formatCreditBudget(researchRun.credit_budget, researchRun.budget_limit)}
        </span>
        <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-300">
          {formatDateTime(researchRun.created_at)}
        </span>
      </div>

      {controlError && (
        <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-100">
          {controlError}
        </div>
      )}
    </div>
  )
}
