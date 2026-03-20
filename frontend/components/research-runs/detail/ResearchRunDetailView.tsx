'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { Loader2, RefreshCw } from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { VerificationReviewCard } from '@/components/VerificationReviewCard'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  approveVerification,
  cancelResearchRun,
  getResearchRun,
  getResearchRunEvidence,
  getResearchRunEvidenceGraph,
  getResearchRunPolicyEvaluations,
  getResearchRunReport,
  getResearchRunReportPack,
  getResearchRunSwarmHandoffs,
  getResearchRunVerificationDecisions,
  getTask,
  pauseResearchRun,
  rejectVerification,
  resumeResearchRun,
  type ResearchClaim,
  type ResearchCriticFinding,
  type ResearchQualitySummary,
  type ResearchSourceCard,
} from '@/lib/api'

import { ResearchRunStatusBadge } from '../ResearchRunStatusBadge'
import {
  dedupeSources,
  getCitationId,
  getRunClaims,
  getRunHeadline,
  getRunPayload,
  getRunQualitySummary,
  getRunSources,
  getCriticFindings,
  linkInlineCitations,
  pickFocusNode,
  TERMINAL_RUN_STATUSES,
} from './shared'
import { RunHeader } from './RunHeader'
import { ProgressStepper } from './ProgressStepper'
import { ReportView } from './ReportView'
import { FollowUpChat } from './FollowUpChat'
import { DetailsAccordion } from './DetailsAccordion'
import { PipelineRail } from './PipelineRail'

