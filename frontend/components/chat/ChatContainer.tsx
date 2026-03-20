'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport } from 'ai'
import { useMutation } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import { Bot, Plus, Send, User } from 'lucide-react'

import { useChatStore, type ReportContext, type ResearchPlan } from '@/store/chatStore'
import { createResearchRun } from '@/lib/api'
import { ResearchPlanCard } from './ResearchPlanCard'
import { ResearchProgressInline } from './ResearchProgressInline'

export function ChatContainer() {
  const {
    phase,
    researchPlan,
    activeResearchRunId,
    reportContext,
    setPlan,
    setActiveResearchRunId,
    setPhase,
    setComplete,
    reset,
  } = useChatStore()

  const scrollRef = useRef<HTMLDivElement>(null)
  const [input, setInput] = useState('')

  // Keep a ref so the transport body closure always reads the latest value
  const reportContextRef = useRef<ReportContext | null>(reportContext)
  reportContextRef.current = reportContext

  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: '/api/chat',
        body: () => {
          const ctx = reportContextRef.current
          return ctx
            ? { researchContext: { report: ctx.report, citations: ctx.citations } }
            : {}
        },
      }),
    [],
  )

  const { messages, sendMessage, status, setMessages } = useChat({
    transport,
    onToolCall: ({ toolCall }) => {
      if (toolCall.toolName === 'createResearchPlan') {
        setPlan(toolCall.input as unknown as ResearchPlan)
      }
    },
  })

  const isLoading = status === 'streaming' || status === 'submitted'

  const launchMutation = useMutation({
    mutationFn: createResearchRun,
    onSuccess: (run) => {
      setActiveResearchRunId(run.id)
    },
    onError: (err) => {
      console.error('Failed to launch research run:', err)
    },
  })

  const handleApprove = (plan: ResearchPlan) => {
    launchMutation.mutate({
      description: plan.description,
      budget_limit: plan.budget_estimate,
    })
  }

  const handleRefine = () => {
    setPhase('chatting')
  }

  const handleNewResearch = () => {
    reset()
    setMessages([])
    setInput('')
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || isLoading) return
    sendMessage({ text: input.trim() })
    setInput('')
  }

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, phase])

  // Extract text content from message parts
  const getMessageText = (parts: typeof messages[0]['parts']) => {
    return parts
      .filter((p): p is { type: 'text'; text: string } => p.type === 'text')
      .map((p) => p.text)
      .join('')
  }

  // Check if a message has a plan tool call
  const hasPlanToolCall = (parts: typeof messages[0]['parts']) => {
    return parts.some((p) => p.type === 'tool-createResearchPlan')
  }

  const showInput = phase === 'chatting' || phase === 'plan_ready' || phase === 'complete'

  return (
    <div className="flex h-full flex-col">
      {/* Messages area */}
      <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto pb-4">
        {messages.length === 0 && phase === 'chatting' && (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-sky-500/10">
              <Bot className="h-7 w-7 text-sky-400" />
            </div>
            <h2 className="text-lg font-semibold text-white">Start your research</h2>
            <p className="mt-2 max-w-md text-sm leading-relaxed text-slate-400">
              Describe what you want to research. I&apos;ll help refine your question and create a plan before launching
              the deep research run.
            </p>
          </div>
        )}

        {messages.map((message) => {
          const text = getMessageText(message.parts)
          const hasPlan = hasPlanToolCall(message.parts)

          return (
            <div key={message.id}>
              {/* Render text content */}
              {text && (
                <div
                  className={`flex gap-3 ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  {message.role === 'assistant' && (
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-sky-500/20">
                      <Bot className="h-4 w-4 text-sky-300" />
                    </div>
                  )}
                  <div
                    className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                      message.role === 'user'
                        ? 'bg-sky-500/20 text-white'
                        : 'bg-white/5 text-slate-200'
                    }`}
                  >
                    {message.role === 'assistant' ? (
                      <div className="prose prose-sm prose-invert max-w-none prose-p:my-1 prose-ul:my-1 prose-li:my-0.5">
                        <ReactMarkdown>{text}</ReactMarkdown>
                      </div>
                    ) : (
                      text
                    )}
                  </div>
                  {message.role === 'user' && (
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-600">
                      <User className="h-4 w-4 text-slate-300" />
                    </div>
                  )}
                </div>
              )}

              {/* Render plan card if tool was called */}
              {hasPlan && phase === 'plan_ready' && researchPlan && (
                <div className="mt-4">
                  <ResearchPlanCard
                    plan={researchPlan}
                    onApprove={handleApprove}
                    onRefine={handleRefine}
                    isLaunching={launchMutation.isPending}
                    launchError={
                      launchMutation.error instanceof Error
                        ? launchMutation.error.message
                        : null
                    }
                  />
                </div>
              )}
            </div>
          )
        })}

        {/* Streaming indicator */}
        {isLoading && (
          <div className="flex gap-3">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-sky-500/20">
              <Bot className="h-4 w-4 text-sky-300" />
            </div>
            <div className="flex items-center gap-1.5 rounded-2xl bg-white/5 px-4 py-3">
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-sky-400 [animation-delay:0ms]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-sky-400 [animation-delay:150ms]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-sky-400 [animation-delay:300ms]" />
            </div>
          </div>
        )}

        {/* Inline research progress (inside scroll area so report is an artifact) */}
        {(phase === 'executing' || phase === 'complete') && activeResearchRunId && (
          <div className="mt-4">
            <ResearchProgressInline
              researchRunId={activeResearchRunId}
              onNewResearch={handleNewResearch}
              onComplete={(ctx) => setComplete(ctx)}
            />
          </div>
        )}
      </div>

      {/* Chat input */}
      {showInput && (
        <div className="flex gap-3 border-t border-white/10 pt-4">
          {phase === 'complete' && (
            <button
              type="button"
              onClick={handleNewResearch}
              title="New research"
              className="flex shrink-0 items-center justify-center rounded-2xl border border-white/10 bg-white/5 px-3 py-3 text-slate-400 transition hover:bg-white/10 hover:text-white"
            >
              <Plus className="h-4 w-4" />
            </button>
          )}
          <form onSubmit={handleSubmit} className="flex flex-1 gap-3">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={
                phase === 'complete'
                  ? 'Ask about this report...'
                  : phase === 'plan_ready'
                    ? 'Ask to refine the plan...'
                    : 'Describe your research question...'
              }
              disabled={isLoading}
              className="flex-1 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white placeholder-slate-500 outline-none transition focus:border-sky-400/50 focus:ring-1 focus:ring-sky-400/25 disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={isLoading || !input.trim()}
              className="flex shrink-0 items-center gap-2 rounded-2xl bg-gradient-to-r from-sky-500 via-cyan-500 to-teal-500 px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-sky-500/25 transition hover:opacity-90 disabled:opacity-50"
            >
              <Send className="h-4 w-4" />
            </button>
          </form>
        </div>
      )}
    </div>
  )
}
