'use client'

import React from 'react'
import { useTaskStore } from '@/store/taskStore'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ExternalLink } from 'lucide-react'

export function HolAgentsPanel() {
  const { progressLogs } = useTaskStore()

  const holSessions = React.useMemo(() => {
    if (!progressLogs || progressLogs.length === 0) return []

    return progressLogs
      .filter((log) => log.step.startsWith('hol_') && log.data?.hol_session)
      .map((log) => log.data!.hol_session)
  }, [progressLogs])

  if (!holSessions.length) {
    return null
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-2">
          <span>External Agents (HOL)</span>
          <Badge variant="outline" className="text-xs font-normal">
            {holSessions.length} session{holSessions.length > 1 ? 's' : ''}
          </Badge>
        </CardTitle>
        <CardDescription>
          External agents hired via the Hashgraph Online (HOL) Universal Agentic Registry for this task.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {holSessions.map((session: any, index: number) => (
          <div
            key={`${session.session_id || index}-${index}`}
            className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-800"
          >
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-semibold">
                    {session.agent_name || session.uaid || 'HOL Agent'}
                  </span>
                  {session.registry && (
                    <Badge variant="outline" className="border-sky-200 bg-sky-50 text-[10px] text-sky-700">
                      {session.registry}
                    </Badge>
                  )}
                </div>
                {session.uaid && (
                  <div className="mt-0.5 text-[11px] text-slate-500">
                    UAID: <span className="font-mono">{session.uaid}</span>
                  </div>
                )}
                {session.instructions && (
                  <p className="mt-1 line-clamp-3 text-[11px] text-slate-700">
                    {session.instructions}
                  </p>
                )}
              </div>
              {session.public_url && (
                <a
                  href={session.public_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-700 hover:border-sky-300 hover:text-sky-700"
                >
                  <ExternalLink className="h-3 w-3" />
                  View chat
                </a>
              )}
            </div>
            {session.session_id && (
              <div className="mt-1 text-[11px] text-slate-500">
                Session: <span className="font-mono">{session.session_id}</span>
              </div>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

