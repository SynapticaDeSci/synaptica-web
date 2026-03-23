'use client'

import { useRef, useEffect, useState } from 'react'
import { Loader2, MessageSquare, Send } from 'lucide-react'
import ReactMarkdown from 'react-markdown'

import { Button } from '@/components/ui/button'
import type { DataAssetDetailRecord } from '@/lib/api'
import { cn } from '@/lib/utils'

const BACKEND_BASE_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'

interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
}

export function DatasetChat({ dataset }: { dataset: DataAssetDetailRecord }) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const text = input.trim()
    if (!text || isLoading) return

    const userMsg: ChatMessage = { id: `u-${Date.now()}`, role: 'user', text }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setIsLoading(true)

    try {
      const res = await fetch(`${BACKEND_BASE_URL}/api/data-agent/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, dataset_id: dataset.id }),
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Request failed' }))
        throw new Error(err.detail || err.error || 'Request failed')
      }

      const data = await res.json()
      const assistantMsg: ChatMessage = {
        id: `a-${Date.now()}`,
        role: 'assistant',
        text: data.response,
      }
      setMessages((prev) => [...prev, assistantMsg])
    } catch (err: any) {
      const errorMsg: ChatMessage = {
        id: `e-${Date.now()}`,
        role: 'assistant',
        text: `Error: ${err.message || 'Something went wrong'}`,
      }
      setMessages((prev) => [...prev, errorMsg])
    } finally {
      setIsLoading(false)
    }
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
        {messages.map((message) => (
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
                <ReactMarkdown>{message.text}</ReactMarkdown>
              </div>
            ) : (
              <p>{message.text}</p>
            )}
          </div>
        ))}
        {isLoading && (
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
