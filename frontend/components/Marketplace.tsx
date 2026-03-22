'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  BarChart3,
  Bot,
  Brain,
  ChevronDown,
  Code,
  Database,
  FileText,
  Globe,
  MessageSquare,
  Search,
  Star,
  TrendingUp,
} from 'lucide-react'

import { AddAgentModal } from '@/components/AddAgentModal'
import { HolMarketplaceView } from '@/components/HolMarketplaceView'
import { HolRegisterBadge } from '@/components/HolRegisterBadge'
import { getAgents, registerAgentOnHol, type AgentRecord } from '@/lib/api'

type IconType = typeof Database

const typeToIcon: Record<string, IconType> = {
  data: Database,
  stats: BarChart3,
  nlp: MessageSquare,
  market: TrendingUp,
  report: FileText,
  ml: Brain,
  code: Code,
  web: Globe,
}

function resolveAgentTags(agent: AgentRecord): string[] {
  if (Array.isArray(agent.categories) && agent.categories.length > 0) {
    return agent.categories
  }

  if (Array.isArray(agent.capabilities) && agent.capabilities.length > 0) {
    return agent.capabilities
  }

  return []
}

const EMPTY_AGENTS: AgentRecord[] = []

function normalizeHolErrorMessage(value?: string | null): string | null {
  if (!value || !value.trim()) {
    return null
  }

  const message = value.trim()

  if (/insufficient_credits/i.test(message)) {
    const required = message.match(/requiredCredits=(\d+(?:\.\d+)?)/i)?.[1]
    const available = message.match(/availableCredits=(\d+(?:\.\d+)?)/i)?.[1]
    if (required && available) {
      return `HOL credits are insufficient (required ${required}, available ${available}). This is HOL Registry broker credit balance, not Synaptica app credits.`
    }
    return 'HOL credits are insufficient for registration. This is HOL Registry broker credit balance, not Synaptica app credits.'
  }

  if (/timed out|timeout/i.test(message)) {
    return 'HOL request timed out. Please retry.'
  }

  if (/502|bad gateway|upstream HOL registry error page/i.test(message)) {
    return 'HOL registry is temporarily unavailable (502). Please retry.'
  }

  if (message.length > 180) {
    return `${message.slice(0, 177)}...`
  }

  return message
}

