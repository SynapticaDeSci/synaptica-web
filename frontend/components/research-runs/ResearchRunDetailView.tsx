'use client'

import { useEffect, useMemo, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  Clock3,
  Coins,
  DatabaseZap,
  ChevronDown,
  ExternalLink,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  Slash,
  ShieldCheck,
} from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'

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
  getPayment,
  getPaymentEvents,
  getTask,
  pauseResearchRun,
  type ResearchClaim,
  type ResearchCriticFinding,
  type ResearchRunEvidenceGraphResponse,
  rejectVerification,
  resumeResearchRun,
  type PaymentDetailResponse,
  type PaymentEventsResponse,
  type ResearchRunEvidenceResponse,
  type ResearchRunNodeResponse,
  type ResearchRunNodeStatus,
  type ResearchRunPolicyEvaluationResponse,
  type ResearchRunReportResponse,
  type ResearchRunReportPackResponse,
  type ResearchRunResponse,
  type ResearchRunSwarmHandoffResponse,
  type ResearchRunVerificationDecisionResponse,
  type ResearchQualitySummary,
  type ResearchSourceCard,
} from '@/lib/api'
import { cn } from '@/lib/utils'

import { ResearchRunStatusBadge } from './ResearchRunStatusBadge'

const TERMINAL_RUN_STATUSES = new Set(['completed', 'failed', 'cancelled'])

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

