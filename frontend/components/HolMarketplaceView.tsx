'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Search, Globe2, Network, Cpu } from 'lucide-react'

import { type HolAgentRecord, searchHolAgents } from '@/lib/api'

export function HolMarketplaceView() {
  const [searchQuery, setSearchQuery] = useState('')

  const { data, isLoading, isError, error, refetch } = useQuery<
    { agents: HolAgentRecord[]; query: string },
    Error
  >({
    queryKey: ['hol-agents', searchQuery],
    queryFn: () => searchHolAgents(searchQuery),
    staleTime: 30_000,
  })

  const agents = data?.agents ?? []
  const errorMessage = isError ? error?.message ?? 'Failed to load HOL agents' : null

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-white">HOL Registry</h2>
          <p className="mt-1 text-sm text-slate-400">
            Discover external agents from the Hashgraph Online Universal Agentic Registry.
          </p>
        </div>
      </div>

      <div className="space-y-4">
        <div className="relative">
          <Search className="absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            placeholder="Search HOL agents by UAID, name, capabilities..."
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            onBlur={() => void refetch()}
            className="w-full rounded-2xl border border-white/10 bg-slate-900/40 px-12 py-3 text-sm text-white placeholder:text-slate-500 focus:border-sky-400/50 focus:outline-none focus:ring-1 focus:ring-sky-400/30"
          />
        </div>
      </div>

      {isLoading && (
        <div className="rounded-2xl border border-white/15 bg-slate-900/50 p-6 text-center text-slate-400">
          Searching HOL agents...
        </div>
      )}

      {errorMessage && !isLoading && (
        <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-6 text-center text-red-300">
          {errorMessage}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {!isLoading &&
          !errorMessage &&
          agents.map((agent) => {
            const hasTransports = Array.isArray(agent.transports) && agent.transports.length > 0
            const Icon = hasTransports ? Network : Cpu
            const price = agent.pricing?.rate
            const currency = agent.pricing?.currency ?? 'HBAR'
            const rateType = agent.pricing?.rate_type?.replace('_', ' ') ?? 'per task'

            return (
              <div
                key={agent.uaid}
                className="group overflow-hidden rounded-2xl border border-white/15 bg-slate-900/50 backdrop-blur-sm transition hover:border-sky-400/50 hover:bg-slate-900/70"
              >
                <div className="p-6">
                  <div className="flex items-start gap-4">
                    <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-sky-500/20 via-indigo-500/20 to-purple-600/20 text-sky-400 ring-1 ring-white/10">
                      <Icon className="h-7 w-7" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h3 className="truncate text-lg font-semibold text-white">{agent.name}</h3>
                      <p className="mt-1 truncate font-mono text-xs text-slate-400">{agent.uaid}</p>
                      {agent.registry && (
                        <div className="mt-1 inline-flex items-center gap-1 rounded-full bg-slate-800/60 px-2 py-0.5 text-[11px] text-slate-200">
                          <Globe2 className="h-3 w-3 text-sky-400" />
                          {agent.registry}
                        </div>
                      )}
                    </div>
                  </div>

                  {agent.description && (
                    <p className="mt-4 line-clamp-3 text-sm leading-relaxed text-slate-300">
                      {agent.description}
                    </p>
                  )}

                  {hasTransports && (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {agent.transports.map((t) => (
                        <span
                          key={t}
                          className="rounded-full bg-slate-800/60 px-2 py-0.5 text-[11px] uppercase tracking-wide text-slate-200"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  )}

                  <div className="mt-5 flex items-center justify-between border-t border-white/10 pt-4 text-sm">
                    <div className="text-slate-300">
                      <div className="text-xs uppercase tracking-[0.15em] text-slate-500">
                        Pricing
                      </div>
                      <div className="mt-1 text-sm font-semibold text-white">
                        {typeof price === 'number' ? `${price.toFixed(2)} ${currency}` : '—'}
                      </div>
                      <div className="text-xs text-slate-500">{rateType}</div>
                    </div>
                    <div className="flex flex-col items-end gap-2">
                      <button
                        type="button"
                        className="rounded-full bg-sky-500 px-3 py-1.5 text-xs font-medium text-white shadow-sm shadow-sky-500/30 transition hover:bg-sky-400"
                        disabled
                        title="Launching tasks with a specific HOL agent will be wired into createTask."
                      >
                        Launch research (soon)
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
      </div>

      {!isLoading && !errorMessage && agents.length === 0 && (
        <div className="rounded-2xl border border-white/15 bg-slate-900/50 p-12 text-center">
          <p className="text-slate-400">No HOL agents found for this query yet.</p>
          <p className="mt-2 text-sm text-slate-500">
            Try a broader search term, or ensure REGISTRY_BROKER_API_KEY is configured on the
            backend.
          </p>
        </div>
      )}
    </div>
  )
}

