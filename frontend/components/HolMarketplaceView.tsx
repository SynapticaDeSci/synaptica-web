'use client'

import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Search, Globe2, Network, Cpu, MessageSquare, Send } from 'lucide-react'

import {
  ApiRequestError,
  createHolChatSession,
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

function holAgentChatHint(agent: HolAgentRecord): {
  label: string
  toneClass: string
  recommendedTransport?: string
} {
  const transports = (agent.transports ?? []).map((item) => String(item).trim().toLowerCase()).filter(Boolean)
  const protocol = String(agent.protocol ?? '').trim().toLowerCase()
  const adapter = String(agent.adapter ?? '').trim().toLowerCase()

  if (transports.includes('http')) {
    return {
      label: 'Likely usable',
      toneClass: 'bg-emerald-500/20 text-emerald-200',
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
  const protocol = String(agent.protocol ?? '').trim().toLowerCase()
  const adapter = String(agent.adapter ?? '').trim().toLowerCase()

  if (protocol === 'acp' || adapter === 'virtuals-protocol-adapter') {
    return {
      supported: true,
      reason:
        'Virtuals ACP is often job-based and may require provider wallet/payment setup; chat can still be attempted.',
    }
  }

  return { supported: true }
}

export function HolMarketplaceView() {
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedAgent, setSelectedAgent] = useState<HolAgentRecord | null>(null)
  const [chatTransport, setChatTransport] = useState('')
  const [chatSessionId, setChatSessionId] = useState<string | null>(null)
  const [chatMessages, setChatMessages] = useState<HolChatMessageRecord[]>([])
  const [chatDraft, setChatDraft] = useState('')
  const [chatError, setChatError] = useState<string | null>(null)

  const { data, isLoading, isError, error, refetch } = useQuery<
    { agents: HolAgentRecord[]; query: string },
    Error
  >({
    queryKey: ['hol-agents', searchQuery],
    queryFn: () => searchHolAgents(searchQuery, { onlyAvailable: true }),
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
    },
    onSuccess: (result) => {
      setChatSessionId(result.session_id)
      setChatMessages(result.history ?? [])
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
  }, [selectedAgent])

  const agents = data?.agents ?? []
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

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-white">HOL Registry</h2>
          <p className="mt-1 text-sm text-slate-400">
            Discover external HOL agents currently marked available by the broker and test them with a live broker chat session.
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
            const hint = holAgentChatHint(agent)
            const sessionSupport = holSessionSupport(agent)

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
                      </div>
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

      <Dialog
        open={Boolean(selectedAgent)}
        onOpenChange={(open) => {
          if (!open) {
            setSelectedAgent(null)
            setChatSessionId(null)
            setChatMessages([])
            setChatDraft('')
            setChatError(null)
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
                      <div className="whitespace-pre-wrap break-words">{message.content}</div>
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
