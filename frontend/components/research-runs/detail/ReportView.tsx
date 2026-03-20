'use client'

import { ExternalLink } from 'lucide-react'
import ReactMarkdown from 'react-markdown'

import type {
  ResearchClaim,
  ResearchCriticFinding,
  ResearchQualitySummary,
  ResearchSourceCard,
} from '@/lib/api'

import {
  citationAnchorId,
  ClaimCards,
  ExpandableText,
  formatDateTime,
  formatMode,
  getCitationId,
  citationSourceKey,
  createMarkdownComponents,
  QualityBanner,
} from './shared'

export function ReportView({
  linkedHeadline,
  claims,
  citedSources,
  citationLookup,
  criticFindings,
  limitations,
  qualitySummary,
  sourceSummary,
  freshnessSummary,
  qualityTier,
  qualityWarnings,
}: {
  linkedHeadline: string | null
  claims: ResearchClaim[]
  citedSources: ResearchSourceCard[]
  citationLookup: Map<string, ResearchSourceCard>
  criticFindings: ResearchCriticFinding[]
  limitations: string[]
  qualitySummary: ResearchQualitySummary | null
  sourceSummary: Record<string, any> | null
  freshnessSummary: Record<string, any> | null
  qualityTier?: string | null
  qualityWarnings: string[]
}) {
  return (
    <div className="space-y-4">
      <QualityBanner
        qualityTier={qualityTier}
        qualitySummary={qualitySummary}
        sourceSummary={sourceSummary}
        freshnessSummary={freshnessSummary}
        totalSources={citedSources.length}
      />

      {linkedHeadline && (
        <div className="prose prose-invert prose-sm max-w-none prose-headings:text-white prose-p:text-slate-100 prose-strong:text-white prose-a:text-sky-200 prose-li:text-slate-100 prose-blockquote:border-sky-400/30 prose-blockquote:text-slate-200 prose-code:text-emerald-100">
          <ReactMarkdown components={createMarkdownComponents(citationLookup)}>
            {linkedHeadline}
          </ReactMarkdown>
        </div>
      )}

      {citedSources.length > 0 && (
        <details id="cited-sources-details" className="rounded-2xl border border-white/10 bg-white/5 p-4">
          <summary className="cursor-pointer list-none text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">
            Cited sources ({citedSources.length})
          </summary>
          <div className="mt-3 grid gap-2">
            {citedSources.map((citation) => {
              const citationId = getCitationId(citation)

              return (
                <a
                  key={citationSourceKey(citation)}
                  id={citationId ? citationAnchorId(citationId) : undefined}
                  href={citation.url}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-xl border border-white/10 bg-white/5 px-3 py-3 text-sm text-slate-200 transition hover:bg-white/10"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        {citationId && (
                          <span className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-emerald-200/90">
                            {citationId}
                          </span>
                        )}
                        <p className="font-medium text-white">{citation.title}</p>
                      </div>
                      <p className="mt-1 text-xs text-slate-400">
                        {[
                          citation.publisher,
                          citation.source_type ? formatMode(citation.source_type) : null,
                          citation.published_at ? formatDateTime(citation.published_at) : null,
                        ]
                          .filter(Boolean)
                          .join(' \u00b7 ')}
                      </p>
                    </div>
                    <ExternalLink className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
                  </div>
                </a>
              )
            })}
          </div>
        </details>
      )}

      <ClaimCards claims={claims} citationLookup={citationLookup} />

      {criticFindings.length > 0 && (
        <details className="rounded-2xl border border-white/10 bg-white/5 p-4">
          <summary className="cursor-pointer list-none text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">
            Critic findings ({criticFindings.length})
          </summary>
          <div className="mt-3 space-y-2">
            {criticFindings.map((finding) => (
              <div
                key={`${finding.issue}-${finding.recommendation}`}
                className="rounded-xl border border-white/10 bg-slate-950/40 px-3 py-2 text-sm text-slate-200"
              >
                <span className="font-medium">{finding.issue}</span>
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
            ))}
          </div>
        </details>
      )}

      {limitations.length > 0 && (
        <details className="rounded-2xl border border-white/10 bg-white/5 p-4">
          <summary className="cursor-pointer list-none text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">
            Limitations ({limitations.length})
          </summary>
          <ul className="mt-3 space-y-2 text-sm text-slate-200">
            {limitations.map((limitation) => (
              <li key={limitation} className="rounded-xl border border-white/10 bg-slate-950/40 px-3 py-2">
                {limitation}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}