export function Marketplace() {
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedCategory, setSelectedCategory] = useState('All')
  const [showAllTags, setShowAllTags] = useState(false)
  const [activeSource, setActiveSource] = useState<'local' | 'hol'>('local')
  const [registeringAgentId, setRegisteringAgentId] = useState<string | null>(null)
  const [holRegistrationErrors, setHolRegistrationErrors] = useState<Record<string, string>>({})

  const { data, isLoading, isError, error, refetch } = useQuery<AgentRecord[], Error>({
    queryKey: ['agents'],
    queryFn: getAgents,
    staleTime: 60_000,
  })

  const handleAgentAdded = useCallback(() => {
    void refetch()
    setSearchQuery('')
    setSelectedCategory('All')
    setHolRegistrationErrors({})
  }, [refetch])

  const handleRegisterOnHol = useCallback(
    async (agentId: string) => {
      setRegisteringAgentId(agentId)
      setHolRegistrationErrors((current) => {
        const next = { ...current }
        delete next[agentId]
        return next
      })

      try {
        await registerAgentOnHol({ agent_id: agentId, mode: 'register' })
        await refetch()
      } catch (err: any) {
        const message = normalizeHolErrorMessage(err?.message || 'Failed to register agent on HOL')
        if (message) {
          setHolRegistrationErrors((current) => ({ ...current, [agentId]: message }))
          window.setTimeout(() => {
            setHolRegistrationErrors((current) => {
              const next = { ...current }
              delete next[agentId]
              return next
            })
          }, 8000)
        }
      } finally {
        setRegisteringAgentId(null)
      }
    },
    [refetch]
  )

  useEffect(() => {
    if (activeSource !== 'local') {
      setHolRegistrationErrors({})
    }
  }, [activeSource])

  const agents = data ?? EMPTY_AGENTS
  const errorMessage = isError ? error?.message ?? 'Failed to load agents' : null

  const categories = useMemo(() => {
    const tagSet = new Set<string>()
    agents.forEach((agent) => {
      resolveAgentTags(agent).forEach((tag) => tagSet.add(tag))
    })
    return ['All', ...Array.from(tagSet).sort((a, b) => a.localeCompare(b))]
  }, [agents])

  const filteredAgents = useMemo(() => {
    const query = searchQuery.trim().toLowerCase()
    return agents.filter((agent) => {
      const tags = resolveAgentTags(agent)
      const matchesCategory = selectedCategory === 'All' || tags.includes(selectedCategory)
      if (!matchesCategory) {
        return false
      }

      if (!query) {
        return true
      }

      const capabilities = Array.isArray(agent.capabilities) ? agent.capabilities : []
      const haystack = [
        agent.name ?? '',
        agent.agent_id ?? '',
        agent.description ?? '',
        ...capabilities,
        ...tags,
      ]
        .join(' ')
        .toLowerCase()

      return haystack.includes(query)
    })
  }, [agents, searchQuery, selectedCategory])

  const handleSelectCategory = (category: string) => {
    setSelectedCategory(category)
    // Keep drawer open when browsing; close on selection if not "All"
    if (category !== 'All') {
      setShowAllTags(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_240px_minmax(0,1fr)] md:items-center">
        <div>
          <h2 className="text-2xl font-semibold text-white">Agent Marketplace</h2>
          <p className="mt-1 text-sm text-slate-400">
            Browse local marketplace agents and external agents from HOL Registry.
          </p>
        </div>
        <div className="grid h-10 w-full grid-cols-2 rounded-full border border-white/10 bg-slate-900/60 p-1 md:w-[240px] md:justify-self-center">
          <button
            type="button"
            onClick={() => setActiveSource('local')}
            className={`h-full rounded-full px-3 text-xs font-medium transition ${
              activeSource === 'local'
                ? 'bg-slate-100 text-slate-900 shadow-sm'
                : 'text-slate-300 hover:text-white'
            }`}
          >
            Local
          </button>
          <button
            type="button"
            onClick={() => setActiveSource('hol')}
            className={`h-full rounded-full px-3 text-xs font-medium transition ${
              activeSource === 'hol'
                ? 'bg-sky-500 text-white shadow-sm shadow-sky-500/30'
                : 'text-slate-300 hover:text-white'
            }`}
          >
            HOL Registry
          </button>
        </div>
        <div className="w-[132px] justify-self-start md:justify-self-end">
          <AddAgentModal onSuccess={handleAgentAdded} />
        </div>
      </div>

      {activeSource === 'hol' ? (
        <HolMarketplaceView />
      ) : (
        <>
          <div className="space-y-4">
            <div className="relative">
              <Search className="absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                placeholder="Search agents by name or capability..."
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                className="w-full rounded-2xl border border-white/10 bg-slate-900/40 px-12 py-3 text-sm text-white placeholder:text-slate-500 focus:border-sky-400/50 focus:outline-none focus:ring-1 focus:ring-sky-400/30"
              />
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={() => setShowAllTags((value) => !value)}
                className="inline-flex items-center gap-2 rounded-lg bg-slate-800/60 px-3 py-2 text-sm text-slate-200 ring-1 ring-white/10 transition hover:bg-slate-800"
                aria-expanded={showAllTags}
                aria-controls="all-tags-accordion"
              >
                <ChevronDown className={`h-4 w-4 transition-transform ${showAllTags ? 'rotate-180' : ''}`} />
                All tags
                <span className="ml-1 rounded-md bg-slate-700/70 px-1.5 py-0.5 text-xs text-slate-300">
                  {Math.max(categories.length - 1, 0)}
                </span>
              </button>
            </div>

            {showAllTags && (
              <div
                id="all-tags-accordion"
                className="rounded-xl border border-white/15 bg-slate-900/60 p-3 backdrop-blur-sm"
              >
                <div className="max-h-56 overflow-y-auto pr-1">
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
                    {categories
                      .filter((category) => category !== 'All')
                      .map((category) => (
                        <button
                          key={category}
                          onClick={() => handleSelectCategory(category)}
                          className={`w-full truncate rounded-lg px-3 py-2 text-left text-sm transition ${
                            selectedCategory === category
                              ? 'bg-sky-500 text-white'
                              : 'bg-slate-800/50 text-slate-300 hover:bg-slate-800 hover:text-white'
                          }`}
                          title={category}
                        >
                          {category}
                        </button>
                      ))}
                  </div>
                </div>
              </div>
            )}
          </div>

          {isLoading && (
            <div className="rounded-2xl border border-white/15 bg-slate-900/50 p-6 text-center text-slate-400">
              Loading agents...
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
              filteredAgents.map((agent) => {
                const typeKey = (agent.agent_type || '').toLowerCase()
                const IconComponent = typeToIcon[typeKey] || Bot
                const capabilities = Array.isArray(agent.capabilities) ? agent.capabilities : []
                const normalizedScore =
                  typeof agent.reputation_score === 'number'
                    ? Math.max(0, Math.min(1, agent.reputation_score)) * 5
                    : null
                const ratingLabel = normalizedScore !== null ? normalizedScore.toFixed(1) : '—'

                const priceValue = typeof agent.pricing?.rate === 'number' ? agent.pricing.rate : null
                const priceLabel =
                  priceValue !== null ? `${priceValue.toFixed(2)} ${agent.pricing?.currency ?? ''}` : '—'
                const rateTypeLabel = agent.pricing?.rate_type?.replace('_', ' ') ?? 'per task'
                const holStatus = (agent.hol_registration_status || '').toLowerCase()
                const hasHolUaid = Boolean(agent.hol_uaid)
                const holRegistered = holStatus === 'registered' || holStatus === 'ok' || hasHolUaid
                const holPending = holStatus === 'pending'
                const canRegisterOnHol = Boolean(
                  agent.endpoint_url && (agent.erc8004_metadata_uri || agent.metadata_gateway_url)
                )
                const isRegistering = registeringAgentId === agent.agent_id
                const registerDisabled =
                  holRegistered || holPending || isRegistering || !canRegisterOnHol

                return (
                  <div
                    key={agent.agent_id}
                    className="group overflow-hidden rounded-2xl border border-white/15 bg-slate-900/50 backdrop-blur-sm transition hover:border-sky-400/50 hover:bg-slate-900/70"
                  >
                    <div className="p-6">
                      <div className="flex items-start gap-4">
                        <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-sky-500/20 via-indigo-500/20 to-purple-600/20 text-sky-400 ring-1 ring-white/10">
                          <IconComponent className="h-7 w-7" />
                          <HolRegisterBadge
                            holUaid={agent.hol_uaid}
                            holStatus={agent.hol_registration_status}
                          />
                        </div>
                        <div className="flex-1">
                          <h3 className="text-lg font-semibold text-white">{agent.name}</h3>
                          {agent.agent_type && <p className="text-sm text-sky-400">{agent.agent_type}</p>}
                        </div>
                      </div>

                      <p className="mt-4 text-sm leading-relaxed text-slate-300">
                        {agent.description || 'No description provided.'}
                      </p>

                      <div className="mt-4 flex flex-wrap gap-2">
                        {capabilities.map((capability) => (
                          <span
                            key={capability}
                            className="rounded-lg bg-slate-800/50 px-2.5 py-1 text-xs text-slate-300"
                          >
                            {capability}
                          </span>
                        ))}
                      </div>

                      <div className="mt-6 flex items-center justify-between border-t border-white/10 pt-4">
                        <div className="flex items-center gap-4 text-sm">
                          <div className="flex items-center gap-1.5">
                            <Star className="h-4 w-4 fill-yellow-400 text-yellow-400" />
                            <span className="font-medium text-white">{ratingLabel}</span>
                          </div>
                          <div className="text-slate-400">
                            {ratingLabel === '—' ? 'No feedback yet' : 'Avg reputation'}
                          </div>
                        </div>
                        <div className="text-right">
                          <div className="text-lg font-semibold text-white">{priceLabel}</div>
                          <div className="text-xs text-slate-400">{rateTypeLabel}</div>
                        </div>
                      </div>

                      <div className="mt-3 flex items-center justify-between gap-3">
                        <button
                          type="button"
                          onClick={() => void handleRegisterOnHol(agent.agent_id)}
                          disabled={registerDisabled}
                          className={`rounded-full px-3 py-1.5 text-xs font-medium transition ${
                            registerDisabled
                              ? 'cursor-not-allowed bg-slate-800/60 text-slate-500'
                              : 'bg-sky-500 text-white hover:bg-sky-400'
                          }`}
                          title={
                            !canRegisterOnHol
                              ? 'Agent requires endpoint + metadata URI before HOL registration.'
                              : undefined
                          }
                        >
                          {isRegistering
                            ? 'Registering on HOL...'
                            : holRegistered
                              ? 'Registered on HOL'
                              : holPending
                                ? 'HOL Registration Pending'
                                : 'Register on HOL'}
                        </button>
                      </div>
                      {holRegistrationErrors[agent.agent_id] && (
                        <p className="mt-2 text-xs text-rose-300">{holRegistrationErrors[agent.agent_id]}</p>
                      )}
                    </div>
                  </div>
                )
              })}
          </div>

          {!isLoading && !errorMessage && filteredAgents.length === 0 && (
            <div className="rounded-2xl border border-white/15 bg-slate-900/50 p-12 text-center">
              <p className="text-slate-400">No agents found matching your criteria</p>
              <p className="mt-2 text-sm text-slate-500">Try adjusting your search or filter settings</p>
            </div>
          )}
        </>
      )}
    </div>
  )
}
