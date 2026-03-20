'use client'

import { Suspense, useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport } from 'ai'
import ReactMarkdown from 'react-markdown'
import { Bot, Loader2, Send, User } from 'lucide-react'

import { Sidebar } from '@/components/Sidebar'
import { ResearchRunDetailView } from '@/components/research-runs/detail'
import type { ResearchSourceCard } from '@/lib/api'

function getMessageText(parts: { type: string; text?: string }[]) {
  return parts
    .filter((p): p is { type: 'text'; text: string } => p.type === 'text')
    .map((p) => p.text)
    .join('')
}

/** Follow-up chat — only mounts once report context is available */
function DetailFollowUpChat({
  researchRunId,
  reportContext,
  scrollAnchorRef,
}: {
  researchRunId: string
  reportContext: { report: string; citations: ResearchSourceCard[] }
  scrollAnchorRef: React.RefObject<HTMLDivElement | null>
}) {
  const [input, setInput] = useState('')

  const { messages, sendMessage, status } = useChat({
    id: `research-followup-${researchRunId}`,
    transport: new DefaultChatTransport({
      api: '/api/chat',
      body: {
        researchContext: {
          report: reportContext.report,
          citations: reportContext.citations.map((c) => ({
            citation_id: c.citation_id,
            title: c.title,
            url: c.url,
            publisher: c.publisher,
          })),
        },
      },
    }),
  })

  const isLoading = status === 'streaming' || status === 'submitted'

  useEffect(() => {
    scrollAnchorRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, scrollAnchorRef])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || isLoading) return
    sendMessage({ text: input.trim() })
    setInput('')
  }

  return (
    <>
      {/* Follow-up messages */}
      {messages.length > 0 && (
        <div className="mt-6 space-y-4">
          <p className="text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">
            Follow-up conversation
          </p>
          {messages.map((message) => {
            const text = getMessageText(message.parts as { type: string; text?: string }[])
            if (!text) return null
            return (
              <div
                key={message.id}
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
                    <div className="prose prose-sm prose-invert max-w-none prose-p:my-1 prose-ul:my-1 prose-li:my-0.5 prose-a:text-sky-200">
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
            )
          })}
          {isLoading && messages[messages.length - 1]?.role === 'user' && (
            <div className="flex gap-3">
              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-sky-500/20">
                <Bot className="h-4 w-4 text-sky-300" />
              </div>
              <div className="flex items-center gap-2 rounded-2xl bg-white/5 px-4 py-3 text-sm text-slate-400">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Thinking...
              </div>
            </div>
          )}
        </div>
      )}

      {/* Sticky chat input */}
      <div className="sticky bottom-0 mt-6 border-t border-white/10 bg-slate-950/95 px-0 py-4 backdrop-blur-sm">
        <form onSubmit={handleSubmit} className="flex gap-3">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about this report..."
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
    </>
  )
}

export default function ResearchRunDetailPage({
  params,
}: {
  params: { id: string }
}) {
  const [activeTab, setActiveTab] = useState('research')
  const [reportContext, setReportContext] = useState<{
    report: string
    citations: ResearchSourceCard[]
  } | null>(null)

  const router = useRouter()
  const scrollAnchorRef = useRef<HTMLDivElement>(null)

  return (
    <div className="flex h-screen overflow-hidden bg-slate-950 text-slate-100">
      <Suspense fallback={null}>
        <Sidebar
          activeTab={activeTab}
          onTabChange={(tab) => {
            setActiveTab(tab)
            router.push('/')
          }}
          onNewResearch={() => router.push('/')}
        />
      </Suspense>

      <main className="flex flex-1 flex-col overflow-y-auto">
        <div className="mx-auto w-full max-w-5xl px-6 py-8">
          <ResearchRunDetailView
            researchRunId={params.id}
            onComplete={setReportContext}
            hideFollowUpChat
          />

          {reportContext && (
            <DetailFollowUpChat
              researchRunId={params.id}
              reportContext={reportContext}
              scrollAnchorRef={scrollAnchorRef}
            />
          )}
          <div ref={scrollAnchorRef} />
        </div>
      </main>
    </div>
  )
}
