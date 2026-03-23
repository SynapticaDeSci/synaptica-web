'use client'

import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Search, Globe2, Network, Cpu, MessageSquare, Send } from 'lucide-react'

import {
  ApiRequestError,
  createHolChatSession,
  type AgentRecord,
  type HolAgentRecord,
  type HolChatMessageRecord,
  searchHolAgents,
  sendHolChatMessage,
} from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

const KNOWN_GOOD_UAIDS = {
  ping: 'uaid:aid:2vdWUw1Qd26QtfXomHZhSJb6x4Pd3r5MTYr82v9A15ua2ja8TiVTWZEFAg1rQ37gpW',
  hederaMcp:
    'uaid:aid:9WADT6xgCjoT3XP4QCsfQdJwPn8RhXCufoHQcbKRTzdS6fTnmY4BxFKPrwjqkiT4aC',
} as const
const PINNED_TEST_AGENTS: HolAgentRecord[] = [
  {
    uaid: KNOWN_GOOD_UAIDS.ping,
    name: 'Registry Ping Agent',
    description: 'Stateless ping/pong agent for verifying Registry Broker chat connectivity.',
    capabilities: ['ping', 'connectivity'],
    categories: ['Testing'],
    transports: ['a2a'],
    pricing: {},
    registry: 'a2a-registry',
    available: null,
    availability_status: 'pinned test agent',
    trust_score: null,
    trust_scores: null,
    source_url: null,
    adapter: 'a2a-registry-adapter',
    protocol: 'a2a',
  },
  {
    uaid: KNOWN_GOOD_UAIDS.hederaMcp,
    name: 'Hedera MCP Agent',
    description: 'Pinned test agent for broker chat against the Hedera MCP surface.',
    capabilities: ['hedera', 'mcp'],
    categories: ['Infrastructure'],
    transports: ['http'],
    pricing: {},
    registry: 'hashgraph-online',
    available: null,
    availability_status: 'pinned test agent',
    trust_score: null,
    trust_scores: null,
    source_url: null,
    adapter: null,
    protocol: 'http',
  },
]
const HIGH_TRUST_THRESHOLD = 10

function normalizeForMatch(value: string | null | undefined): string {
  return String(value ?? '').trim().toLowerCase()
}

function holAgentTrustScore(agent: HolAgentRecord): number | null {
  return typeof agent.trust_score === 'number' && Number.isFinite(agent.trust_score)
    ? agent.trust_score
    : null
}

function isOpenRouterRegistryAgent(agent: HolAgentRecord): boolean {
  const registry = normalizeForMatch(agent.registry)
  const name = normalizeForMatch(agent.name)
  const description = normalizeForMatch(agent.description)
  return (
    registry.includes('openrouter') ||
    name.includes('openrouter') ||
    description.includes('openrouter')
  )
}

function isKnownGoodHolAgent(agent: HolAgentRecord): boolean {
  return (
    agent.uaid === KNOWN_GOOD_UAIDS.ping ||
    agent.uaid === KNOWN_GOOD_UAIDS.hederaMcp ||
    isOpenRouterRegistryAgent(agent)
  )
}

function compareAgentsByTrust(a: HolAgentRecord, b: HolAgentRecord): number {
  const trustA = holAgentTrustScore(a)
  const trustB = holAgentTrustScore(b)
  if (trustA !== null && trustB !== null && trustA !== trustB) {
    return trustB - trustA
  }
  if (trustA !== null && trustB === null) return -1
  if (trustA === null && trustB !== null) return 1
  return a.name.localeCompare(b.name)
}

