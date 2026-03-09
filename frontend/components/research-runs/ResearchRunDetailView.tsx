'use client'

import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  Clock3,
  Coins,
  DatabaseZap,
  Loader2,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { VerificationReviewCard } from '@/components/VerificationReviewCard'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  approveVerification,
  getResearchRun,
  getTask,
  rejectVerification,
  type ResearchRunNodeResponse,
  type ResearchRunNodeStatus,
  type ResearchRunResponse,
} from '@/lib/api'
import { cn } from '@/lib/utils'

import { ResearchRunStatusBadge } from './ResearchRunStatusBadge'

const TERMINAL_RUN_STATUSES = new Set(['completed', 'failed'])

function formatDateTime(value?: string | null) {
  if (!value) return 'Not yet'

  try {
    return new Intl.DateTimeFormat('en-SG', {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(value))
  } catch {
    return value
  }
}

function formatBudget(value?: number | null) {
  if (typeof value !== 'number') {
    return 'Unspecified'
  }

  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
  }).format(value)
}

function stringifyValue(value: unknown) {
  if (value == null) return null
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}

function getRunHeadline(run: ResearchRunResponse): string | null {
  const report = run.result && typeof run.result === 'object' ? run.result.report : null
  if (report && typeof report === 'object' && typeof report.summary === 'string') {
    return report.summary
  }
  if (run.error) {
    return run.error
  }
  return null
}

function getRunFindings(run: ResearchRunResponse): string[] {
  const report = run.result && typeof run.result === 'object' ? run.result.report : null
  if (report && typeof report === 'object' && Array.isArray(report.key_findings)) {
    return report.key_findings.filter((item: unknown): item is string => typeof item === 'string')
  }
  return []
}

function pickFocusNode(nodes: ResearchRunNodeResponse[]) {
  const priority: ResearchRunNodeStatus[] = [
    'waiting_for_review',
    'running',
    'failed',
    'blocked',
    'pending',
    'completed',
  ]

  for (const status of priority) {
    const match = nodes.find((node) => node.status === status)
    if (match) {
      return match
    }
  }

  return nodes[0] ?? null
}

function JsonPreview({
  title,
  value,
  tone = 'dark',
}: {
  title: string
  value: unknown
  tone?: 'dark' | 'light'
}) {
  const content = stringifyValue(value)

  if (!content) {
    return null
  }

  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-400">{title}</p>
      <pre
        className={cn(
          'max-h-72 overflow-auto rounded-2xl border p-4 text-xs leading-relaxed',
          tone === 'dark'
            ? 'border-white/10 bg-slate-950/90 text-slate-200'
            : 'border-slate-200 bg-slate-50 text-slate-700',
        )}
      >
        {content}
      </pre>
    </div>
  )
}