function isRecord(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function getRunHeadline(run: ResearchRunResponse): string | null {
  const payload = run.result && typeof run.result === 'object' ? run.result : null
  if (payload && typeof payload.answer_markdown === 'string') {
    return payload.answer_markdown
  }
  if (payload && typeof payload.answer === 'string') {
    return payload.answer
  }
  const report = payload && typeof payload.report === 'object' ? payload.report : null
  if (report && typeof report.answer === 'string') {
    return report.answer
  }
  if (run.error) {
    return run.error
  }
  return null
}

function getRunClaims(run: ResearchRunResponse): ResearchClaim[] {
  const payload = run.result && typeof run.result === 'object' ? run.result : null
  if (payload && Array.isArray(payload.claims)) {
    return payload.claims
      .map((item: unknown) =>
        item && typeof item === 'object' && typeof (item as ResearchClaim).claim === 'string'
          ? (item as ResearchClaim)
          : null,
      )
      .filter((item: ResearchClaim | null): item is ResearchClaim => Boolean(item))
  }
  return []
}

function getRunSources(run: ResearchRunResponse): ResearchSourceCard[] {
  const payload = run.result && typeof run.result === 'object' ? run.result : null
  if (!payload || !Array.isArray(payload.sources)) {
    return []
  }
  return payload.sources.filter(
    (item: unknown): item is ResearchSourceCard =>
      Boolean(item) && typeof item === 'object' && typeof (item as ResearchSourceCard).title === 'string',
  )
}

function getCriticFindings(run: ResearchRunResponse): ResearchCriticFinding[] {
  const payload = run.result && typeof run.result === 'object' ? run.result : null
  if (!payload || !Array.isArray(payload.critic_findings)) {
    return []
  }
  return payload.critic_findings.filter(
    (item: unknown): item is ResearchCriticFinding =>
      Boolean(item) && typeof item === 'object' && typeof (item as ResearchCriticFinding).issue === 'string',
  )
}

function getRunPayload(run: ResearchRunResponse): Record<string, any> | null {
  return run.result && typeof run.result === 'object' ? (run.result as Record<string, any>) : null
}

function getRunQualitySummary(run: ResearchRunResponse): ResearchQualitySummary | null {
  const payload = getRunPayload(run)
  return isRecord(payload?.quality_summary) ? (payload.quality_summary as ResearchQualitySummary) : null
}

function formatMode(value: string) {
  return value.replace(/_/g, ' ')
}

function cleanDisplayText(value: string) {
  return value
    .replace(/\r/g, '')
    .replace(/(^|\n)#{1,6}\s*/g, '$1')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

function normalizeStringList(value: unknown): string[] {
  if (typeof value === 'string') {
    return value.trim() ? [value] : []
  }

  if (!Array.isArray(value)) {
    return []
  }

  return value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
}

function formatCoverage(value?: number | null) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return null
  }

  const normalized = value <= 1 ? value * 100 : value
  return `${Math.round(normalized)}%`
}

function formatSourceDiversity(
  value: ResearchQualitySummary['source_diversity'],
): string | null {
  if (typeof value === 'number') {
    return `${value} source groups`
  }

  if (typeof value === 'string' && value.trim()) {
    return value
  }

  if (!isRecord(value)) {
    return null
  }

  const parts = Object.entries(value)
    .filter(([, item]) => typeof item === 'string' || typeof item === 'number')
    .map(([key, item]) => `${formatMode(key)}: ${item}`)

  return parts.length > 0 ? parts.join(' • ') : null
}

function getCitationId(source: ResearchSourceCard) {
  return typeof source.citation_id === 'string' && source.citation_id.trim().length > 0
    ? source.citation_id.trim()
    : null
}

function citationAnchorId(citationId: string) {
  return `citation-${citationId.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`
}

function citationSourceKey(source: ResearchSourceCard) {
  return getCitationId(source) || source.url || source.title
}

function dedupeSources(sources: ResearchSourceCard[]) {
  const seen = new Map<string, ResearchSourceCard>()

  for (const source of sources) {
    seen.set(citationSourceKey(source), source)
  }

  return [...seen.values()]
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function linkInlineCitations(markdown: string, citationIds: string[]) {
  return citationIds.reduce((current, citationId) => {
    const pattern = new RegExp(`\\[(${escapeRegExp(citationId)})\\](?!\\()`, 'g')
    return current.replace(pattern, `[$1](#${citationAnchorId(citationId)})`)
  }, markdown)
}

function pickFocusNode(nodes: ResearchRunNodeResponse[]) {
  const priority: ResearchRunNodeStatus[] = [
    'waiting_for_review',
    'running',
    'failed',
    'cancelled',
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

function ExpandableText({
  content,
  className,
  collapsedHeight = 'max-h-72',
  buttonLabel = 'Show more',
}: {
  content: string
  className?: string
  collapsedHeight?: string
  buttonLabel?: string
}) {
  const [expanded, setExpanded] = useState(false)
  const normalized = useMemo(() => cleanDisplayText(content), [content])
  const shouldCollapse = normalized.length > 420 || normalized.split('\n').length > 7

  return (
    <div className="space-y-3">
      <div className="relative">
        <div
          className={cn(
            'min-w-0 whitespace-pre-wrap break-words text-sm leading-relaxed',
            !expanded && shouldCollapse && `overflow-hidden ${collapsedHeight}`,
            className,
          )}
        >
          {normalized}
        </div>
        {!expanded && shouldCollapse && (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 rounded-b-2xl bg-gradient-to-t from-slate-900/95 via-slate-900/75 to-transparent" />
        )}
      </div>

      {shouldCollapse && (
        <Button
          type="button"
          variant="ghost"
          onClick={() => setExpanded((current) => !current)}
          className="h-auto px-0 text-xs font-semibold uppercase tracking-[0.2em] text-sky-200 hover:bg-transparent hover:text-sky-100"
        >
          {expanded ? 'Show less' : buttonLabel}
        </Button>
      )}
    </div>
  )
}

function DebugSection({ title, value }: { title: string; value: unknown }) {
  const content = stringifyValue(value)
  if (!content) {
    return null
  }

  return (
    <details className="rounded-2xl border border-white/10 bg-white/5 p-4">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-xs font-semibold uppercase tracking-[0.25em] text-slate-300">
        <span>{title}</span>
        <ChevronDown className="h-4 w-4 text-slate-400 transition details-open:rotate-180" />
      </summary>
      <div className="mt-4">
        <JsonPreview title={title} value={value} />
      </div>
    </details>
  )
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
          'max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-2xl border p-4 text-xs leading-relaxed',
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

function SourceCards({
  sources,
  title = 'Linked sources',
}: {
  sources: ResearchSourceCard[]
  title?: string
}) {
  if (sources.length === 0) {
    return null
  }

  return (
    <div className="space-y-3">
      <p className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-400">{title}</p>
      <div className="space-y-3">
        {sources.map((source) => (
          <a
            key={`${source.url}-${source.title}`}
            href={source.url}
            target="_blank"
            rel="noreferrer"
            className="block rounded-3xl border border-white/10 bg-white/5 p-4 transition hover:bg-white/10"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 space-y-2">
                <p className="text-sm font-semibold text-white">{source.title}</p>
                <div className="flex flex-wrap gap-2 text-xs text-slate-400">
                  {getCitationId(source) && (
                    <span className="rounded-full border border-sky-400/20 bg-sky-400/10 px-2 py-1 font-semibold uppercase tracking-[0.18em] text-sky-100">
                      {getCitationId(source)}
                    </span>
                  )}
                  {source.publisher && (
                    <span className="rounded-full border border-white/10 bg-white/5 px-2 py-1">
                      {source.publisher}
                    </span>
                  )}
                  {source.source_type && (
                    <span className="rounded-full border border-white/10 bg-white/5 px-2 py-1 capitalize">
                      {formatMode(source.source_type)}
                    </span>
                  )}
                  {source.published_at && (
                    <span className="rounded-full border border-white/10 bg-white/5 px-2 py-1">
                      {formatDateTime(source.published_at)}
                    </span>
                  )}
                  {(source.quality_flags ?? []).map((flag) => (
                    <span
                      key={`${source.url}-${flag}`}
                      className="rounded-full border border-amber-400/20 bg-amber-400/10 px-2 py-1 text-amber-100"
                    >
                      {formatMode(flag)}
                    </span>
                  ))}
                </div>
                {(source.display_snippet || source.snippet) && (
                  <ExpandableText
                    content={source.display_snippet || source.snippet || ''}
                    collapsedHeight="max-h-36"
                    buttonLabel="Read snippet"
                    className="text-slate-300"
                  />
                )}
              </div>
              <ExternalLink className="mt-1 h-4 w-4 shrink-0 text-sky-300" />
            </div>
          </a>
        ))}
      </div>
    </div>
  )
}

function PaymentActivityPanel({
  payment,
  paymentEvents,
}: {
  payment?: PaymentDetailResponse
  paymentEvents?: PaymentEventsResponse
}) {
  if (!payment) {
    return null
  }

  const notifications = paymentEvents?.notifications ?? []
  const transitions = paymentEvents?.state_transitions ?? []
  const reconciliations = paymentEvents?.reconciliations ?? []

  return (
    <div className="space-y-4 rounded-2xl border border-white/10 bg-white/5 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">
            Payment activity
          </p>
          <p className="mt-1 text-sm text-slate-300">
            Track the payment state, profile verification, and payer/payee delivery.
          </p>
        </div>
        <span className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.2em] text-emerald-100">
          {payment.status}
        </span>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-2xl border border-white/10 bg-slate-950/60 p-3">
          <p className="text-[11px] uppercase tracking-[0.25em] text-slate-400">Transaction</p>
          <p className="mt-2 break-all text-sm text-slate-200">{payment.transaction_id || 'Pending'}</p>
        </div>
        <div className="rounded-2xl border border-white/10 bg-slate-950/60 p-3">
          <p className="text-[11px] uppercase tracking-[0.25em] text-slate-400">Mode</p>
          <p className="mt-2 text-sm capitalize text-slate-200">
            {payment.payment_mode || 'Not recorded'}
          </p>
        </div>
        <div className="rounded-2xl border border-white/10 bg-slate-950/60 p-3">
          <p className="text-[11px] uppercase tracking-[0.25em] text-slate-400">Payee profile</p>
          <p className="mt-2 text-sm text-slate-200">
            {payment.payment_profile?.status || 'Not recorded'}
          </p>
        </div>
        <div className="rounded-2xl border border-white/10 bg-slate-950/60 p-3">
          <p className="text-[11px] uppercase tracking-[0.25em] text-slate-400">Notifications</p>
          <p className="mt-2 text-sm text-slate-200">
            {notifications.length} delivered
            {typeof payment.notification_summary?.reconciliations === 'number'
              ? ` • ${payment.notification_summary.reconciliations} reconciliations`
              : ''}
          </p>
        </div>
      </div>

      {payment.verification_notes && (
        <div className="rounded-2xl border border-emerald-400/20 bg-emerald-400/10 p-3 text-sm text-emerald-50">
          {payment.verification_notes}
        </div>
      )}

      {payment.rejection_reason && (
        <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-100">
          {payment.rejection_reason}
        </div>
      )}

      {(transitions.length > 0 || notifications.length > 0 || reconciliations.length > 0) && (
        <div className="space-y-3">
          <p className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-400">
            Delivery timeline
          </p>
          <div className="space-y-2">
            {transitions.map((transition) => (
              <div
                key={`transition-${transition.id ?? transition.idempotency_key ?? transition.action}`}
                className="rounded-2xl border border-white/10 bg-slate-950/60 p-3 text-sm text-slate-200"
              >
                <p className="font-medium text-white">
                  {transition.action} • {transition.state}
                </p>
                <p className="mt-1 text-xs text-slate-400">{formatDateTime(transition.created_at)}</p>
              </div>
            ))}
            {notifications.map((notification) => (
              <div
                key={`notification-${notification.id ?? notification.message_id}`}
                className="rounded-2xl border border-white/10 bg-slate-950/60 p-3 text-sm text-slate-200"
              >
                <p className="font-medium text-white">
                  {notification.notification_type} → {notification.recipient_role}
                </p>
                <p className="mt-1 text-xs text-slate-400">
                  {formatDateTime(notification.delivered_at)} • {notification.status}
                </p>
              </div>
            ))}
            {reconciliations.map((reconciliation) => (
              <div
                key={`reconciliation-${reconciliation.id ?? reconciliation.created_at}`}
                className="rounded-2xl border border-white/10 bg-slate-950/60 p-3 text-sm text-slate-200"
              >
                <p className="font-medium text-white">Reconciliation • {reconciliation.status}</p>
                <p className="mt-1 text-xs text-slate-400">
                  {formatDateTime(reconciliation.created_at)}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function QualitySummaryPanel({
  qualitySummary,
  sourceSummary,
  freshnessSummary,
}: {
  qualitySummary: ResearchQualitySummary | null
  sourceSummary: Record<string, any> | null
  freshnessSummary: Record<string, any> | null
}) {
  const verificationNotes = normalizeStringList(qualitySummary?.verification_notes)
  const citationCoverage = formatCoverage(qualitySummary?.citation_coverage)
  const sourceDiversity = formatSourceDiversity(qualitySummary?.source_diversity)
  const uncoveredClaims =
    typeof qualitySummary?.uncovered_claims === 'number'
      ? qualitySummary.uncovered_claims
      : Array.isArray(qualitySummary?.uncovered_claims)
        ? qualitySummary.uncovered_claims.length
        : null

  if (!qualitySummary && !sourceSummary && !freshnessSummary) {
    return null
  }

  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs font-semibold uppercase tracking-[0.25em] text-slate-300">
          Quality summary
        </p>
        {typeof qualitySummary?.strict_live_analysis_checks_passed === 'boolean' && (
          <span
            className={cn(
              'rounded-full border px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.2em]',
              qualitySummary.strict_live_analysis_checks_passed
                ? 'border-emerald-400/20 bg-emerald-400/10 text-emerald-100'
                : 'border-amber-400/20 bg-amber-400/10 text-amber-100',
            )}
          >
            {qualitySummary.strict_live_analysis_checks_passed ? 'Strict checks passed' : 'Needs review'}
          </span>
        )}
      </div>

      <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-200">
        {citationCoverage && (
          <span className="rounded-full border border-white/10 bg-white/5 px-2 py-1">
            Citation coverage: {citationCoverage}
          </span>
        )}
        {typeof uncoveredClaims === 'number' && (
          <span
            className={cn(
              'rounded-full border px-2 py-1',
              uncoveredClaims === 0
                ? 'border-emerald-400/20 bg-emerald-400/10 text-emerald-100'
                : 'border-amber-400/20 bg-amber-400/10 text-amber-100',
            )}
          >
            Uncovered claims: {uncoveredClaims}
          </span>
        )}
        {sourceDiversity && (
          <span className="rounded-full border border-white/10 bg-white/5 px-2 py-1">
            {sourceDiversity}
          </span>
        )}
        {typeof sourceSummary?.total_sources === 'number' && (
          <span className="rounded-full border border-white/10 bg-white/5 px-2 py-1">
            Sources: {sourceSummary.total_sources}
          </span>
        )}
        {typeof sourceSummary?.fresh_sources === 'number' && (
          <span className="rounded-full border border-white/10 bg-white/5 px-2 py-1">
            Fresh: {sourceSummary.fresh_sources}
          </span>
        )}
        {typeof sourceSummary?.academic_or_primary_sources === 'number' && (
          <span className="rounded-full border border-white/10 bg-white/5 px-2 py-1">
            Primary/Academic: {sourceSummary.academic_or_primary_sources}
          </span>
        )}
        {freshnessSummary?.required && (
          <span
            className={cn(
              'rounded-full border px-2 py-1',
              freshnessSummary.requirements_met
                ? 'border-emerald-400/20 bg-emerald-400/10 text-emerald-100'
                : 'border-amber-400/20 bg-amber-400/10 text-amber-100',
            )}
          >
            Freshness {freshnessSummary.requirements_met ? 'met' : 'warning'}
          </span>
        )}
      </div>

      {verificationNotes.length > 0 && (
        <ul className="mt-3 space-y-2 text-sm text-slate-200">
          {verificationNotes.map((note) => (
            <li key={note} className="rounded-xl border border-white/10 bg-slate-950/40 px-3 py-2">
              {note}
            </li>
          ))}
        </ul>
      )}

      {Array.isArray(freshnessSummary?.issues) && freshnessSummary.issues.length > 0 && (
        <ul className="mt-3 space-y-2 text-sm text-amber-100">
          {freshnessSummary.issues.map((issue: string) => (
            <li key={issue} className="rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2">
              {issue}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function ClaimCards({
  claims,
  citationLookup,
}: {
  claims: ResearchClaim[]
  citationLookup: Map<string, ResearchSourceCard>
}) {
  if (claims.length === 0) {
    return null
  }

  return (
    <div className="mt-4 space-y-3">
      <p className="text-xs font-semibold uppercase tracking-[0.25em] text-emerald-200/80">
        Claim grounding
      </p>
      <div className="space-y-3">
        {claims.map((claim, index) => {
          const citationRefs = [
            ...(claim.supporting_citation_ids ?? []),
            ...((claim.supporting_citations ?? []).filter(
              (item, refIndex, source) => source.indexOf(item) === refIndex,
            )),
          ]

          return (
            <div
              key={claim.claim_id || `${claim.claim}-${index}`}
              className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-emerald-50"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <p className="flex-1 font-medium text-white">{claim.claim}</p>
                {claim.confidence && (
                  <span className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.2em] text-emerald-100">
                    {claim.confidence}
                  </span>
                )}
              </div>

              {citationRefs.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {citationRefs.map((reference) => {
                    const linkedCitation = citationLookup.get(reference)
                    const citationId = linkedCitation ? getCitationId(linkedCitation) : null

                    if (linkedCitation && citationId) {
                      return (
                        <a
                          key={`${claim.claim}-${reference}`}
                          href={`#${citationAnchorId(citationId)}`}
                          className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.2em] text-emerald-100 transition hover:bg-emerald-400/20"
                          title={linkedCitation.title}
                        >
                          {citationId}
                        </a>
                      )
                    }

                    return (
                      <span
                        key={`${claim.claim}-${reference}`}
                        className="rounded-full border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-emerald-50/90"
                      >
                        {reference}
                      </span>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

const markdownComponents: Components = {
  a: ({ href, children, ...props }) => {
    const isInlineCitation = typeof href === 'string' && href.startsWith('#citation-')

    return (
      <a
        {...props}
        href={href}
        target={isInlineCitation ? undefined : '_blank'}
        rel={isInlineCitation ? undefined : 'noreferrer'}
        className={cn(
          isInlineCitation &&
            'rounded-full border border-emerald-400/20 bg-emerald-400/10 px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-emerald-100 no-underline transition hover:bg-emerald-400/20',
        )}
      >
        {children}
      </a>
    )
  },
}

export function ResearchRunDetailView({ researchRunId }: { researchRunId: string }) {
  const queryClient = useQueryClient()
  const [activeNodeId, setActiveNodeId] = useState<string | null>(null)
  const [controlAction, setControlAction] = useState<'pause' | 'resume' | 'cancel' | null>(null)
  const [controlError, setControlError] = useState<string | null>(null)
  const getActivePollingInterval = () => {
    const status = queryClient.getQueryData<ResearchRunResponse>(['research-run', researchRunId])?.status
    return status && TERMINAL_RUN_STATUSES.has(status) ? false : 2000
  }

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

  const selectedPaymentId = selectedNode?.payment_id ?? null
  const relevantPaymentIds = [
    ...new Set(
      [
        selectedPaymentId,
        waitingNode?.payment_id,
        waitingTaskQuery.data?.verification_data?.payment_id,
      ].filter(
        (paymentId): paymentId is string =>
          typeof paymentId === 'string' && paymentId.length > 0,
      ),
    ),
  ]
  const paymentDetailQuery = useQuery({
    queryKey: ['payment', selectedPaymentId],
    queryFn: () => getPayment(selectedPaymentId as string),
    enabled: Boolean(selectedPaymentId),
    retry: false,
    refetchInterval: researchRunQuery.data?.status && TERMINAL_RUN_STATUSES.has(researchRunQuery.data.status) ? false : 2000,
    refetchIntervalInBackground: true,
  })
  const paymentEventsQuery = useQuery({
    queryKey: ['payment', selectedPaymentId, 'events'],
    queryFn: () => getPaymentEvents(selectedPaymentId as string),
    enabled: Boolean(selectedPaymentId),
    retry: false,
    refetchInterval: researchRunQuery.data?.status && TERMINAL_RUN_STATUSES.has(researchRunQuery.data.status) ? false : 2000,
    refetchIntervalInBackground: true,
  })

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
      if (action === 'pause') {
        await pauseResearchRun(researchRunId)
      } else if (action === 'resume') {
        await resumeResearchRun(researchRunId)
      } else {
        await cancelResearchRun(researchRunId)
      }

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
  const fallbackRunPayload = getRunPayload(researchRun)
  const reportData: ResearchRunReportResponse | null = reportQuery.data ?? null
  const evidenceGraphData: ResearchRunEvidenceGraphResponse | null = evidenceGraphQuery.data ?? null
  const reportPackData: ResearchRunReportPackResponse | null = reportPackQuery.data ?? null
  const verificationDecisions: ResearchRunVerificationDecisionResponse[] =
    verificationDecisionsQuery.data ?? []
  const swarmHandoffs: ResearchRunSwarmHandoffResponse[] = swarmHandoffsQuery.data ?? []
  const policyEvaluations: ResearchRunPolicyEvaluationResponse[] = policyEvaluationsQuery.data ?? []
  const reportPayload: Record<string, any> | null =
    reportData && typeof reportData === 'object'
      ? (reportData as unknown as Record<string, any>)
      : reportPackData && typeof reportPackData === 'object'
        ? (reportPackData as unknown as Record<string, any>)
        : fallbackRunPayload
  const evidencePayload: ResearchRunEvidenceResponse | null = evidenceQuery.data ?? null
  const claimTargets = Array.isArray(evidencePayload?.claim_targets) ? evidencePayload.claim_targets : []
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
    ? reportPayload?.limitations.filter((item): item is string => typeof item === 'string')
    : []
  const freshnessSummary = evidencePayload?.freshness_summary ??
    (reportPayload && typeof reportPayload.freshness_summary === 'object'
      ? (reportPayload.freshness_summary as Record<string, any>)
      : null)
  const sourceSummary = evidencePayload?.source_summary ??
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
      if (citationId) {
        lookup.set(citationId, source)
      }
      lookup.set(source.title, source)
    }

    return lookup
  })()
  const linkedHeadline = (() => {
    if (!headline) {
      return null
    }

    const citationIds = citedSources
      .map((source) => getCitationId(source))
      .filter((citationId): citationId is string => Boolean(citationId))

    return citationIds.length > 0 ? linkInlineCitations(headline, citationIds) : headline
  })()
  const selectedNodeAttempts = [...(selectedNode?.attempts ?? [])].sort(
    (left, right) => right.attempt_number - left.attempt_number,
  )
  const selectedNodeVerificationDecisions = verificationDecisions.filter(
    (item) => item.node_id === selectedNode?.node_id,
  )
  const selectedNodeSwarmHandoffs = swarmHandoffs.filter((item) => item.node_id === selectedNode?.node_id)
  const selectedNodePolicyEvaluations = policyEvaluations.filter(
    (item) => item.node_id === selectedNode?.node_id,
  )
  const recentVerificationDecisions = [...verificationDecisions].slice(-4).reverse()
  const recentSwarmHandoffs = [...swarmHandoffs].slice(-6).reverse()
  const recentPolicyEvaluations = [...policyEvaluations].slice(-4).reverse()
  const canPause = researchRun.status === 'running'
  const canResume = researchRun.status === 'paused'
  const canCancel = !TERMINAL_RUN_STATUSES.has(researchRun.status)

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
                <div className="flex flex-wrap items-center justify-end gap-2">
                  <ResearchRunStatusBadge status={researchRun.status} />
                  {canPause && (
                    <Button
                      type="button"
                      variant="outline"
                      disabled={controlAction !== null}
                      onClick={() => handleRunControl('pause')}
                      className="border-white/15 bg-white/5 text-white hover:bg-white/10 hover:text-white"
                    >
                      {controlAction === 'pause' ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      ) : (
                        <Pause className="mr-2 h-4 w-4" />
                      )}
                      Pause
                    </Button>
                  )}
                  {canResume && (
                    <Button
                      type="button"
                      variant="outline"
                      disabled={controlAction !== null}
                      onClick={() => handleRunControl('resume')}
                      className="border-emerald-400/20 bg-emerald-400/10 text-emerald-100 hover:bg-emerald-400/20 hover:text-emerald-50"
                    >
                      {controlAction === 'resume' ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      ) : (
                        <Play className="mr-2 h-4 w-4" />
                      )}
                      Resume
                    </Button>
                  )}
                  {canCancel && (
                    <Button
                      type="button"
                      variant="outline"
                      disabled={controlAction !== null}
                      onClick={() => handleRunControl('cancel')}
                      className="border-rose-500/30 bg-rose-500/10 text-rose-100 hover:bg-rose-500/20 hover:text-rose-50"
                    >
                      {controlAction === 'cancel' ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      ) : (
                        <Slash className="mr-2 h-4 w-4" />
                      )}
                      Cancel
                    </Button>
                  )}
                </div>
              </div>
            </CardHeader>

            <CardContent className="space-y-6">
              {controlError && (
                <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-100">
                  {controlError}
                </div>
              )}

              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
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
                  <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Requested mode</p>
                  <p className="mt-2 text-lg font-semibold capitalize text-white">
                    {formatMode(researchRun.research_mode)}
                  </p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Classified mode</p>
                  <p className="mt-2 text-lg font-semibold capitalize text-white">
                    {formatMode(researchRun.classified_mode)}
                  </p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Depth</p>
                  <p className="mt-2 text-lg font-semibold capitalize text-white">
                    {formatMode(researchRun.depth_mode)}
                  </p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Freshness</p>
                  <p className="mt-2 text-lg font-semibold text-white">
                    {researchRun.freshness_required ? 'Required' : 'Advisory'}
                  </p>
                </div>
              </div>

              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-2 2xl:grid-cols-4">
                <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Created</p>
                  <p className="mt-2 text-sm font-medium text-white">{formatDateTime(researchRun.created_at)}</p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Updated</p>
                  <p className="mt-2 text-sm font-medium text-white">{formatDateTime(researchRun.updated_at)}</p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Evidence rounds</p>
                  <p className="mt-2 text-sm font-medium text-white">
                    {(researchRun.rounds_completed.evidence_rounds ?? 0)}/
                    {researchRun.rounds_planned.evidence_rounds ?? 0}
                  </p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Critique rounds</p>
                  <p className="mt-2 text-sm font-medium text-white">
                    {(researchRun.rounds_completed.critique_rounds ?? 0)}/
                    {researchRun.rounds_planned.critique_rounds ?? 0}
                  </p>
                </div>
              </div>

              <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Workflow</p>
                <p className="mt-2 whitespace-pre-wrap break-words font-mono text-sm text-sky-100">
                  {researchRun.workflow}
                </p>
                <p className="mt-3 text-xs text-slate-400">Run ID: {researchRun.id}</p>
              </div>

              <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Source requirements</p>
                <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-300">
                  <span className="rounded-full border border-white/10 bg-white/5 px-2 py-1">
                    Total: {researchRun.source_requirements.total_sources ?? 0}
                  </span>
                  {(researchRun.source_requirements.min_academic_or_primary ?? 0) > 0 && (
                    <span className="rounded-full border border-white/10 bg-white/5 px-2 py-1">
                      Academic/Primary: {researchRun.source_requirements.min_academic_or_primary}
                    </span>
                  )}
                  {(researchRun.source_requirements.min_fresh_sources ?? 0) > 0 && (
                    <span className="rounded-full border border-white/10 bg-white/5 px-2 py-1">
                      Fresh: {researchRun.source_requirements.min_fresh_sources} in{' '}
                      {researchRun.source_requirements.freshness_window_days}d
                    </span>
                  )}
                </div>
              </div>

              <div className="grid gap-3 xl:grid-cols-[0.95fr_1.05fr]">
                <div className="rounded-2xl border border-amber-400/20 bg-amber-400/10 p-4">
                  <div className="flex items-center gap-2 text-amber-100">
                    <ShieldCheck className="h-4 w-4" />
                    <p className="text-sm font-semibold uppercase tracking-[0.3em]">
                      Adaptive controls
                    </p>
                  </div>
                  <div className="mt-4 grid gap-3 sm:grid-cols-2">
                    <div className="rounded-2xl border border-white/10 bg-black/10 p-3">
                      <p className="text-[11px] uppercase tracking-[0.25em] text-amber-200/80">
                        Strict mode
                      </p>
                      <p className="mt-2 text-sm font-medium text-white">
                        {researchRun.policy.strict_mode ? 'Enabled' : 'Disabled'}
                      </p>
                    </div>
                    <div className="rounded-2xl border border-white/10 bg-black/10 p-3">
                      <p className="text-[11px] uppercase tracking-[0.25em] text-amber-200/80">
                        Risk level
                      </p>
                      <p className="mt-2 text-sm font-medium capitalize text-white">
                        {formatMode(researchRun.policy.risk_level)}
                      </p>
                    </div>
                    <div className="rounded-2xl border border-white/10 bg-black/10 p-3">
                      <p className="text-[11px] uppercase tracking-[0.25em] text-amber-200/80">
                        Quorum policy
                      </p>
                      <p className="mt-2 text-sm font-medium capitalize text-white">
                        {formatMode(researchRun.policy.quorum_policy)}
                      </p>
                    </div>
                    <div className="rounded-2xl border border-white/10 bg-black/10 p-3">
                      <p className="text-[11px] uppercase tracking-[0.25em] text-amber-200/80">
                        Max attempts
                      </p>
                      <p className="mt-2 text-sm font-medium text-white">
                        {researchRun.policy.max_node_attempts}
                      </p>
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
                </div>

                <div className="rounded-2xl border border-fuchsia-400/20 bg-fuchsia-400/10 p-4">
                  <div className="flex items-center gap-2 text-fuchsia-100">
                    <DatabaseZap className="h-4 w-4" />
                    <p className="text-sm font-semibold uppercase tracking-[0.3em]">
                      Persisted trace summary
                    </p>
                  </div>
                  <div className="mt-4 grid gap-3 sm:grid-cols-2">
                    <div className="rounded-2xl border border-white/10 bg-black/10 p-3">
                      <p className="text-[11px] uppercase tracking-[0.25em] text-fuchsia-200/80">
                        Verification decisions
                      </p>
                      <p className="mt-2 text-sm font-medium text-white">
                        {researchRun.trace_summary.verification_decision_count}
                      </p>
                    </div>
                    <div className="rounded-2xl border border-white/10 bg-black/10 p-3">
                      <p className="text-[11px] uppercase tracking-[0.25em] text-fuchsia-200/80">
                        Swarm handoffs
                      </p>
                      <p className="mt-2 text-sm font-medium text-white">
                        {researchRun.trace_summary.swarm_handoff_count}
                      </p>
                    </div>
                    <div className="rounded-2xl border border-white/10 bg-black/10 p-3">
                      <p className="text-[11px] uppercase tracking-[0.25em] text-fuchsia-200/80">
                        Policy evaluations
                      </p>
                      <p className="mt-2 text-sm font-medium text-white">
                        {researchRun.trace_summary.policy_evaluation_count}
                      </p>
                    </div>
                    <div className="rounded-2xl border border-white/10 bg-black/10 p-3">
                      <p className="text-[11px] uppercase tracking-[0.25em] text-fuchsia-200/80">
                        Open dissent
                      </p>
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
                </div>
              </div>

              {(evidenceGraphData || reportPackData) && (
                <div className="rounded-2xl border border-violet-400/20 bg-violet-400/10 p-4">
                  <div className="flex items-center gap-2 text-violet-100">
                    <DatabaseZap className="h-4 w-4" />
                    <p className="text-sm font-semibold uppercase tracking-[0.3em]">
                      Graph and report pack
                    </p>
                  </div>
                  <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                    <div className="rounded-2xl border border-white/10 bg-black/10 p-3">
                      <p className="text-[11px] uppercase tracking-[0.25em] text-violet-200/80">
                        Artifacts
                      </p>
                      <p className="mt-2 text-sm font-medium text-white">
                        {evidenceGraphData?.summary.artifact_count ?? 0}
                      </p>
                    </div>
                    <div className="rounded-2xl border border-white/10 bg-black/10 p-3">
                      <p className="text-[11px] uppercase tracking-[0.25em] text-violet-200/80">
                        Claims
                      </p>
                      <p className="mt-2 text-sm font-medium text-white">
                        {evidenceGraphData?.summary.claim_count ?? reportPackData?.claims.length ?? 0}
                      </p>
                    </div>
                    <div className="rounded-2xl border border-white/10 bg-black/10 p-3">
                      <p className="text-[11px] uppercase tracking-[0.25em] text-violet-200/80">
                        Cited artifacts
                      </p>
                      <p className="mt-2 text-sm font-medium text-white">
                        {evidenceGraphData?.summary.cited_artifact_count ?? reportPackData?.citations.length ?? 0}
                      </p>
                    </div>
                    <div className="rounded-2xl border border-white/10 bg-black/10 p-3">
                      <p className="text-[11px] uppercase tracking-[0.25em] text-violet-200/80">
                        Evidence links
                      </p>
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
                </div>
              )}

              {(recentVerificationDecisions.length > 0 ||
                recentSwarmHandoffs.length > 0 ||
                recentPolicyEvaluations.length > 0) && (
                <div className="rounded-2xl border border-rose-400/20 bg-rose-400/10 p-4">
                  <div className="flex items-center gap-2 text-rose-100">
                    <Activity className="h-4 w-4" />
                    <p className="text-sm font-semibold uppercase tracking-[0.3em]">Swarm trace</p>
                  </div>

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
                              {formatMode(decision.node_id)} · {formatMode(decision.decision)}
                            </p>
                            <span className="text-xs text-rose-100/70">
                              {formatDateTime(decision.created_at)}
                            </span>
                          </div>
                          <p className="mt-2 text-xs text-rose-100/80">
                            {[decision.agent_id, decision.quorum_policy, decision.decision_source]
                              .filter((value): value is string => typeof value === 'string' && value.length > 0)
                              .map((value) => formatMode(value))
                              .join(' • ')}
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
                            <p className="font-medium text-white">
                              {formatMode(handoff.handoff_type)}
                            </p>
                            <span className="text-xs text-rose-100/70">
                              Round {handoff.round_number}
                            </span>
                          </div>
                          <p className="mt-2 text-xs text-rose-100/80">
                            {[handoff.from_agent_id, handoff.to_agent_id, handoff.node_id]
                              .filter((value): value is string => typeof value === 'string' && value.length > 0)
                              .map((value) => formatMode(value))
                              .join(' → ')}
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
                            <p className="font-medium text-white">
                              {formatMode(evaluation.evaluation_type)}
                            </p>
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
                </div>
              )}

              {(evidencePayload?.rewritten_research_brief ||
                claimTargets.length > 0 ||
                (evidencePayload?.search_lanes_used?.length ?? 0) > 0) && (
                <div className="rounded-2xl border border-cyan-400/20 bg-cyan-400/10 p-4">
                  <div className="flex items-center gap-2 text-cyan-100">
                    <Activity className="h-4 w-4" />
                    <p className="text-sm font-semibold uppercase tracking-[0.3em]">Evidence view</p>
                  </div>

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
                              .filter((value): value is string => typeof value === 'string' && value.length > 0)
                              .join(' • ') || 'Target'}
                          </p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {researchRun.error?.includes('insufficient_fresh_evidence') && (
                <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-100">
                  The run stopped because it could not collect enough fresh evidence for a time-sensitive query.
                </div>
              )}

              {!(headline || claims.length > 0 || citedSources.length > 0) &&
                (qualitySummary || sourceSummary || freshnessSummary) && (
                  <QualitySummaryPanel
                    qualitySummary={qualitySummary}
                    sourceSummary={sourceSummary}
                    freshnessSummary={freshnessSummary}
                  />
                )}

              {(headline || claims.length > 0 || citedSources.length > 0) && (
                <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/10 p-5">
                  <div className="flex items-center gap-2 text-emerald-200">
                    <ShieldCheck className="h-4 w-4" />
                    <p className="text-sm font-semibold uppercase tracking-[0.3em]">Final result</p>
                  </div>
                  <div className="mt-4">
                    <QualitySummaryPanel
                      qualitySummary={qualitySummary}
                      sourceSummary={sourceSummary}
                      freshnessSummary={freshnessSummary}
                    />
                  </div>
                  {headline && (
                    <div className="prose prose-invert prose-sm mt-4 max-w-none prose-headings:text-white prose-p:text-slate-100 prose-strong:text-white prose-a:text-sky-200 prose-li:text-slate-100 prose-blockquote:border-sky-400/30 prose-blockquote:text-slate-200 prose-code:text-emerald-100">
                      <ReactMarkdown components={markdownComponents}>
                        {linkedHeadline}
                      </ReactMarkdown>
                    </div>
                  )}
                  <ClaimCards claims={claims} citationLookup={citationLookup} />
                  {criticFindings.length > 0 && (
                    <div className="mt-4 space-y-2">
                      <p className="text-xs font-semibold uppercase tracking-[0.25em] text-emerald-200/80">
                        Critic findings incorporated
                      </p>
                      {criticFindings.map((finding) => (
                        <div
                          key={`${finding.issue}-${finding.recommendation}`}
                          className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-emerald-50"
                        >
                          <span className="font-medium">{finding.issue}</span>
                          {finding.recommendation && (
                            <div className="mt-2">
                              <ExpandableText
                                content={finding.recommendation}
                                collapsedHeight="max-h-24"
                                buttonLabel="Expand finding"
                                className="text-emerald-50/90"
                              />
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  {limitations.length > 0 && (
                    <div className="mt-4 space-y-2">
                      <p className="text-xs font-semibold uppercase tracking-[0.25em] text-emerald-200/80">
                        Limitations
                      </p>
                      <ul className="space-y-2 text-sm text-emerald-50">
                        {limitations.map((limitation) => (
                          <li key={limitation} className="rounded-xl border border-white/10 bg-white/5 px-3 py-2">
                            {limitation}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {citedSources.length > 0 && (
                    <div className="mt-4 space-y-2">
                      <p className="text-xs font-semibold uppercase tracking-[0.25em] text-emerald-200/80">
                        Cited sources
                      </p>
                      <div className="grid gap-2">
                        {citedSources.map((citation) => {
                          const citationId = getCitationId(citation)

                          return (
                          <a
                            key={citationSourceKey(citation)}
                            id={citationId ? citationAnchorId(citationId) : undefined}
                            href={citation.url}
                            target="_blank"
                            rel="noreferrer"
                            className="rounded-xl border border-white/10 bg-white/5 px-3 py-3 text-sm text-emerald-50 transition hover:bg-white/10"
                          >
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <div className="flex flex-wrap items-center gap-2">
                                  {citationId && (
                                    <span className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.2em] text-emerald-100">
                                      {citationId}
                                    </span>
                                  )}
                                  <p className="font-medium text-white">{citation.title}</p>
                                </div>
                                <p className="mt-1 text-xs text-emerald-100/80">
                                  {[citation.publisher, citation.source_type ? formatMode(citation.source_type) : null, citation.published_at ? formatDateTime(citation.published_at) : null]
                                    .filter(Boolean)
                                    .join(' • ')}
                                </p>
                              </div>
                              <ExternalLink className="mt-0.5 h-4 w-4 shrink-0 text-emerald-200" />
                            </div>
                          </a>
                          )
                        })}
                      </div>
                    </div>
                  )}
                </div>
              )}

              <SourceCards sources={runSources} />
              <SourceCards sources={filteredSources} title="Filtered or downranked sources" />

              <div className="space-y-3">
                <p className="text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Debug payloads</p>
                <DebugSection title="Research run evidence" value={evidenceQuery.data} />
                <DebugSection title="Research run report" value={reportQuery.data} />
                <DebugSection title="Research run evidence graph" value={evidenceGraphQuery.data} />
                <DebugSection title="Research run report pack" value={reportPackQuery.data} />
                <DebugSection
                  title="Research run verification decisions"
                  value={verificationDecisionsQuery.data}
                />
                <DebugSection title="Research run swarm handoffs" value={swarmHandoffsQuery.data} />
                <DebugSection
                  title="Research run policy evaluations"
                  value={policyEvaluationsQuery.data}
                />
                <DebugSection title="Research run result" value={researchRun.result} />
              </div>
            </CardContent>
          </Card>

          <Card className="rounded-[28px] border border-white/15 bg-slate-900/75 text-slate-100 backdrop-blur-xl">
            <CardHeader className="space-y-3">
              <CardTitle className="text-2xl text-white">Pipeline rail</CardTitle>
              <CardDescription className="text-slate-300">
                Each node maps to one persisted task attempt while the run adds internal scout, critic, and revision loops behind the scenes.
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
                  <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                    <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Rounds completed</p>
                    <p className="mt-2 text-sm font-medium text-white">
                      {(selectedNode.result && typeof selectedNode.result === 'object'
                        ? (selectedNode.result as Record<string, any>).rounds_completed?.evidence_rounds ?? 0
                        : 0)}
                      {' / '}
                      {(selectedNode.result && typeof selectedNode.result === 'object'
                        ? (selectedNode.result as Record<string, any>).rounds_completed?.critique_rounds ?? 0
                        : 0)}
                    </p>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                    <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Sources linked</p>
                    <p className="mt-2 text-sm font-medium text-white">
                      {selectedNode.result && typeof selectedNode.result === 'object' && Array.isArray((selectedNode.result as Record<string, any>).sources)
                        ? (selectedNode.result as Record<string, any>).sources.length
                        : 0}
                    </p>
                  </div>
                </div>

                <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <p className="text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">
                    Description
                  </p>
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
                        Loading payment activity…
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
                        <p className="text-xs uppercase tracking-[0.25em] text-slate-400">
                          Verification decisions
                        </p>
                        <div className="mt-3 space-y-2">
                          {selectedNodeVerificationDecisions.map((decision) => (
                            <div
                              key={decision.id}
                              className="rounded-2xl border border-white/10 bg-slate-950/60 p-3"
                            >
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <p className="text-sm font-medium text-white">
                                  {formatMode(decision.decision)}
                                </p>
                                <span className="text-xs text-slate-400">
                                  {formatDateTime(decision.created_at)}
                                </span>
                              </div>
                              <p className="mt-2 text-xs text-slate-300">
                                {[decision.agent_id, decision.quorum_policy, decision.decision_source]
                                  .filter((value): value is string => typeof value === 'string' && value.length > 0)
                                  .map((value) => formatMode(value))
                                  .join(' • ')}
                              </p>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {selectedNodeSwarmHandoffs.length > 0 && (
                      <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                        <p className="text-xs uppercase tracking-[0.25em] text-slate-400">
                          Swarm handoffs
                        </p>
                        <div className="mt-3 space-y-2">
                          {selectedNodeSwarmHandoffs.map((handoff) => (
                            <div
                              key={handoff.id}
                              className="rounded-2xl border border-white/10 bg-slate-950/60 p-3"
                            >
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <p className="text-sm font-medium text-white">
                                  {formatMode(handoff.handoff_type)}
                                </p>
                                <span className="text-xs text-slate-400">
                                  Round {handoff.round_number}
                                </span>
                              </div>
                              <p className="mt-2 text-xs text-slate-300">
                                {[handoff.from_agent_id, handoff.to_agent_id]
                                  .filter((value): value is string => typeof value === 'string' && value.length > 0)
                                  .join(' → ')}
                              </p>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {selectedNodePolicyEvaluations.length > 0 && (
                      <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                        <p className="text-xs uppercase tracking-[0.25em] text-slate-400">
                          Policy evaluations
                        </p>
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
                        <DebugSection title="Attempt result" value={attempt.result} />
                      </div>
                    </div>
                  ))}
                </div>
                <DebugSection title="Node result" value={selectedNode.result} />
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