export function ResearchRunDetailView({
  researchRunId,
  onComplete,
  hideFollowUpChat,
}: {
  researchRunId: string
  onComplete?: (ctx: { report: string; citations: ResearchSourceCard[] }) => void
  hideFollowUpChat?: boolean
}) {
  const queryClient = useQueryClient()
  const [activeNodeId, setActiveNodeId] = useState<string | null>(null)
  const [controlAction, setControlAction] = useState<'pause' | 'resume' | 'cancel' | null>(null)
  const completeFiredRef = useRef(false)
  const [controlError, setControlError] = useState<string | null>(null)

  const getActivePollingInterval = () => {
    const status = queryClient.getQueryData<{ status: string }>(['research-run', researchRunId])?.status
    return status && TERMINAL_RUN_STATUSES.has(status) ? false : 2000
  }

  // --- Queries ---
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

  const evidenceQuery = useQuery({
    queryKey: ['research-run', researchRunId, 'evidence'],
    queryFn: () => getResearchRunEvidence(researchRunId),
    retry: false,
    refetchInterval: getActivePollingInterval,
    refetchIntervalInBackground: true,
  })

  const reportQuery = useQuery({
    queryKey: ['research-run', researchRunId, 'report'],
    queryFn: () => getResearchRunReport(researchRunId),
    retry: false,
    refetchInterval: getActivePollingInterval,
    refetchIntervalInBackground: true,
  })

  const evidenceGraphQuery = useQuery({
    queryKey: ['research-run', researchRunId, 'evidence-graph'],
    queryFn: () => getResearchRunEvidenceGraph(researchRunId),
    retry: false,
    refetchInterval: getActivePollingInterval,
    refetchIntervalInBackground: true,
  })

  const reportPackQuery = useQuery({
    queryKey: ['research-run', researchRunId, 'report-pack'],
    queryFn: () => getResearchRunReportPack(researchRunId),
    retry: false,
    refetchInterval: getActivePollingInterval,
    refetchIntervalInBackground: true,
  })

  const verificationDecisionsQuery = useQuery({
    queryKey: ['research-run', researchRunId, 'verification-decisions'],
    queryFn: () => getResearchRunVerificationDecisions(researchRunId),
    retry: false,
    refetchInterval: getActivePollingInterval,
    refetchIntervalInBackground: true,
  })

  const swarmHandoffsQuery = useQuery({
    queryKey: ['research-run', researchRunId, 'swarm-handoffs'],
    queryFn: () => getResearchRunSwarmHandoffs(researchRunId),
    retry: false,
    refetchInterval: getActivePollingInterval,
    refetchIntervalInBackground: true,
  })

  const policyEvaluationsQuery = useQuery({
    queryKey: ['research-run', researchRunId, 'policy-evaluations'],
    queryFn: () => getResearchRunPolicyEvaluations(researchRunId),
    retry: false,
    refetchInterval: getActivePollingInterval,
    refetchIntervalInBackground: true,
  })

  // --- Derived data ---
  const orderedNodes = useMemo(
    () =>
      [...(researchRunQuery.data?.nodes ?? [])].sort(
        (left, right) => left.execution_order - right.execution_order,
      ),
    [researchRunQuery.data?.nodes],
  )

  useEffect(() => {
    if (orderedNodes.length === 0) return

    const focusedNode = pickFocusNode(orderedNodes)
    const activeNodeStillExists = orderedNodes.some((node) => node.node_id === activeNodeId)

    if (!activeNodeStillExists) {
      setActiveNodeId(focusedNode?.node_id ?? orderedNodes[0].node_id)
      return
    }

    const activeNode = orderedNodes.find((node) => node.node_id === activeNodeId)
    if (
      activeNode &&
      ['completed', 'pending', 'blocked', 'cancelled'].includes(activeNode.status) &&
      focusedNode &&
      ['waiting_for_review', 'running', 'failed', 'cancelled'].includes(focusedNode.status)
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

  const relevantPaymentIds = [
    ...new Set(
      [
        selectedNode?.payment_id,
        waitingNode?.payment_id,
        waitingTaskQuery.data?.verification_data?.payment_id,
      ].filter(
        (paymentId): paymentId is string =>
          typeof paymentId === 'string' && paymentId.length > 0,
      ),
    ),
  ]

  const invalidateRelevantPaymentQueries = () =>
    Promise.all(
      relevantPaymentIds.flatMap((paymentId) => [
        queryClient.invalidateQueries({ queryKey: ['payment', paymentId] }),
        queryClient.invalidateQueries({ queryKey: ['payment', paymentId, 'events'] }),
      ]),
    )

  const invalidateResearchRunQueries = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ['research-run', researchRunId] }),
      queryClient.invalidateQueries({ queryKey: ['research-run', researchRunId, 'evidence'] }),
      queryClient.invalidateQueries({ queryKey: ['research-run', researchRunId, 'report'] }),
      queryClient.invalidateQueries({ queryKey: ['research-run', researchRunId, 'evidence-graph'] }),
      queryClient.invalidateQueries({ queryKey: ['research-run', researchRunId, 'report-pack'] }),
      queryClient.invalidateQueries({
        queryKey: ['research-run', researchRunId, 'verification-decisions'],
      }),
      queryClient.invalidateQueries({ queryKey: ['research-run', researchRunId, 'swarm-handoffs'] }),
      queryClient.invalidateQueries({
        queryKey: ['research-run', researchRunId, 'policy-evaluations'],
      }),
    ])

  // --- Handlers ---
  const handleApproveReview = async (taskId: string) => {
    await approveVerification(taskId)
    await Promise.all([
      invalidateResearchRunQueries(),
      queryClient.invalidateQueries({ queryKey: ['task', taskId] }),
      invalidateRelevantPaymentQueries(),
    ])
  }

  const handleRejectReview = async (taskId: string, reason?: string) => {
    await rejectVerification(taskId, reason)
    await Promise.all([
      invalidateResearchRunQueries(),
      queryClient.invalidateQueries({ queryKey: ['task', taskId] }),
      invalidateRelevantPaymentQueries(),
    ])
  }

  const handleRunControl = async (action: 'pause' | 'resume' | 'cancel') => {
    setControlAction(action)
    setControlError(null)
    try {
      if (action === 'pause') await pauseResearchRun(researchRunId)
      else if (action === 'resume') await resumeResearchRun(researchRunId)
      else await cancelResearchRun(researchRunId)

      await Promise.all([
        invalidateResearchRunQueries(),
        waitingTaskId
          ? queryClient.invalidateQueries({ queryKey: ['task', waitingTaskId] })
          : Promise.resolve(),
        invalidateRelevantPaymentQueries(),
      ])
    } catch (error) {
      setControlError(
        error instanceof Error ? error.message : 'Unable to update the research run right now.',
      )
    } finally {
      setControlAction(null)
    }
  }

  // Notify parent when report is ready
  const runData = researchRunQuery.data
  const runIsTerminal = runData ? TERMINAL_RUN_STATUSES.has(runData.status) : false
  const runHeadline = (() => {
    if (!runData) return null
    const rp = reportQuery.data ?? reportPackQuery.data ?? getRunPayload(runData)
    const rPayload = rp && typeof rp === 'object' ? (rp as Record<string, unknown>) : null
    return typeof rPayload?.answer_markdown === 'string'
      ? rPayload.answer_markdown as string
      : typeof rPayload?.answer === 'string'
        ? rPayload.answer as string
        : getRunHeadline(runData)
  })()

  useEffect(() => {
    if (runIsTerminal && runHeadline && onComplete && !completeFiredRef.current) {
      completeFiredRef.current = true
      const evPayload = evidenceQuery.data ?? null
      const rp = reportQuery.data ?? reportPackQuery.data ?? (runData ? getRunPayload(runData) : null)
      const rPayload = rp && typeof rp === 'object' ? (rp as Record<string, unknown>) : null
      const cits = Array.isArray(rPayload?.citations)
        ? (rPayload.citations as ResearchSourceCard[])
        : []
      const rSources = evPayload?.sources?.length
        ? evPayload.sources
        : runData ? getRunSources(runData) : []
      const allSources = dedupeSources([
        ...cits,
        ...rSources.filter((s: ResearchSourceCard) => Boolean(getCitationId(s))),
      ])
      onComplete({ report: runHeadline, citations: allSources })
    }
  }, [runIsTerminal, runHeadline, onComplete, runData, reportQuery.data, reportPackQuery.data, evidenceQuery.data])

  // --- Loading/Error states ---
  if (researchRunQuery.isLoading) {
    return (
      <Card className="rounded-[28px] border border-white/15 bg-slate-900/75 text-slate-100 backdrop-blur-xl">
        <CardContent className="flex items-center justify-center gap-3 py-16">
          <Loader2 className="h-5 w-5 animate-spin text-sky-300" />
          <span>Loading research run...</span>
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

  // --- Derive report data ---
  const researchRun = researchRunQuery.data
  const isTerminal = TERMINAL_RUN_STATUSES.has(researchRun.status)
  const fallbackRunPayload = getRunPayload(researchRun)
  const reportData = reportQuery.data ?? null
  const evidenceGraphData = evidenceGraphQuery.data ?? null
  const reportPackData = reportPackQuery.data ?? null
  const verificationDecisions = verificationDecisionsQuery.data ?? []
  const swarmHandoffs = swarmHandoffsQuery.data ?? []
  const policyEvaluations = policyEvaluationsQuery.data ?? []
  const reportPayload: Record<string, any> | null =
    reportData && typeof reportData === 'object'
      ? (reportData as unknown as Record<string, any>)
      : reportPackData && typeof reportPackData === 'object'
        ? (reportPackData as unknown as Record<string, any>)
        : fallbackRunPayload
  const evidencePayload = evidenceQuery.data ?? null
  const headline =
    typeof reportPayload?.answer_markdown === 'string'
      ? reportPayload.answer_markdown
      : typeof reportPayload?.answer === 'string'
        ? reportPayload.answer
        : getRunHeadline(researchRun)
  const claims = Array.isArray(reportPayload?.claims)
    ? (reportPayload.claims as ResearchClaim[])
    : getRunClaims(researchRun)
  const runSources = evidencePayload?.sources?.length
    ? evidencePayload.sources
    : getRunSources(researchRun)
  const filteredSources = evidencePayload?.filtered_sources ?? []
  const criticFindings = Array.isArray(reportPayload?.critic_findings)
    ? (reportPayload.critic_findings as ResearchCriticFinding[])
    : getCriticFindings(researchRun)
  const qualitySummary =
    reportPayload && typeof reportPayload.quality_summary === 'object'
      ? (reportPayload.quality_summary as ResearchQualitySummary)
      : getRunQualitySummary(researchRun)
  const citations = Array.isArray(reportPayload?.citations)
    ? (reportPayload.citations as ResearchSourceCard[])
    : []
  const limitations = Array.isArray(reportPayload?.limitations)
    ? reportPayload.limitations.filter((item: unknown): item is string => typeof item === 'string')
    : []
  const freshnessSummary =
    evidencePayload?.freshness_summary ??
    (reportPayload && typeof reportPayload.freshness_summary === 'object'
      ? (reportPayload.freshness_summary as Record<string, any>)
      : null)
  const sourceSummary =
    evidencePayload?.source_summary ??
    (reportPayload && typeof reportPayload.source_summary === 'object'
      ? (reportPayload.source_summary as Record<string, any>)
      : null)
  const citedSources = dedupeSources([
    ...citations,
    ...runSources.filter((source) => Boolean(getCitationId(source))),
  ])
  const citationLookup = (() => {
    const lookup = new Map<string, ResearchSourceCard>()
    for (const source of citedSources) {
      const citationId = getCitationId(source)
      if (citationId) lookup.set(citationId, source)
      lookup.set(source.title, source)
    }
    return lookup
  })()
  const linkedHeadline = (() => {
    if (!headline) return null
    const citationIds = citedSources
      .map((source) => getCitationId(source))
      .filter((citationId): citationId is string => Boolean(citationId))
    return citationIds.length > 0 ? linkInlineCitations(headline, citationIds) : headline
  })()

  const recentVerificationDecisions = [...verificationDecisions].slice(-4).reverse()
  const recentSwarmHandoffs = [...swarmHandoffs].slice(-6).reverse()
  const recentPolicyEvaluations = [...policyEvaluations].slice(-4).reverse()

  const hasReport = headline || claims.length > 0 || citedSources.length > 0

  const debugPayloads = [
    { title: 'Research run evidence', value: evidenceQuery.data },
    { title: 'Research run report', value: reportQuery.data },
    { title: 'Research run evidence graph', value: evidenceGraphQuery.data },
    { title: 'Research run report pack', value: reportPackQuery.data },
    { title: 'Research run verification decisions', value: verificationDecisionsQuery.data },
    { title: 'Research run swarm handoffs', value: swarmHandoffsQuery.data },
    { title: 'Research run policy evaluations', value: policyEvaluationsQuery.data },
    { title: 'Research run result', value: researchRun.result },
  ]

  return (
    <div className="space-y-6">
      {/* Human review section */}
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
                Loading verification packet...
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

      {/* Compact header */}
      <RunHeader
        researchRun={researchRun}
        controlAction={controlAction}
        controlError={controlError}
        onRunControl={handleRunControl}
      />

      {/* Progress stepper (running state only) */}
      {!isTerminal && (
        <ProgressStepper
          nodes={orderedNodes}
          activeNodeId={activeNodeId}
          onNodeClick={setActiveNodeId}
        />
      )}

      {/* Report view (terminal state) */}
      {isTerminal && hasReport && (
        <ReportView
          linkedHeadline={linkedHeadline}
          claims={claims}
          citedSources={citedSources}
          citationLookup={citationLookup}
          criticFindings={criticFindings}
          limitations={limitations}
          qualitySummary={qualitySummary}
          sourceSummary={sourceSummary}
          freshnessSummary={freshnessSummary}
          qualityTier={researchRun.quality_tier}
          qualityWarnings={researchRun.quality_warnings ?? []}
        />
      )}

      {/* Follow-up chat (terminal state with report, unless hidden by parent) */}
      {isTerminal && headline && !hideFollowUpChat && (
        <FollowUpChat
          report={headline}
          citations={citedSources}
        />
      )}

      {/* Pipeline rail */}
      <PipelineRail
        orderedNodes={orderedNodes}
        selectedNode={selectedNode}
        activeNodeId={activeNodeId}
        onNodeClick={setActiveNodeId}
        verificationDecisions={verificationDecisions}
        swarmHandoffs={swarmHandoffs}
        policyEvaluations={policyEvaluations}
        runStatus={researchRun.status}
        defaultOpen={!isTerminal}
      />

      {/* Advanced details */}
      <DetailsAccordion
        researchRun={researchRun}
        evidencePayload={evidencePayload}
        evidenceGraphData={evidenceGraphData}
        reportPackData={reportPackData}
        recentVerificationDecisions={recentVerificationDecisions}
        recentSwarmHandoffs={recentSwarmHandoffs}
        recentPolicyEvaluations={recentPolicyEvaluations}
        runSources={runSources}
        filteredSources={filteredSources}
        debugPayloads={debugPayloads}
      />
    </div>
  )
}