function holAgentChatHint(agent: HolAgentRecord): {
  label: string
  toneClass: string
  recommendedTransport?: string
} {
  const transports = (agent.transports ?? []).map((item) => String(item).trim().toLowerCase()).filter(Boolean)
  const protocol = String(agent.protocol ?? '').trim().toLowerCase()
  const adapter = String(agent.adapter ?? '').trim().toLowerCase()
  const trustScore = holAgentTrustScore(agent)

  if (transports.includes('http') && trustScore !== null && trustScore >= HIGH_TRUST_THRESHOLD) {
    return {
      label: 'Trusted + usable',
      toneClass: 'bg-emerald-500/20 text-emerald-200',
      recommendedTransport: 'http',
    }
  }
  if (transports.includes('http')) {
    return {
      label: 'Likely usable',
      toneClass: 'bg-sky-500/20 text-sky-200',
      recommendedTransport: 'http',
    }
  }
  if (['a2a', 'uagent'].includes(protocol) || ['a2a-registry-adapter', 'agentverse-adapter'].includes(adapter)) {
    return {
      label: 'High risk',
      toneClass: 'bg-red-500/20 text-red-200',
    }
  }
  return {
    label: 'Unknown',
    toneClass: 'bg-amber-500/20 text-amber-200',
  }
}

function holSessionSupport(agent: HolAgentRecord): { supported: boolean; reason?: string } {
  const isAvailable = agent.available === true
  const protocol = String(agent.protocol ?? '').trim().toLowerCase()
  const adapter = String(agent.adapter ?? '').trim().toLowerCase()

  if (!isAvailable) {
    if (isKnownGoodHolAgent(agent)) {
      return {
        supported: true,
        reason:
          'Pinned test agent. HOL may currently mark it unavailable, but it is still worth trying for broker-chat validation.',
      }
    }
    return {
      supported: false,
      reason: 'This agent is discoverable in HOL but is not currently marked available by the broker.',
    }
  }

  if (protocol === 'acp' || adapter === 'virtuals-protocol-adapter') {
    return {
      supported: true,
      reason:
        'Virtuals ACP is often job-based and may require provider wallet/payment setup, so chat may fail even though this agent appears available.',
    }
  }

  if (['a2a', 'uagent'].includes(protocol) || ['a2a-registry-adapter', 'agentverse-adapter'].includes(adapter)) {
    return {
      supported: true,
      reason:
        'This protocol/adapter is available but commonly unreliable in this broker environment. Chat is allowed, but failures are expected.',
    }
  }

  return { supported: true }
}

function extractHolChatStatus(brokerResponse: Record<string, any> | null | undefined): {
  mode: string
  fallbackReason?: string | null
} | null {
  if (!brokerResponse || typeof brokerResponse !== 'object') return null
  const mode = typeof brokerResponse.mode === 'string' ? brokerResponse.mode.trim() : ''
  if (!mode) return null
  return {
    mode,
    fallbackReason:
      typeof brokerResponse.fallback_reason === 'string' ? brokerResponse.fallback_reason : null,
  }
}

function decodeHolHtmlEntities(value: string): string {
  return value
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
}

