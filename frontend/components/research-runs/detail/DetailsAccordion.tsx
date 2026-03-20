'use client'

import { Activity, ChevronDown, DatabaseZap, ShieldCheck } from 'lucide-react'

import type {
  ResearchRunResponse,
  ResearchRunEvidenceResponse,
  ResearchRunEvidenceGraphResponse,
  ResearchRunReportPackResponse,
  ResearchRunVerificationDecisionResponse,
  ResearchRunSwarmHandoffResponse,
  ResearchRunPolicyEvaluationResponse,
  ResearchSourceCard,
} from '@/lib/api'

import {
  DebugSection,
  ExpandableText,
  formatDateTime,
  formatMode,
  SourceCards,
} from './shared'

export function DetailsAccordion({
  researchRun,
  evidencePayload,
  evidenceGraphData,
  reportPackData,
  recentVerificationDecisions,
  recentSwarmHandoffs,
  recentPolicyEvaluations,
  runSources,
  filteredSources,
  debugPayloads,
}: {
  researchRun: ResearchRunResponse
  evidencePayload: ResearchRunEvidenceResponse | null
  evidenceGraphData: ResearchRunEvidenceGraphResponse | null
  reportPackData: ResearchRunReportPackResponse | null
  recentVerificationDecisions: ResearchRunVerificationDecisionResponse[]
  recentSwarmHandoffs: ResearchRunSwarmHandoffResponse[]
  recentPolicyEvaluations: ResearchRunPolicyEvaluationResponse[]
  runSources: ResearchSourceCard[]
  filteredSources: ResearchSourceCard[]
  debugPayloads: { title: string; value: unknown }[]
}) {
  const claimTargets = Array.isArray(evidencePayload?.claim_targets) ? evidencePayload.claim_targets : []

  return (
    <details className="rounded-[28px] border border-white/15 bg-slate-900/75 text-slate-100 backdrop-blur-xl">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-6 py-5">
        <span className="text-sm font-semibold uppercase tracking-[0.25em] text-slate-300">
          Advanced details
        </span>
        <ChevronDown className="h-4 w-4 text-slate-400 transition details-open:rotate-180" />
      </summary>

      <div className="space-y-6 px-6 pb-6">
        {/* Adaptive controls */}
        <details className="rounded-2xl border border-amber-400/20 bg-amber-400/10 p-4">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-amber-100">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4" />
              <span className="text-sm font-semibold uppercase tracking-[0.3em]">Adaptive controls</span>
            </div>
            <ChevronDown className="h-4 w-4 transition details-open:rotate-180" />
          </summary>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="rounded-2xl border border-white/10 bg-black/10 p-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-amber-200/80">Strict mode</p>
              <p className="mt-2 text-sm font-medium text-white">
                {researchRun.policy.strict_mode ? 'Enabled' : 'Disabled'}
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-black/10 p-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-amber-200/80">Risk level</p>
              <p className="mt-2 text-sm font-medium capitalize text-white">
                {formatMode(researchRun.policy.risk_level)}
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-black/10 p-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-amber-200/80">Quorum policy</p>
              <p className="mt-2 text-sm font-medium capitalize text-white">
                {formatMode(researchRun.policy.quorum_policy)}
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-black/10 p-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-amber-200/80">Max attempts</p>
              <p className="mt-2 text-sm font-medium text-white">{researchRun.policy.max_node_attempts}</p>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-2 text-xs text-amber-50">
            <span className="rounded-full border border-white/10 bg-black/10 px-2 py-1">
              Reroute on failure: {researchRun.policy.reroute_on_failure ? 'Yes' : 'No'}
            </span>
            <span className="rounded-full border border-white/10 bg-black/10 px-2 py-1">
              Max swarm rounds: {researchRun.policy.max_swarm_rounds}
            </span>
            <span className="rounded-full border border-white/10 bg-black/10 px-2 py-1">
              Escalate on dissent: {researchRun.policy.escalate_on_dissent ? 'Yes' : 'No'}
            </span>
          </div>
        </details>

        {/* Persisted trace summary */}
        <details className="rounded-2xl border border-fuchsia-400/20 bg-fuchsia-400/10 p-4">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-fuchsia-100">
            <div className="flex items-center gap-2">
              <DatabaseZap className="h-4 w-4" />
              <span className="text-sm font-semibold uppercase tracking-[0.3em]">Persisted trace summary</span>
            </div>
            <ChevronDown className="h-4 w-4 transition details-open:rotate-180" />
          </summary>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="rounded-2xl border border-white/10 bg-black/10 p-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-fuchsia-200/80">Verification decisions</p>
              <p className="mt-2 text-sm font-medium text-white">
                {researchRun.trace_summary.verification_decision_count}
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-black/10 p-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-fuchsia-200/80">Swarm handoffs</p>
              <p className="mt-2 text-sm font-medium text-white">
                {researchRun.trace_summary.swarm_handoff_count}
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-black/10 p-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-fuchsia-200/80">Policy evaluations</p>
              <p className="mt-2 text-sm font-medium text-white">
                {researchRun.trace_summary.policy_evaluation_count}
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-black/10 p-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-fuchsia-200/80">Open dissent</p>
              <p className="mt-2 text-sm font-medium text-white">
                {researchRun.trace_summary.unresolved_dissent_count}
              </p>
            </div>
          </div>
          {reportPackData?.generated_at && (
            <p className="mt-4 text-xs text-fuchsia-100/80">
              Latest report pack: {formatDateTime(reportPackData.generated_at)}
            </p>
          )}
        </details>

        {/* Graph and report pack */}
        {(evidenceGraphData || reportPackData) && (
          <details className="rounded-2xl border border-violet-400/20 bg-violet-400/10 p-4">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-violet-100">
              <div className="flex items-center gap-2">
                <DatabaseZap className="h-4 w-4" />
                <span className="text-sm font-semibold uppercase tracking-[0.3em]">Graph and report pack</span>
              </div>
              <ChevronDown className="h-4 w-4 transition details-open:rotate-180" />
            </summary>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-2xl border border-white/10 bg-black/10 p-3">
                <p className="text-[11px] uppercase tracking-[0.25em] text-violet-200/80">Artifacts</p>
                <p className="mt-2 text-sm font-medium text-white">
                  {evidenceGraphData?.summary.artifact_count ?? 0}
                </p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-black/10 p-3">
                <p className="text-[11px] uppercase tracking-[0.25em] text-violet-200/80">Claims</p>
                <p className="mt-2 text-sm font-medium text-white">
                  {evidenceGraphData?.summary.claim_count ?? reportPackData?.claims.length ?? 0}
                </p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-black/10 p-3">
                <p className="text-[11px] uppercase tracking-[0.25em] text-violet-200/80">Cited artifacts</p>
                <p className="mt-2 text-sm font-medium text-white">
                  {evidenceGraphData?.summary.cited_artifact_count ?? reportPackData?.citations.length ?? 0}
                </p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-black/10 p-3">
                <p className="text-[11px] uppercase tracking-[0.25em] text-violet-200/80">Evidence links</p>
                <p className="mt-2 text-sm font-medium text-white">
                  {evidenceGraphData?.summary.link_count ?? reportPackData?.claim_lineage.length ?? 0}
                </p>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap gap-2 text-xs text-violet-50">
              {evidenceGraphData && (
                <>
                  <span className="rounded-full border border-white/10 bg-black/10 px-2 py-1">
                    High-confidence claims: {evidenceGraphData.summary.high_confidence_claim_count}
                  </span>
                  <span className="rounded-full border border-white/10 bg-black/10 px-2 py-1">
                    Mixed evidence: {evidenceGraphData.summary.mixed_evidence_claim_count}
                  </span>
                  <span className="rounded-full border border-white/10 bg-black/10 px-2 py-1">
                    Insufficient evidence: {evidenceGraphData.summary.insufficient_evidence_claim_count}
                  </span>
                </>
              )}
              {reportPackData?.schema_version && (
                <span className="rounded-full border border-white/10 bg-black/10 px-2 py-1">
                  {reportPackData.schema_version}
                </span>
              )}
            </div>
          </details>
        )}

        {/* Swarm trace */}
        {(recentVerificationDecisions.length > 0 ||
          recentSwarmHandoffs.length > 0 ||
          recentPolicyEvaluations.length > 0) && (
          <details className="rounded-2xl border border-rose-400/20 bg-rose-400/10 p-4">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-rose-100">
              <div className="flex items-center gap-2">
                <Activity className="h-4 w-4" />
                <span className="text-sm font-semibold uppercase tracking-[0.3em]">Swarm trace</span>
              </div>
              <ChevronDown className="h-4 w-4 transition details-open:rotate-180" />
            </summary>

            {recentVerificationDecisions.length > 0 && (
              <div className="mt-4 space-y-2">
                <p className="text-xs font-semibold uppercase tracking-[0.25em] text-rose-100/80">
                  Verification decisions
                </p>
                {recentVerificationDecisions.map((decision) => (
                  <div
                    key={decision.id}
                    className="rounded-2xl border border-white/10 bg-black/10 px-3 py-3 text-sm text-rose-50"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="font-medium text-white">
                        {formatMode(decision.node_id)} &middot; {formatMode(decision.decision)}
                      </p>
                      <span className="text-xs text-rose-100/70">{formatDateTime(decision.created_at)}</span>
                    </div>
                    <p className="mt-2 text-xs text-rose-100/80">
                      {[decision.agent_id, decision.quorum_policy, decision.decision_source]
                        .filter((v): v is string => typeof v === 'string' && v.length > 0)
                        .map((v) => formatMode(v))
                        .join(' \u2022 ')}
                    </p>
                  </div>
                ))}
              </div>
            )}

            {recentSwarmHandoffs.length > 0 && (
              <div className="mt-4 space-y-2">
                <p className="text-xs font-semibold uppercase tracking-[0.25em] text-rose-100/80">
                  Blackboard handoffs
                </p>
                {recentSwarmHandoffs.map((handoff) => (
                  <div
                    key={handoff.id}
                    className="rounded-2xl border border-white/10 bg-black/10 px-3 py-3 text-sm text-rose-50"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="font-medium text-white">{formatMode(handoff.handoff_type)}</p>
                      <span className="text-xs text-rose-100/70">Round {handoff.round_number}</span>
                    </div>
                    <p className="mt-2 text-xs text-rose-100/80">
                      {[handoff.from_agent_id, handoff.to_agent_id, handoff.node_id]
                        .filter((v): v is string => typeof v === 'string' && v.length > 0)
                        .map((v) => formatMode(v))
                        .join(' \u2192 ')}
                    </p>
                  </div>
                ))}
              </div>
            )}

            {recentPolicyEvaluations.length > 0 && (
              <div className="mt-4 space-y-2">
                <p className="text-xs font-semibold uppercase tracking-[0.25em] text-rose-100/80">
                  Policy evaluations
                </p>
                {recentPolicyEvaluations.map((evaluation) => (
                  <div
                    key={evaluation.id}
                    className="rounded-2xl border border-white/10 bg-black/10 px-3 py-3 text-sm text-rose-50"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="font-medium text-white">{formatMode(evaluation.evaluation_type)}</p>
                      <span className="text-xs uppercase tracking-[0.2em] text-rose-100/70">
                        {formatMode(evaluation.status)}
                      </span>
                    </div>
                    {evaluation.summary && (
                      <p className="mt-2 text-xs text-rose-100/80">{evaluation.summary}</p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </details>
        )}

        {/* Evidence view */}
        {(evidencePayload?.rewritten_research_brief ||
          claimTargets.length > 0 ||
          (evidencePayload?.search_lanes_used?.length ?? 0) > 0) && (
          <details className="rounded-2xl border border-cyan-400/20 bg-cyan-400/10 p-4">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-cyan-100">
              <div className="flex items-center gap-2">
                <Activity className="h-4 w-4" />
                <span className="text-sm font-semibold uppercase tracking-[0.3em]">Evidence view</span>
              </div>
              <ChevronDown className="h-4 w-4 transition details-open:rotate-180" />
            </summary>

            {evidencePayload?.rewritten_research_brief && (
              <div className="mt-4">
                <p className="text-xs font-semibold uppercase tracking-[0.25em] text-cyan-200/80">
                  Rewritten brief
                </p>
                <div className="mt-2">
                  <ExpandableText
                    content={evidencePayload.rewritten_research_brief}
                    collapsedHeight="max-h-24"
                    buttonLabel="Expand brief"
                    className="text-cyan-50"
                  />
                </div>
              </div>
            )}

            <div className="mt-4 flex flex-wrap gap-2 text-xs text-cyan-50">
              {(evidencePayload?.search_lanes_used ?? []).map((lane) => (
                <span
                  key={lane}
                  className="rounded-full border border-cyan-300/20 bg-cyan-300/10 px-2 py-1"
                >
                  {formatMode(lane)}
                </span>
              ))}
              {claimTargets.length > 0 && (
                <span className="rounded-full border border-cyan-300/20 bg-cyan-300/10 px-2 py-1">
                  Claim targets: {claimTargets.length}
                </span>
              )}
            </div>

            {claimTargets.length > 0 && (
              <div className="mt-4 grid gap-2 md:grid-cols-2">
                {claimTargets.map((target, index) => (
                  <div
                    key={`${String(target.claim_id ?? target.claim_target ?? index)}`}
                    className="rounded-2xl border border-white/10 bg-white/5 p-3 text-sm text-cyan-50"
                  >
                    <p className="font-medium text-white">
                      {String(target.claim_target ?? target.claim ?? 'Claim target')}
                    </p>
                    <p className="mt-2 text-[11px] uppercase tracking-[0.2em] text-cyan-100/70">
                      {[target.claim_id, target.priority, target.lane]
                        .filter((v): v is string => typeof v === 'string' && v.length > 0)
                        .join(' \u2022 ') || 'Target'}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </details>
        )}

        {/* Sources */}
        <SourceCards sources={runSources} />
        <SourceCards sources={filteredSources} title="Filtered or downranked sources" />

        {/* Run metadata */}
        <details className="rounded-2xl border border-white/10 bg-white/5 p-4">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-xs font-semibold uppercase tracking-[0.25em] text-slate-300">
            <span>Run metadata</span>
            <ChevronDown className="h-4 w-4 text-slate-400 transition details-open:rotate-180" />
          </summary>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <div className="rounded-2xl border border-white/10 bg-slate-950/60 p-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-slate-400">Verification mode</p>
              <p className="mt-2 text-sm font-medium capitalize text-white">{researchRun.verification_mode}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-slate-950/60 p-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-slate-400">Classified mode</p>
              <p className="mt-2 text-sm font-medium capitalize text-white">
                {formatMode(researchRun.classified_mode)}
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-slate-950/60 p-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-slate-400">Depth</p>
              <p className="mt-2 text-sm font-medium capitalize text-white">
                {formatMode(researchRun.depth_mode)}
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-slate-950/60 p-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-slate-400">Evidence rounds</p>
              <p className="mt-2 text-sm font-medium text-white">
                {researchRun.rounds_completed.evidence_rounds ?? 0}/
                {researchRun.rounds_planned.evidence_rounds ?? 0}
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-slate-950/60 p-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-slate-400">Critique rounds</p>
              <p className="mt-2 text-sm font-medium text-white">
                {researchRun.rounds_completed.critique_rounds ?? 0}/
                {researchRun.rounds_planned.critique_rounds ?? 0}
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-slate-950/60 p-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-slate-400">Run ID</p>
              <p className="mt-2 break-all text-sm font-medium text-white">{researchRun.id}</p>
            </div>
          </div>
          <div className="mt-4 rounded-2xl border border-white/10 bg-slate-950/60 p-3">
            <p className="text-[11px] uppercase tracking-[0.25em] text-slate-400">Workflow</p>
            <p className="mt-2 whitespace-pre-wrap break-words font-mono text-sm text-sky-100">
              {researchRun.workflow}
            </p>
          </div>
        </details>

        {/* Debug payloads */}
        <details className="rounded-2xl border border-white/10 bg-white/5 p-4">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-xs font-semibold uppercase tracking-[0.25em] text-slate-300">
            <span>Debug payloads</span>
            <ChevronDown className="h-4 w-4 text-slate-400 transition details-open:rotate-180" />
          </summary>
          <div className="mt-4 space-y-3">
            {debugPayloads.map((payload) => (
              <DebugSection key={payload.title} title={payload.title} value={payload.value} />
            ))}
          </div>
        </details>
      </div>
    </details>
  )
}
