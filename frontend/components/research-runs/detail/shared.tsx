'use client'

import { useMemo, useState } from 'react'
import {
  ChevronDown,
  ExternalLink,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'

import { Button } from '@/components/ui/button'
import type {
  PaymentDetailResponse,
  PaymentEventsResponse,
  ResearchClaim,
  ResearchCriticFinding,
  ResearchRunNodeResponse,
  ResearchRunNodeStatus,
  ResearchRunResponse,
  ResearchQualitySummary,
  ResearchSourceCard,
} from '@/lib/api'
import { cn } from '@/lib/utils'

export const TERMINAL_RUN_STATUSES = new Set(['completed', 'failed', 'cancelled'])

export function formatDateTime(value?: string | null) {
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

export function formatBudget(value?: number | null) {
  if (typeof value !== 'number') {
    return 'Unspecified'
  }

  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
  }).format(value)
}

export function stringifyValue(value: unknown) {
  if (value == null) return null
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}

export function isRecord(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

export function getRunHeadline(run: ResearchRunResponse): string | null {
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

export function getRunClaims(run: ResearchRunResponse): ResearchClaim[] {
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

export function getRunSources(run: ResearchRunResponse): ResearchSourceCard[] {
  const payload = run.result && typeof run.result === 'object' ? run.result : null
  if (!payload || !Array.isArray(payload.sources)) {
    return []
  }
  return payload.sources.filter(
    (item: unknown): item is ResearchSourceCard =>
      Boolean(item) && typeof item === 'object' && typeof (item as ResearchSourceCard).title === 'string',
  )
}

export function getCriticFindings(run: ResearchRunResponse): ResearchCriticFinding[] {
  const payload = run.result && typeof run.result === 'object' ? run.result : null
  if (!payload || !Array.isArray(payload.critic_findings)) {
    return []
  }
  return payload.critic_findings.filter(
    (item: unknown): item is ResearchCriticFinding =>
      Boolean(item) && typeof item === 'object' && typeof (item as ResearchCriticFinding).issue === 'string',
  )
}

export function getRunPayload(run: ResearchRunResponse): Record<string, any> | null {
  return run.result && typeof run.result === 'object' ? (run.result as Record<string, any>) : null
}

export function getRunQualitySummary(run: ResearchRunResponse): ResearchQualitySummary | null {
  const payload = getRunPayload(run)
  return isRecord(payload?.quality_summary) ? (payload.quality_summary as ResearchQualitySummary) : null
}

export function formatMode(value: string) {
  return value.replace(/_/g, ' ')
}

export function cleanDisplayText(value: string) {
  return value
    .replace(/\r/g, '')
    .replace(/(^|\n)#{1,6}\s*/g, '$1')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

export function normalizeStringList(value: unknown): string[] {
  if (typeof value === 'string') {
    return value.trim() ? [value] : []
  }

  if (!Array.isArray(value)) {
    return []
  }

  return value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
}

export function formatCoverage(value?: number | null) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return null
  }

  const normalized = value <= 1 ? value * 100 : value
  return `${Math.round(normalized)}%`
}

export function formatSourceDiversity(
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

  return parts.length > 0 ? parts.join(' \u00b7 ') : null
}

export function getCitationId(source: ResearchSourceCard) {
  return typeof source.citation_id === 'string' && source.citation_id.trim().length > 0
    ? source.citation_id.trim()
    : null
}

export function citationAnchorId(citationId: string) {
  return `citation-${citationId.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`
}

export function citationSourceKey(source: ResearchSourceCard) {
  return getCitationId(source) || source.url || source.title
}

export function dedupeSources(sources: ResearchSourceCard[]) {
  const seen = new Map<string, ResearchSourceCard>()

  for (const source of sources) {
    seen.set(citationSourceKey(source), source)
  }

  return [...seen.values()]
}

export function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

export function linkInlineCitations(markdown: string, citationIds: string[]) {
  return citationIds.reduce((current, citationId) => {
    const pattern = new RegExp(`\\[(${escapeRegExp(citationId)})\\](?!\\()`, 'g')
    return current.replace(pattern, `[$1](#${citationAnchorId(citationId)})`)
  }, markdown)
}

export function pickFocusNode(nodes: ResearchRunNodeResponse[]) {
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

export function ExpandableText({
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

export function DebugSection({ title, value }: { title: string; value: unknown }) {
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

export function JsonPreview({
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

export function SourceCards({
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

export function PaymentActivityPanel({
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
              ? ` \u00b7 ${payment.notification_summary.reconciliations} reconciliations`
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
                  {transition.action} \u00b7 {transition.state}
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
                  {notification.notification_type} \u2192 {notification.recipient_role}
                </p>
                <p className="mt-1 text-xs text-slate-400">
                  {formatDateTime(notification.delivered_at)} \u00b7 {notification.status}
                </p>
              </div>
            ))}
            {reconciliations.map((reconciliation) => (
              <div
                key={`reconciliation-${reconciliation.id ?? reconciliation.created_at}`}
                className="rounded-2xl border border-white/10 bg-slate-950/60 p-3 text-sm text-slate-200"
              >
                <p className="font-medium text-white">Reconciliation \u00b7 {reconciliation.status}</p>
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

export function QualitySummaryPanel({
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

export function ClaimCards({
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
                    const citId = linkedCitation ? getCitationId(linkedCitation) : null

                    if (linkedCitation && citId) {
                      return (
                        <a
                          key={`${claim.claim}-${reference}`}
                          href={`#${citationAnchorId(citId)}`}
                          className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.2em] text-emerald-100 transition hover:bg-emerald-400/20"
                          title={linkedCitation.title}
                        >
                          {citId}
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

export const markdownComponents: Components = {
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