export function ResearchRunDetailView({ researchRunId }: { researchRunId: string }) {
  const queryClient = useQueryClient()
  const [activeNodeId, setActiveNodeId] = useState<string | null>(null)

  const researchRunQuery = useQuery({
    queryKey: ['research-run', researchRunId],
    queryFn: () => getResearchRun(researchRunId),
    retry: false,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && TERMINAL_RUN_STATUSES.has(status) ? false : 2000
    },
    refetchIntervalInBackground: true,
  })

  const orderedNodes = useMemo(
    () =>
      [...(researchRunQuery.data?.nodes ?? [])].sort(
        (left, right) => left.execution_order - right.execution_order,
      ),
    [researchRunQuery.data?.nodes],
  )

  useEffect(() => {
    if (orderedNodes.length === 0) {
      return
    }

    const focusedNode = pickFocusNode(orderedNodes)
    const activeNodeStillExists = orderedNodes.some((node) => node.node_id === activeNodeId)

    if (!activeNodeStillExists) {
      setActiveNodeId(focusedNode?.node_id ?? orderedNodes[0].node_id)
      return
    }

    const activeNode = orderedNodes.find((node) => node.node_id === activeNodeId)
    if (
      activeNode &&
      ['completed', 'pending', 'blocked'].includes(activeNode.status) &&
      focusedNode &&
      ['waiting_for_review', 'running', 'failed'].includes(focusedNode.status)
    ) {
      setActiveNodeId(focusedNode.node_id)
    }
  }, [activeNodeId, orderedNodes])

  const selectedNode =
    orderedNodes.find((node) => node.node_id === activeNodeId) ?? orderedNodes[0] ?? null
  const waitingNode =
    orderedNodes.find(
      (node) => node.status === 'waiting_for_review' && typeof node.task_id === 'string',
    ) ?? null
  const waitingTaskId = waitingNode?.task_id ?? null

  const waitingTaskQuery = useQuery({
    queryKey: ['task', waitingTaskId],
    queryFn: () => getTask(waitingTaskId as string),
    enabled: Boolean(waitingTaskId),
    retry: false,
    refetchInterval: researchRunQuery.data?.status === 'waiting_for_review' ? 2000 : false,
  })

  const handleApproveReview = async (taskId: string) => {
    await approveVerification(taskId)
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['research-run', researchRunId] }),
      queryClient.invalidateQueries({ queryKey: ['task', taskId] }),
    ])
  }

  const handleRejectReview = async (taskId: string, reason?: string) => {
    await rejectVerification(taskId, reason)
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['research-run', researchRunId] }),
      queryClient.invalidateQueries({ queryKey: ['task', taskId] }),
    ])
  }

  if (researchRunQuery.isLoading) {
    return (
      <Card className="rounded-[28px] border border-white/15 bg-slate-900/75 text-slate-100 backdrop-blur-xl">
        <CardContent className="flex items-center justify-center gap-3 py-16">
          <Loader2 className="h-5 w-5 animate-spin text-sky-300" />
          <span>Loading research run…</span>
        </CardContent>
      </Card>
    )
  }

  if (researchRunQuery.isError || !researchRunQuery.data) {
    const message =
      researchRunQuery.error instanceof Error
        ? researchRunQuery.error.message
        : 'Unable to load research run.'
    const notFound = /not found/i.test(message)

    return (
      <Card className="rounded-[28px] border border-white/15 bg-slate-900/75 text-slate-100 backdrop-blur-xl">
        <CardHeader>
          <CardTitle className="text-3xl text-white">
            {notFound ? 'Research run not found' : 'Unable to load research run'}
          </CardTitle>
          <CardDescription className="text-slate-300">
            {notFound
              ? 'The requested run ID does not exist in this environment.'
              : message}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            onClick={() => researchRunQuery.refetch()}
            variant="outline"
            className="border-white/15 bg-white/5 text-white hover:bg-white/10 hover:text-white"
          >
            <RefreshCw className="mr-2 h-4 w-4" />
            Retry
          </Button>
        </CardContent>
      </Card>
    )
  }

  const researchRun = researchRunQuery.data
  const headline = getRunHeadline(researchRun)
  const findings = getRunFindings(researchRun)
  const selectedNodeAttempts = [...(selectedNode?.attempts ?? [])].sort(
    (left, right) => right.attempt_number - left.attempt_number,
  )

  return (
    <div className="space-y-6">
      {waitingNode && (
        <section className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.3em] text-amber-300">
                Human Review Required
              </p>
              <h2 className="mt-2 text-2xl font-semibold text-white">{waitingNode.title}</h2>
              <p className="mt-1 text-sm text-slate-300">
                Review is routed through the linked task endpoint while the research run stays paused.
              </p>
            </div>
            <ResearchRunStatusBadge status={waitingNode.status} />
          </div>

          {waitingTaskQuery.isLoading && (
            <Card className="rounded-[28px] border border-white/15 bg-slate-900/75 text-slate-100">
              <CardContent className="flex items-center gap-3 py-8">
                <Loader2 className="h-4 w-4 animate-spin text-sky-300" />
                Loading verification packet…
              </CardContent>
            </Card>
          )}

          {waitingTaskQuery.data?.verification_data && waitingTaskId && (
            <VerificationReviewCard
              taskId={waitingTaskId}
              verificationData={waitingTaskQuery.data.verification_data}
              onApprove={handleApproveReview}
              onReject={handleRejectReview}
              approveLabel="Approve node"
              rejectLabel="Reject node"
            />
          )}

          {waitingTaskQuery.isError && (
            <Card className="rounded-[28px] border border-red-500/30 bg-red-500/10 text-red-100">
              <CardContent className="py-6">
                Unable to load verification details for task {waitingTaskId}.
              </CardContent>
            </Card>
          )}
        </section>
      )}

      <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <div className="space-y-6">
          <Card className="rounded-[28px] border border-white/15 bg-slate-900/75 text-slate-100 shadow-[0_40px_100px_-60px_rgba(56,189,248,0.8)] backdrop-blur-xl">
            <CardHeader className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="space-y-2">
                  <span className="inline-flex w-fit items-center rounded-full border border-sky-400/20 bg-sky-400/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.35em] text-sky-200">
                    Research run summary
                  </span>
                  <CardTitle className="text-3xl text-white">{researchRun.title}</CardTitle>
                  <CardDescription className="max-w-2xl text-slate-300">
                    {researchRun.description}
                  </CardDescription>
                </div>
                <ResearchRunStatusBadge status={researchRun.status} />
              </div>
            </CardHeader>

            <CardContent className="space-y-6">
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Budget</p>
                  <p className="mt-2 text-lg font-semibold text-white">{formatBudget(researchRun.budget_limit)}</p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Verification</p>
                  <p className="mt-2 text-lg font-semibold capitalize text-white">
                    {researchRun.verification_mode}
                  </p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Created</p>
                  <p className="mt-2 text-sm font-medium text-white">{formatDateTime(researchRun.created_at)}</p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Updated</p>
                  <p className="mt-2 text-sm font-medium text-white">{formatDateTime(researchRun.updated_at)}</p>
                </div>
              </div>

              <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Workflow</p>
                <p className="mt-2 font-mono text-sm text-sky-100">{researchRun.workflow}</p>
                <p className="mt-3 text-xs text-slate-400">Run ID: {researchRun.id}</p>
              </div>

              {(headline || findings.length > 0) && (
                <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/10 p-5">
                  <div className="flex items-center gap-2 text-emerald-200">
                    <ShieldCheck className="h-4 w-4" />
                    <p className="text-sm font-semibold uppercase tracking-[0.3em]">Final result</p>
                  </div>
                  {headline && <p className="mt-3 text-base leading-relaxed text-white">{headline}</p>}
                  {findings.length > 0 && (
                    <ul className="mt-4 space-y-2 text-sm text-emerald-50">
                      {findings.map((finding: string) => (
                        <li key={finding} className="rounded-xl border border-white/10 bg-white/5 px-3 py-2">
                          {finding}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="rounded-[28px] border border-white/15 bg-slate-900/75 text-slate-100 backdrop-blur-xl">
            <CardHeader className="space-y-3">
              <CardTitle className="text-2xl text-white">Pipeline rail</CardTitle>
              <CardDescription className="text-slate-300">
                Each node maps to one persisted task attempt and reuses the Phase 0 verification and payment flow.
              </CardDescription>
            </CardHeader>

            <CardContent>
              <ol className="space-y-3">
                {orderedNodes.map((node, index) => {
                  const isSelected = node.node_id === selectedNode?.node_id
                  return (
                    <li key={node.node_id} className="relative">
                      <button
                        type="button"
                        onClick={() => setActiveNodeId(node.node_id)}
                        className={cn(
                          'w-full rounded-3xl border p-5 text-left transition',
                          isSelected
                            ? 'border-sky-400/60 bg-sky-500/10 shadow-[0_24px_60px_-36px_rgba(56,189,248,0.95)]'
                            : 'border-white/10 bg-white/5 hover:bg-white/10',
                        )}
                      >
                        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
                          <div className="flex items-start gap-4">
                            <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-white/10 bg-white/10 text-sm font-semibold text-white">
                              {index + 1}
                            </div>
                            <div className="space-y-2">
                              <div className="flex flex-wrap items-center gap-2">
                                <p className="text-lg font-semibold text-white">{node.title}</p>
                                {node.task_id && (
                                  <span className="rounded-full border border-white/10 bg-white/5 px-2 py-1 text-[11px] uppercase tracking-[0.2em] text-slate-300">
                                    Task linked
                                  </span>
                                )}
                              </div>
                              <p className="text-sm leading-relaxed text-slate-300">{node.description}</p>
                              <div className="flex flex-wrap gap-2 text-xs text-slate-400">
                                <span className="rounded-full border border-white/10 bg-white/5 px-2 py-1">
                                  Capability: {node.capability_requirements}
                                </span>
                                <span className="rounded-full border border-white/10 bg-white/5 px-2 py-1">
                                  Attempts: {node.attempts.length}
                                </span>
                              </div>
                            </div>
                          </div>
                          <ResearchRunStatusBadge status={node.status} className="shrink-0" />
                        </div>
                      </button>

                      {index < orderedNodes.length - 1 && (
                        <div className="ml-5 mt-2 h-6 border-l border-dashed border-white/15" />
                      )}
                    </li>
                  )
                })}
              </ol>
            </CardContent>
          </Card>
        </div>

        <Card className="rounded-[28px] border border-white/15 bg-slate-900/75 text-slate-100 backdrop-blur-xl">
          <CardHeader className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <CardTitle className="text-2xl text-white">
                  {selectedNode ? selectedNode.title : 'Node details'}
                </CardTitle>
                <CardDescription className="text-slate-300">
                  Inspect the current node, its linked task/payment IDs, and every persisted attempt.
                </CardDescription>
              </div>
              {selectedNode && <ResearchRunStatusBadge status={selectedNode.status} />}
            </div>
          </CardHeader>

          <CardContent className="space-y-6">
            {!selectedNode && (
              <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-5 text-sm text-slate-300">
                Select a node from the pipeline rail to inspect its state.
              </div>
            )}

            {selectedNode && (
              <>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                    <div className="flex items-center gap-2 text-xs uppercase tracking-[0.25em] text-slate-400">
                      <DatabaseZap className="h-3.5 w-3.5" />
                      Assigned agent
                    </div>
                    <p className="mt-2 text-sm font-medium text-white">{selectedNode.assigned_agent_id}</p>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                    <div className="flex items-center gap-2 text-xs uppercase tracking-[0.25em] text-slate-400">
                      <Coins className="h-3.5 w-3.5" />
                      Payment ID
                    </div>
                    <p className="mt-2 break-all text-sm font-medium text-white">
                      {selectedNode.payment_id || 'Not created yet'}
                    </p>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                    <div className="flex items-center gap-2 text-xs uppercase tracking-[0.25em] text-slate-400">
                      <Clock3 className="h-3.5 w-3.5" />
                      Started
                    </div>
                    <p className="mt-2 text-sm font-medium text-white">{formatDateTime(selectedNode.started_at)}</p>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                    <div className="flex items-center gap-2 text-xs uppercase tracking-[0.25em] text-slate-400">
                      <AlertTriangle className="h-3.5 w-3.5" />
                      Task ID
                    </div>
                    <p className="mt-2 break-all text-sm font-medium text-white">
                      {selectedNode.task_id || 'Not created yet'}
                    </p>
                  </div>
                </div>

                <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <p className="text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">
                    Description
                  </p>
                  <p className="mt-3 text-sm leading-relaxed text-slate-200">
                    {selectedNode.description}
                  </p>
                </div>

                {selectedNode.error && (
                  <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-100">
                    {selectedNode.error}
                  </div>
                )}

                <JsonPreview title="Node result" value={selectedNode.result} />

                <div className="space-y-3">
                  <p className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-400">
                    Execution attempts
                  </p>
                  {selectedNodeAttempts.length === 0 && (
                    <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-5 text-sm text-slate-300">
                      No attempts have been recorded yet.
                    </div>
                  )}

                  {selectedNodeAttempts.map((attempt) => (
                    <div
                      key={attempt.attempt_id}
                      className="rounded-3xl border border-white/10 bg-white/5 p-4"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <p className="text-sm font-semibold text-white">
                            Attempt {attempt.attempt_number}
                          </p>
                          <p className="mt-1 text-xs text-slate-400">
                            {formatDateTime(attempt.created_at)}
                          </p>
                        </div>
                        <ResearchRunStatusBadge status={attempt.status} />
                      </div>

                      <div className="mt-4 grid gap-3 sm:grid-cols-2">
                        <div className="rounded-2xl border border-white/10 bg-slate-950/60 p-3">
                          <p className="text-[11px] uppercase tracking-[0.25em] text-slate-400">Task</p>
                          <p className="mt-2 break-all text-sm text-slate-200">
                            {attempt.task_id || 'Not created'}
                          </p>
                        </div>
                        <div className="rounded-2xl border border-white/10 bg-slate-950/60 p-3">
                          <p className="text-[11px] uppercase tracking-[0.25em] text-slate-400">Payment</p>
                          <p className="mt-2 break-all text-sm text-slate-200">
                            {attempt.payment_id || 'Not created'}
                          </p>
                        </div>
                        <div className="rounded-2xl border border-white/10 bg-slate-950/60 p-3">
                          <p className="text-[11px] uppercase tracking-[0.25em] text-slate-400">Agent</p>
                          <p className="mt-2 break-all text-sm text-slate-200">
                            {attempt.agent_id || 'Pending selection'}
                          </p>
                        </div>
                        <div className="rounded-2xl border border-white/10 bg-slate-950/60 p-3">
                          <p className="text-[11px] uppercase tracking-[0.25em] text-slate-400">Verification score</p>
                          <p className="mt-2 text-sm text-slate-200">
                            {typeof attempt.verification_score === 'number'
                              ? `${attempt.verification_score}/100`
                              : 'Not available'}
                          </p>
                        </div>
                      </div>

                      {attempt.error && (
                        <div className="mt-4 rounded-2xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-100">
                          {attempt.error}
                        </div>
                      )}

                      <div className="mt-4">
                        <JsonPreview title="Attempt result" value={attempt.result} />
                      </div>
                    </div>
                  ))}
                </div>

                {researchRun.result && (
                  <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                    <p className="mb-3 text-xs font-semibold uppercase tracking-[0.3em] text-slate-400">
                      Run payload
                    </p>
                    <JsonPreview title="Research run result" value={researchRun.result} />
                  </div>
                )}
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
