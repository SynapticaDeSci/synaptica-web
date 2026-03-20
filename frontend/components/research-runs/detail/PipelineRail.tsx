'use client'

import {
  AlertTriangle,
  ChevronDown,
  Clock3,
  Coins,
  DatabaseZap,
  Loader2,
} from 'lucide-react'
import { useQuery } from '@tanstack/react-query'

import {
  getPayment,
  getPaymentEvents,
  type PaymentDetailResponse,
  type PaymentEventsResponse,
  type ResearchCriticFinding,
  type ResearchRunNodeResponse,
  type ResearchRunVerificationDecisionResponse,
  type ResearchRunSwarmHandoffResponse,
  type ResearchRunPolicyEvaluationResponse,
  type ResearchSourceCard,
} from '@/lib/api'
import { cn } from '@/lib/utils'

import { ResearchRunStatusBadge } from '../ResearchRunStatusBadge'
import {
  DebugSection,
  ExpandableText,
  formatDateTime,
  formatMode,
  PaymentActivityPanel,
  SourceCards,
  TERMINAL_RUN_STATUSES,
} from './shared'

export function PipelineRail({
  orderedNodes,
  selectedNode,
  activeNodeId,
  onNodeClick,
  verificationDecisions,
  swarmHandoffs,
  policyEvaluations,
  runStatus,
  defaultOpen,
}: {
  orderedNodes: ResearchRunNodeResponse[]
  selectedNode: ResearchRunNodeResponse | null
  activeNodeId: string | null
  onNodeClick: (nodeId: string) => void
  verificationDecisions: ResearchRunVerificationDecisionResponse[]
  swarmHandoffs: ResearchRunSwarmHandoffResponse[]
  policyEvaluations: ResearchRunPolicyEvaluationResponse[]
  runStatus: string
  defaultOpen: boolean
}) {
  const selectedPaymentId = selectedNode?.payment_id ?? null
  const isTerminal = TERMINAL_RUN_STATUSES.has(runStatus)

  const paymentDetailQuery = useQuery({
    queryKey: ['payment', selectedPaymentId],
    queryFn: () => getPayment(selectedPaymentId as string),
    enabled: Boolean(selectedPaymentId),
    retry: false,
    refetchInterval: isTerminal ? false : 2000,
    refetchIntervalInBackground: true,
  })

  const paymentEventsQuery = useQuery({
    queryKey: ['payment', selectedPaymentId, 'events'],
    queryFn: () => getPaymentEvents(selectedPaymentId as string),
    enabled: Boolean(selectedPaymentId),
    retry: false,
    refetchInterval: isTerminal ? false : 2000,
    refetchIntervalInBackground: true,
  })

  const selectedNodeAttempts = [...(selectedNode?.attempts ?? [])].sort(
    (left, right) => right.attempt_number - left.attempt_number,
  )
  const selectedNodeVerificationDecisions = verificationDecisions.filter(
    (item) => item.node_id === selectedNode?.node_id,
  )
  const selectedNodeSwarmHandoffs = swarmHandoffs.filter(
    (item) => item.node_id === selectedNode?.node_id,
  )
  const selectedNodePolicyEvaluations = policyEvaluations.filter(
    (item) => item.node_id === selectedNode?.node_id,
  )

  return (
    <details
      className="rounded-[28px] border border-white/15 bg-slate-900/75 text-slate-100 backdrop-blur-xl"
      open={defaultOpen}
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-6 py-5">
        <span className="text-sm font-semibold uppercase tracking-[0.25em] text-slate-300">
          Pipeline ({orderedNodes.length} nodes)
        </span>
        <ChevronDown className="h-4 w-4 text-slate-400 transition details-open:rotate-180" />
      </summary>

      <div className="grid gap-6 px-6 pb-6 xl:grid-cols-[1.15fr_0.85fr]">
        {/* Node list */}
        <ol className="space-y-3">
          {orderedNodes.map((node, index) => {
            const isSelected = node.node_id === selectedNode?.node_id
            return (
              <li key={node.node_id} className="relative">
                <button
                  type="button"
                  onClick={() => onNodeClick(node.node_id)}
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

        {/* Node details panel */}
        <div className="space-y-6">
          {!selectedNode && (
            <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-5 text-sm text-slate-300">
              Select a node from the pipeline rail to inspect its state.
            </div>
          )}

          {selectedNode && (
            <>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h3 className="text-xl font-semibold text-white">{selectedNode.title}</h3>
                <ResearchRunStatusBadge status={selectedNode.status} />
              </div>

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
                <p className="text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Description</p>
                <div className="mt-3">
                  <ExpandableText
                    content={selectedNode.description}
                    collapsedHeight="max-h-24"
                    buttonLabel="Read description"
                    className="text-slate-200"
                  />
                </div>
              </div>

              {selectedNode.candidate_agent_ids.length > 0 && (
                <div className="rounded-2xl border border-sky-400/20 bg-sky-400/10 p-4">
                  <p className="text-xs font-semibold uppercase tracking-[0.25em] text-sky-100/80">
                    Candidate agents
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2 text-xs text-sky-50">
                    {selectedNode.candidate_agent_ids.map((agentId) => (
                      <span
                        key={agentId}
                        className={cn(
                          'rounded-full border px-2 py-1',
                          agentId === selectedNode.assigned_agent_id
                            ? 'border-sky-200/40 bg-sky-100/20 text-white'
                            : 'border-sky-300/20 bg-sky-300/10',
                        )}
                      >
                        {agentId}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {selectedNode.error && (
                <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-100">
                  {selectedNode.error}
                </div>
              )}

              {selectedNode.result &&
                typeof selectedNode.result === 'object' &&
                Array.isArray((selectedNode.result as Record<string, any>).critic_findings) &&
                ((selectedNode.result as Record<string, any>).critic_findings as ResearchCriticFinding[]).length > 0 && (
                  <div className="space-y-3">
                    <p className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-400">
                      Critic findings
                    </p>
                    {((selectedNode.result as Record<string, any>).critic_findings as ResearchCriticFinding[]).map(
                      (finding) => (
                        <div
                          key={`${finding.issue}-${finding.recommendation}`}
                          className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-slate-200"
                        >
                          <p className="font-medium text-white">{finding.issue}</p>
                          {finding.recommendation && (
                            <div className="mt-2">
                              <ExpandableText
                                content={finding.recommendation}
                                collapsedHeight="max-h-24"
                                buttonLabel="Expand finding"
                                className="text-slate-300"
                              />
                            </div>
                          )}
                        </div>
                      ),
                    )}
                  </div>
                )}

              {selectedNode.result &&
                typeof selectedNode.result === 'object' &&
                Array.isArray((selectedNode.result as Record<string, any>).sources) && (
                  <SourceCards
                    sources={(selectedNode.result as Record<string, any>).sources as ResearchSourceCard[]}
                  />
                )}

              {selectedPaymentId && (
                <>
                  {paymentDetailQuery.isLoading && (
                    <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-5 text-sm text-slate-300">
                      Loading payment activity...
                    </div>
                  )}
                  {paymentDetailQuery.data && (
                    <PaymentActivityPanel
                      payment={paymentDetailQuery.data}
                      paymentEvents={paymentEventsQuery.data}
                    />
                  )}
                  {(paymentDetailQuery.isError || paymentEventsQuery.isError) && (
                    <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-100">
                      Payment activity could not be loaded for this node.
                    </div>
                  )}
                </>
              )}

              {(selectedNodeVerificationDecisions.length > 0 ||
                selectedNodeSwarmHandoffs.length > 0 ||
                selectedNodePolicyEvaluations.length > 0) && (
                <div className="space-y-3">
                  <p className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-400">
                    Persisted node trace
                  </p>

                  {selectedNodeVerificationDecisions.length > 0 && (
                    <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                      <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Verification decisions</p>
                      <div className="mt-3 space-y-2">
                        {selectedNodeVerificationDecisions.map((decision) => (
                          <div
                            key={decision.id}
                            className="rounded-2xl border border-white/10 bg-slate-950/60 p-3"
                          >
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <p className="text-sm font-medium text-white">{formatMode(decision.decision)}</p>
                              <span className="text-xs text-slate-400">{formatDateTime(decision.created_at)}</span>
                            </div>
                            <p className="mt-2 text-xs text-slate-300">
                              {[decision.agent_id, decision.quorum_policy, decision.decision_source]
                                .filter((v): v is string => typeof v === 'string' && v.length > 0)
                                .map((v) => formatMode(v))
                                .join(' \u2022 ')}
                            </p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {selectedNodeSwarmHandoffs.length > 0 && (
                    <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                      <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Swarm handoffs</p>
                      <div className="mt-3 space-y-2">
                        {selectedNodeSwarmHandoffs.map((handoff) => (
                          <div
                            key={handoff.id}
                            className="rounded-2xl border border-white/10 bg-slate-950/60 p-3"
                          >
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <p className="text-sm font-medium text-white">{formatMode(handoff.handoff_type)}</p>
                              <span className="text-xs text-slate-400">Round {handoff.round_number}</span>
                            </div>
                            <p className="mt-2 text-xs text-slate-300">
                              {[handoff.from_agent_id, handoff.to_agent_id]
                                .filter((v): v is string => typeof v === 'string' && v.length > 0)
                                .join(' \u2192 ')}
                            </p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {selectedNodePolicyEvaluations.length > 0 && (
                    <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                      <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Policy evaluations</p>
                      <div className="mt-3 space-y-2">
                        {selectedNodePolicyEvaluations.map((evaluation) => (
                          <div
                            key={evaluation.id}
                            className="rounded-2xl border border-white/10 bg-slate-950/60 p-3"
                          >
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <p className="text-sm font-medium text-white">
                                {formatMode(evaluation.evaluation_type)}
                              </p>
                              <span className="text-xs uppercase tracking-[0.2em] text-slate-400">
                                {formatMode(evaluation.status)}
                              </span>
                            </div>
                            {evaluation.summary && (
                              <p className="mt-2 text-xs text-slate-300">{evaluation.summary}</p>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

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
                        <p className="text-sm font-semibold text-white">Attempt {attempt.attempt_number}</p>
                        <p className="mt-1 text-xs text-slate-400">{formatDateTime(attempt.created_at)}</p>
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
                      <DebugSection title="Attempt result" value={attempt.result} />
                    </div>
                  </div>
                ))}
              </div>
              <DebugSection title="Node result" value={selectedNode.result} />
            </>
          )}
        </div>
      </div>
    </details>
  )
}
