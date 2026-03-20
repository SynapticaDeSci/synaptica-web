'use client'

import type { ResearchRunNodeResponse } from '@/lib/api'
import { cn } from '@/lib/utils'

const STATUS_COLORS: Record<string, string> = {
  completed: 'bg-emerald-400 border-emerald-400/60',
  running: 'bg-sky-400 border-sky-400/60 animate-pulse',
  waiting_for_review: 'bg-amber-400 border-amber-400/60',
  failed: 'bg-red-400 border-red-400/60',
  cancelled: 'bg-rose-400 border-rose-400/60',
  blocked: 'bg-orange-400 border-orange-400/60',
  pending: 'bg-slate-600 border-slate-500/60',
}

export function ProgressStepper({
  nodes,
  activeNodeId,
  onNodeClick,
}: {
  nodes: ResearchRunNodeResponse[]
  activeNodeId: string | null
  onNodeClick: (nodeId: string) => void
}) {
  if (nodes.length === 0) return null

  const activeNode = nodes.find((n) => ['running', 'waiting_for_review'].includes(n.status))
  const completedCount = nodes.filter((n) => n.status === 'completed').length

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5">
        {nodes.map((node, index) => (
          <div key={node.node_id} className="flex items-center">
            <button
              type="button"
              onClick={() => onNodeClick(node.node_id)}
              title={node.title}
              className={cn(
                'h-3 w-3 rounded-full border-2 transition hover:scale-125',
                STATUS_COLORS[node.status] ?? STATUS_COLORS.pending,
                node.node_id === activeNodeId && 'ring-2 ring-white/30 ring-offset-1 ring-offset-slate-900',
              )}
            />
            {index < nodes.length - 1 && (
              <div
                className={cn(
                  'mx-0.5 h-0.5 w-4',
                  node.status === 'completed' ? 'bg-emerald-400/40' : 'bg-slate-700',
                )}
              />
            )}
          </div>
        ))}
      </div>

      <p className="text-xs text-slate-400">
        Step {completedCount} of {nodes.length}
        {activeNode && (
          <span className="text-slate-300">
            {' '}&middot; {activeNode.title}
          </span>
        )}
      </p>
    </div>
  )
}
