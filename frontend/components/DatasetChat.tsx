'use client'

import { useRef, useEffect, useMemo, useState } from 'react'
import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport } from 'ai'
import { Loader2, MessageSquare, Send } from 'lucide-react'
import ReactMarkdown from 'react-markdown'

import { Button } from '@/components/ui/button'
import type { DataAssetDetailRecord } from '@/lib/api'
import { cn } from '@/lib/utils'

function getMessageText(parts: { type: string; text?: string }[]) {
  return parts
    .filter((p): p is { type: 'text'; text: string } => p.type === 'text')
    .map((p) => p.text)
    .join('')
}

export function DatasetChat({ dataset }: { dataset: DataAssetDetailRecord }) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [input, setInput] = useState('')

  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: '/api/data-agent-chat',
        body: {
          datasetContext: {
            id: dataset.id,
            title: dataset.title,
            description: dataset.description,
            lab_name: dataset.lab_name,
            classification: dataset.data_classification,
            tags: dataset.tags,
            filename: dataset.filename,
            size_bytes: dataset.size_bytes,
            content_type: dataset.content_type,
            verification_status: dataset.verification_status,
            proof_status: dataset.proof_status,
            reuse_count: dataset.reuse_count,
            created_at: dataset.created_at,
          },
        },
      }),
    [dataset],
  )

  const { messages, sendMessage, status } = useChat({
    id: `dataset-chat-${dataset.id}`,
    transport,
  })

  const isLoading = status === 'streaming' || status === 'submitted'

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || isLoading) return
    sendMessage({ text: input.trim() })
    setInput('')
  }

  return (
    <div className="flex h-full flex-col rounded-2xl border border-white/10 bg-white/5 p-4">
      <div className="flex items-center gap-2">
        <MessageSquare className="h-4 w-4 text-sky-400" />
        <p className="text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">
          Ask about this dataset
        </p>
      </div>

      <div
        ref={scrollRef}
        className="mt-3 flex-1 space-y-3 overflow-y-auto"
      >
        {messages.length === 0 && (
          <p className="py-6 text-center text-xs text-slate-500">
            Ask anything about this dataset — its contents, quality, format, or how to reuse it.
          </p>
        )}
        {messages.map((message) => {
            const text = getMessageText(
              message.parts as { type: string; text?: string }[],
            )
            if (!text) return null

            return (
              <div
                key={message.id}
                className={cn(
                  'rounded-xl px-3 py-2 text-sm',
                  message.role === 'user'
                    ? 'ml-8 border border-sky-400/20 bg-sky-400/10 text-sky-50'
                    : 'mr-8 border border-white/10 bg-slate-950/40 text-slate-200',
                )}
              >
                {message.role === 'assistant' ? (
                  <div className="prose prose-invert prose-sm max-w-none prose-p:text-slate-200 prose-a:text-sky-200">
                    <ReactMarkdown>{text}</ReactMarkdown>
                  </div>
                ) : (
                  <p>{text}</p>
                )}
              </div>
            )
          })}
          {isLoading && messages[messages.length - 1]?.role === 'user' && (
            <div className="mr-8 flex items-center gap-2 rounded-xl border border-white/10 bg-slate-950/40 px-3 py-2 text-sm text-slate-400">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Thinking...
            </div>
          )}
      </div>

      <form onSubmit={handleSubmit} className="mt-3 flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="e.g. Describe this dataset, What format is it in?"
          className="flex-1 rounded-xl border border-white/10 bg-slate-950/60 px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:border-sky-400/40 focus:outline-none"
        />
        <Button
          type="submit"
          size="sm"
          disabled={!input.trim() || isLoading}
          className="border-sky-400/20 bg-sky-400/10 text-sky-100 hover:bg-sky-400/20"
          variant="outline"
        >
          <Send className="h-3.5 w-3.5" />
        </Button>
      </form>
    </div>
  )
}