function stripHolChatMarkup(value: string): string {
  const normalized = String(value ?? '').replace(/\r\n/g, '\n')
  const withBreaks = normalized
    .replace(/<\s*br\s*\/?>/gi, '\n')
    .replace(/<\s*\/p\s*>/gi, '\n\n')
    .replace(/<\s*p[^>]*>/gi, '')
  const withoutTags = withBreaks.replace(/<[^>]+>/g, '')
  return decodeHolHtmlEntities(withoutTags)
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

function parseHolSearchSnippet(value: string): {
  title: string
  link?: string
  content: string
} | null {
  const normalized = String(value ?? '').replace(/\r\n/g, '\n').trim()
  if (!/^Title:\s*/i.test(normalized)) {
    return null
  }

  const fields: Record<'title' | 'link' | 'content', string[]> = {
    title: [],
    link: [],
    content: [],
  }
  let activeField: 'title' | 'link' | 'content' | null = null

  for (const line of normalized.split('\n')) {
    const match = line.match(/^(Title|Link|Content):\s*(.*)$/i)
    if (match) {
      activeField = match[1].toLowerCase() as 'title' | 'link' | 'content'
      if (match[2]) {
        fields[activeField].push(match[2])
      }
      continue
    }
    if (activeField) {
      fields[activeField].push(line)
    }
  }

  const title = stripHolChatMarkup(fields.title.join('\n'))
  const link = fields.link.join('\n').trim()
  const content = stripHolChatMarkup(fields.content.join('\n'))
  if (!title || !content) {
    return null
  }

  return {
    title,
    link: /^https?:\/\//i.test(link) ? link : undefined,
    content,
  }
}

function renderHolChatContent(content: string) {
  const snippet = parseHolSearchSnippet(content)
  if (snippet) {
    return (
      <div className="space-y-2">
        <div className="font-medium text-white">{snippet.title}</div>
        {snippet.link && (
          <a
            href={snippet.link}
            target="_blank"
            rel="noreferrer"
            className="block break-all text-xs text-sky-300 underline decoration-sky-400/40 underline-offset-2 hover:text-sky-200"
          >
            {snippet.link}
          </a>
        )}
        <div className="whitespace-pre-wrap break-words text-slate-100">{snippet.content}</div>
      </div>
    )
  }

  const cleaned = stripHolChatMarkup(content)
  return <div className="whitespace-pre-wrap break-words">{cleaned || content}</div>
}

export function HolMarketplaceView({ localAgents = [] }: { localAgents?: AgentRecord[] }) {
  const [searchQuery, setSearchQuery] = useState('')
  const [showAvailableOnly, setShowAvailableOnly] = useState(false)
  const [showHighTrustOnly, setShowHighTrustOnly] = useState(false)
  const [selectedAgent, setSelectedAgent] = useState<HolAgentRecord | null>(null)
  const [chatTransport, setChatTransport] = useState('')
  const [chatSessionId, setChatSessionId] = useState<string | null>(null)
  const [chatMessages, setChatMessages] = useState<HolChatMessageRecord[]>([])
  const [chatDraft, setChatDraft] = useState('')
  const [chatError, setChatError] = useState<string | null>(null)
  const [chatStatus, setChatStatus] = useState<{
    mode: string
    fallbackReason?: string | null
  } | null>(null)

  const { data, isLoading, isError, error, refetch } = useQuery<
    { agents: HolAgentRecord[]; query: string },
    Error
  >({
    queryKey: ['hol-agents', searchQuery, showAvailableOnly],
    queryFn: () => searchHolAgents(searchQuery, { onlyAvailable: showAvailableOnly }),
    staleTime: 30_000,
  })

  const startChatMutation = useMutation({
    mutationFn: async (input: { uaid: string; transport?: string }) =>
      createHolChatSession({
        uaid: input.uaid,
        transport: input.transport,
      }),
    onMutate: () => {
      setChatError(null)
      setChatMessages([])
      setChatSessionId(null)
      setChatStatus(null)
    },
    onSuccess: (result) => {
      setChatSessionId(result.session_id)
      setChatMessages(result.history ?? [])
      setChatStatus(extractHolChatStatus(result.broker_response))
    },
    onError: (error: Error) => {
      setChatError(error.message || 'Failed to start HOL chat session')
    },
  })

  const sendChatMutation = useMutation({
    mutationFn: async (input: { sessionId: string; message: string }) =>
      sendHolChatMessage({
        session_id: input.sessionId,
        message: input.message,
      }),
    onMutate: () => {
      setChatError(null)
    },
    onSuccess: (result) => {
      setChatMessages(result.history ?? [])
      setChatDraft('')
      setChatStatus(extractHolChatStatus(result.broker_response))
    },
    onError: (error: Error) => {
      const message =
        error instanceof ApiRequestError ? error.message : error.message || 'Failed to send HOL chat message'
      setChatError(message)
    },
  })

  useEffect(() => {
    if (!selectedAgent) return
    const hint = holAgentChatHint(selectedAgent)
    setChatTransport(hint.recommendedTransport ?? '')
    setChatSessionId(null)
    setChatMessages([])
    setChatDraft('')
    setChatError(null)
    setChatStatus(null)
  }, [selectedAgent])

  const agents = useMemo(
    () => [...(data?.agents ?? [])].sort(compareAgentsByTrust),
    [data]
  )
  const pinnedTestAgents = useMemo(() => {
    const byUaid = new Map(agents.map((agent) => [agent.uaid, agent]))
    return PINNED_TEST_AGENTS.map((fallback) => {
      const discovered = byUaid.get(fallback.uaid)
      return discovered ? { ...fallback, ...discovered } : fallback
    })
  }, [agents])
  const pinnedTestAgentUaids = useMemo(
    () => new Set(PINNED_TEST_AGENTS.map((agent) => agent.uaid)),
    []
  )
  const filteredAgents = useMemo(
    () =>
      agents.filter((agent) => {
        if (!showHighTrustOnly) {
          return true
        }
        const trustScore = holAgentTrustScore(agent)
        return trustScore !== null && trustScore >= HIGH_TRUST_THRESHOLD
      }),
    [agents, showHighTrustOnly]
  )
  const localHolAgents = useMemo(
    () =>
      localAgents
        .filter(
          (agent) =>
            (agent.hol_registration_status || '').toLowerCase() === 'registered' &&
            typeof agent.hol_uaid === 'string' &&
            agent.hol_uaid.trim()
        )
        .sort((a, b) => a.name.localeCompare(b.name)),
    [localAgents]
  )
  const recommendedAgents = useMemo(() => {
    const seen = new Set<string>()
    const recommended = filteredAgents.filter((agent) => {
      if (pinnedTestAgentUaids.has(agent.uaid) || !isOpenRouterRegistryAgent(agent)) {
        return false
      }
      seen.add(agent.uaid)
      return true
    })
    return { recommended, seen }
  }, [filteredAgents, pinnedTestAgentUaids])
  const availableAgents = useMemo(
    () =>
      filteredAgents.filter(
        (agent) =>
          agent.available === true &&
          !pinnedTestAgentUaids.has(agent.uaid) &&
          !recommendedAgents.seen.has(agent.uaid)
      ),
    [filteredAgents, pinnedTestAgentUaids, recommendedAgents]
  )
  const unavailableAgents = useMemo(
    () =>
      filteredAgents.filter(
        (agent) =>
          agent.available !== true &&
          !pinnedTestAgentUaids.has(agent.uaid) &&
          !recommendedAgents.seen.has(agent.uaid)
      ),
    [filteredAgents, pinnedTestAgentUaids, recommendedAgents]
  )
  const errorMessage = isError ? error?.message ?? 'Failed to load HOL agents' : null
  const selectedAgentHint = useMemo(
    () => (selectedAgent ? holAgentChatHint(selectedAgent) : null),
    [selectedAgent]
  )
  const selectedAgentSessionSupport = useMemo(
    () => (selectedAgent ? holSessionSupport(selectedAgent) : { supported: false }),
    [selectedAgent]
  )

  const handleOpenChat = (agent: HolAgentRecord) => {
    setSelectedAgent(agent)
  }

  const handleStartSession = () => {
    if (!selectedAgent) return
    startChatMutation.mutate({
      uaid: selectedAgent.uaid,
      transport: chatTransport || undefined,
    })
  }

  const handleSendMessage = () => {
    if (!chatSessionId || !chatDraft.trim()) return
    sendChatMutation.mutate({
      sessionId: chatSessionId,
      message: chatDraft.trim(),
    })
  }

  const handleCopyUaid = async (uaid: string) => {
    try {
      await navigator.clipboard.writeText(uaid)
    } catch {
      // ignore clipboard failures in browser-only helper
    }
  }

  const renderAgentCard = (agent: HolAgentRecord) => {
    const hasTransports = Array.isArray(agent.transports) && agent.transports.length > 0
    const Icon = hasTransports ? Network : Cpu
    const price = agent.pricing?.rate
    const currency = agent.pricing?.currency ?? 'HBAR'
    const rateType = agent.pricing?.rate_type?.replace('_', ' ') ?? 'per task'
    const hint = holAgentChatHint(agent)
    const sessionSupport = holSessionSupport(agent)
    const trustScore = holAgentTrustScore(agent)

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
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="truncate text-lg font-semibold text-white">{agent.name}</h3>
                <span className={`rounded-md px-2 py-0.5 text-[11px] ${hint.toneClass}`}>
                  {hint.label}
                </span>
                <span
                  className={`rounded-md px-2 py-0.5 text-[11px] ${
                    agent.available === true
                      ? 'bg-emerald-500/20 text-emerald-200'
                      : 'bg-slate-700/70 text-slate-300'
                  }`}
                >
                  {agent.available === true ? 'Available now' : 'Discoverable only'}
                </span>
              </div>
              <p className="mt-1 truncate font-mono text-xs text-slate-400">{agent.uaid}</p>
              {agent.registry && (
                <div className="mt-1 inline-flex items-center gap-1 rounded-full bg-slate-800/60 px-2 py-0.5 text-[11px] text-slate-200">
                  <Globe2 className="h-3 w-3 text-sky-400" />
                  {agent.registry}
                </div>
              )}
              {trustScore !== null && (
                <div className="mt-1 inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] text-emerald-200">
                  trust {trustScore.toFixed(2)}
                </div>
              )}
            </div>
          </div>

          {agent.description && (
            <p className="mt-4 line-clamp-3 text-sm leading-relaxed text-slate-300">
              {agent.description}
            </p>
          )}

          <div className="mt-3 flex flex-wrap gap-1.5">
            {(agent.transports ?? []).map((t) => (
              <span
                key={t}
                className="rounded-full bg-slate-800/60 px-2 py-0.5 text-[11px] uppercase tracking-wide text-slate-200"
              >
                {t}
              </span>
            ))}
            {agent.protocol && (
              <span className="rounded-full bg-slate-800/60 px-2 py-0.5 text-[11px] text-slate-200">
                proto:{agent.protocol}
              </span>
            )}
            {agent.availability_status && (
              <span className="rounded-full bg-slate-800/60 px-2 py-0.5 text-[11px] text-slate-200">
                {agent.availability_status}
              </span>
            )}
          </div>

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
                className={`inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-xs font-medium transition ${
                  sessionSupport.supported
                    ? 'bg-sky-500 text-white shadow-sm shadow-sky-500/30 hover:bg-sky-400'
                    : 'cursor-not-allowed bg-slate-700/60 text-slate-400'
                }`}
                onClick={() => handleOpenChat(agent)}
                disabled={!sessionSupport.supported}
                title={sessionSupport.reason}
              >
                <MessageSquare className="h-3.5 w-3.5" />
                Open chat
              </button>
              <button
                type="button"
                className="text-[11px] text-slate-400 transition hover:text-slate-200"
                onClick={() => void handleCopyUaid(agent.uaid)}
              >
                Copy UAID
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-white">HOL Registry</h2>
          <p className="mt-1 text-sm text-slate-400">
            Browse discovered HOL agents, but use your own registered Synaptica agents first for the most reliable hackathon demo path.
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
        <div className="flex flex-wrap gap-3">
          <label className="inline-flex items-center gap-3 rounded-xl border border-white/10 bg-slate-900/40 px-4 py-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={showAvailableOnly}
              onChange={(event) => setShowAvailableOnly(event.target.checked)}
              className="h-4 w-4 rounded border-white/20 bg-slate-950 text-sky-500 focus:ring-sky-400/40"
            />
            <span>Available only</span>
          </label>
          <label className="inline-flex items-center gap-3 rounded-xl border border-white/10 bg-slate-900/40 px-4 py-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={showHighTrustOnly}
              onChange={(event) => setShowHighTrustOnly(event.target.checked)}
              className="h-4 w-4 rounded border-white/20 bg-slate-950 text-sky-500 focus:ring-sky-400/40"
            />
            <span>High trust only</span>
            <span className="text-xs text-slate-500">trust &gt;= {HIGH_TRUST_THRESHOLD}</span>
          </label>
        </div>
        <div className="rounded-2xl border border-white/10 bg-slate-900/30 p-4 text-sm text-slate-400">
          Many HOL agents are discoverable but not consistently usable. Public registry results are exploratory; for demos, prefer your own registered agents, then Ping Agent, Hedera MCP Agent, and OpenRouter-backed entries when available.
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

      {!isLoading && !errorMessage && localHolAgents.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold uppercase tracking-[0.18em] text-sky-200">
              Your Registered HOL Agents
            </h3>
            <span className="text-xs text-slate-400">{localHolAgents.length} agents</span>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            {localHolAgents.map((agent) => (
              <div
                key={agent.agent_id}
                className="rounded-2xl border border-sky-500/20 bg-sky-500/5 p-5 text-sm"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-base font-semibold text-white">{agent.name}</div>
                    <div className="mt-1 break-all font-mono text-xs text-slate-400">
                      {agent.hol_uaid}
                    </div>
                  </div>
                  <span className="rounded-md bg-emerald-500/20 px-2 py-0.5 text-[11px] text-emerald-200">
                    registered
                  </span>
                </div>
                <div className="mt-4 flex items-center gap-2">
                  <Button
                    type="button"
                    onClick={() =>
                      handleOpenChat({
                        uaid: agent.hol_uaid || '',
                        name: agent.name,
                        description: agent.description || '',
                        capabilities: agent.capabilities || [],
                        categories: agent.categories || [],
                        transports: ['http'],
                        pricing: {},
                        registry: 'synaptica-local',
                        available: true,
                        availability_status: 'registered',
                        trust_score: null,
                        trust_scores: null,
                        source_url: agent.endpoint_url || null,
                        adapter: null,
                        protocol: 'http',
                      })
                    }
                    className="bg-sky-600 text-white hover:bg-sky-500"
                  >
                    <MessageSquare className="mr-2 h-4 w-4" />
                    Open chat
                  </Button>
                  <button
                    type="button"
                    className="text-xs text-slate-400 transition hover:text-slate-200"
                    onClick={() => void handleCopyUaid(agent.hol_uaid || '')}
                  >
                    Copy UAID
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {!isLoading && !errorMessage && pinnedTestAgents.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold uppercase tracking-[0.18em] text-amber-200">
              Pinned Test Agents
            </h3>
            <span className="text-xs text-slate-400">
              {pinnedTestAgents.length} agents
            </span>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {pinnedTestAgents.map((agent) => renderAgentCard(agent))}
          </div>
        </div>
      )}

      {!isLoading && !errorMessage && recommendedAgents.recommended.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold uppercase tracking-[0.18em] text-amber-200">
              Registry-Recommended
            </h3>
            <span className="text-xs text-slate-400">
              {recommendedAgents.recommended.length} agents
            </span>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {recommendedAgents.recommended.map((agent) => renderAgentCard(agent))}
          </div>
        </div>
      )}

      {!isLoading && !errorMessage && availableAgents.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold uppercase tracking-[0.18em] text-emerald-200">
              Available Now
            </h3>
            <span className="text-xs text-slate-400">{availableAgents.length} agents</span>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {availableAgents.map((agent) => renderAgentCard(agent))}
          </div>
        </div>
      )}

      {!isLoading && !errorMessage && !showAvailableOnly && unavailableAgents.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-300">
              Discoverable Only
            </h3>
            <span className="text-xs text-slate-500">
              {unavailableAgents.length} agents
            </span>
          </div>
          <p className="text-sm text-slate-500">
            These agents exist in HOL search results, but the broker does not currently mark them available for direct use here.
          </p>
          <div className="grid gap-4 md:grid-cols-2">
            {unavailableAgents.map((agent) => renderAgentCard(agent))}
          </div>
        </div>
      )}

      {!isLoading && !errorMessage && agents.length === 0 && (
        <div className="rounded-2xl border border-white/15 bg-slate-900/50 p-12 text-center">
          <p className="text-slate-400">No HOL agents found for this query yet.</p>
          <p className="mt-2 text-sm text-slate-500">
            Try a broader search term, or ensure the HOL sidecar and REGISTRY_BROKER_API_KEY are configured.
          </p>
        </div>
      )}

      <Dialog
        open={Boolean(selectedAgent)}
        onOpenChange={(open) => {
          if (!open) {
            setSelectedAgent(null)
            setChatSessionId(null)
            setChatMessages([])
            setChatDraft('')
            setChatError(null)
            setChatStatus(null)
          }
        }}
      >
        <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto border-white/15 bg-slate-950 text-slate-100">
          <DialogHeader>
            <DialogTitle>{selectedAgent?.name || 'HOL chat'}</DialogTitle>
            <DialogDescription className="text-slate-400">
              Start a broker chat session with this HOL agent to verify that it responds before using it elsewhere.
            </DialogDescription>
          </DialogHeader>

          {selectedAgent && (
            <div className="space-y-4">
              <div className="rounded-lg border border-white/10 bg-slate-900/60 p-3 text-sm text-slate-200">
                <div className="break-all font-mono text-xs text-slate-400">{selectedAgent.uaid}</div>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  {selectedAgentHint && (
                    <span className={`rounded-md px-2 py-0.5 text-[11px] ${selectedAgentHint.toneClass}`}>
                      {selectedAgentHint.label}
                    </span>
                  )}
                  {selectedAgent.availability_status && (
                    <span className="rounded-md bg-slate-800 px-2 py-0.5 text-[11px] text-slate-300">
                      {selectedAgent.availability_status}
                    </span>
                  )}
                </div>
              </div>

              <div className="grid gap-2 md:grid-cols-[180px_minmax(0,1fr)_auto]">
                <select
                  value={chatTransport}
                  onChange={(event) => setChatTransport(event.target.value)}
                  className="h-10 rounded-md border border-white/10 bg-slate-950/40 px-3 text-sm text-white"
                >
                  <option value="">Auto transport</option>
                  <option value="http">Force http</option>
                  <option value="a2a">Force a2a</option>
                </select>
                <div className="flex items-center rounded-md border border-white/10 bg-slate-950/40 px-3 text-xs text-slate-400">
                  {chatSessionId ? `Session: ${chatSessionId}` : 'No session started yet'}
                </div>
                <Button
                  type="button"
                  onClick={handleStartSession}
                  disabled={startChatMutation.isPending || !selectedAgentSessionSupport.supported}
                  className="bg-sky-600 text-white hover:bg-sky-500"
                >
                  {startChatMutation.isPending ? 'Starting...' : chatSessionId ? 'Restart session' : 'Start session'}
                </Button>
              </div>

              {chatError && (
                <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-200">
                  {chatError}
                </div>
              )}
              {chatStatus && (
                <div
                  className={`rounded-lg border px-3 py-2 text-xs ${
                    chatStatus.mode === 'direct'
                      ? 'border-amber-500/40 bg-amber-500/10 text-amber-200'
                      : 'border-sky-500/40 bg-sky-500/10 text-sky-200'
                  }`}
                >
                  {chatStatus.mode === 'direct'
                    ? 'Using direct UAID fallback because broker session creation was transiently unavailable.'
                    : 'Using broker session mode.'}
                  {chatStatus.mode === 'direct' && chatStatus.fallbackReason && (
                    <div className="mt-1 text-amber-100">{chatStatus.fallbackReason}</div>
                  )}
                </div>
              )}
              {selectedAgentSessionSupport.reason && (
                <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                  {selectedAgentSessionSupport.reason}
                </div>
              )}

              <div className="min-h-[280px] space-y-3 rounded-lg border border-white/10 bg-slate-900/50 p-3">
                {chatMessages.length === 0 ? (
                  <div className="text-sm text-slate-400">
                    Start a session, then send a short probe like `hello`, `summarize your capability`, or a domain-specific question.
                  </div>
                ) : (
                  chatMessages.map((message, index) => (
                    <div
                      key={`${message.timestamp || index}-${index}`}
                      className={`rounded-lg px-3 py-2 text-sm ${
                        message.role === 'user'
                          ? 'ml-8 bg-sky-500/20 text-sky-100'
                          : 'mr-8 bg-slate-800 text-slate-100'
                      }`}
                    >
                      <div className="mb-1 text-[11px] uppercase tracking-wide text-slate-400">
                        {message.role}
                      </div>
                      {renderHolChatContent(message.content)}
                    </div>
                  ))
                )}
              </div>

              <div className="space-y-2">
                <Textarea
                  placeholder="Type a message to this HOL agent..."
                  value={chatDraft}
                  onChange={(event) => setChatDraft(event.target.value)}
                  className="min-h-[110px] border-white/10 bg-slate-950/40 text-white"
                />
                <div className="flex justify-end">
                  <Button
                    type="button"
                    onClick={handleSendMessage}
                    disabled={!chatSessionId || !chatDraft.trim() || sendChatMutation.isPending}
                    className="bg-emerald-600 text-white hover:bg-emerald-500"
                  >
                    <Send className="mr-2 h-4 w-4" />
                    {sendChatMutation.isPending ? 'Sending...' : 'Send message'}
                  </Button>
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
