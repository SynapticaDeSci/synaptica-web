'use client'

import { ExternalLink } from 'lucide-react'
import { ResearchRunDetailView } from '@/components/research-runs/detail'
import type { ResearchSourceCard } from '@/lib/api'

interface ResearchProgressInlineProps {
  researchRunId: string
  onNewResearch: () => void
  onComplete?: (ctx: { report: string; citations: ResearchSourceCard[] }) => void
}

export function ResearchProgressInline({
  researchRunId,
  onNewResearch,
  onComplete,
}: ResearchProgressInlineProps) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-400">
          Research in progress
        </span>
        <a
          href={`/research-runs/${researchRunId}`}
          className="flex items-center gap-1 text-xs text-sky-400 transition hover:text-sky-300"
        >
          Full view
          <ExternalLink className="h-3 w-3" />
        </a>
      </div>
      <ResearchRunDetailView
        researchRunId={researchRunId}
        onComplete={onComplete}
        hideFollowUpChat
      />
    </div>
  )
}
