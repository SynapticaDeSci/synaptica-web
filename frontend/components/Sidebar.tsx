'use client'

import { useEffect, useState } from 'react'
import Image from 'next/image'
import { Database, Microscope, Plus, Receipt, Store, Zap } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

interface SidebarProps {
  activeTab: string
  onTabChange: (tab: string) => void
  onNewResearch: () => void
}

const NAV_ITEMS: Array<{ id: string; label: string; icon: LucideIcon }> = [
  { id: 'research',     label: 'Research Console', icon: Microscope },
  { id: 'transactions', label: 'Transactions',      icon: Receipt },
  { id: 'marketplace',  label: 'Marketplace',       icon: Store },
  { id: 'data-vault',   label: 'Data Vault',        icon: Database },
]

interface HistoryItem {
  research_query: string
  created_at: string
}

function stripQueryPrefix(q: string) {
  return q.replace(/^(Research Run:|Research:)\s*/i, '')
}

function formatDate(value: string) {
  try {
    return new Intl.DateTimeFormat('en-SG', { dateStyle: 'medium' }).format(new Date(value))
  } catch {
    return value
  }
}

export function Sidebar({ activeTab, onTabChange, onNewResearch }: SidebarProps) {
  const [history, setHistory] = useState<HistoryItem[]>([])

  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'
    fetch(`${apiUrl}/api/tasks/history`)
      .then((r) => r.json())
      .then((data) => setHistory((Array.isArray(data) ? data : []).slice(0, 8)))
      .catch((err) => console.error('Failed to fetch research history:', err))
  }, [])

  return (
    <aside className="flex h-screen w-[220px] shrink-0 flex-col border-r border-white/10 bg-slate-900">
      {/* Logo */}
      <div className="flex items-center gap-3 border-b border-white/10 px-4 py-5">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-white/10 p-1">
          <Image
            src="/images/synaptica-logo.png"
            alt="Synaptica"
            width={32}
            height={32}
            className="h-full w-full object-contain"
          />
        </div>
        <span className="truncate text-sm font-semibold text-white">Synaptica</span>
      </div>

      {/* New Research button */}
      <div className="px-3 pb-2 pt-4">
        <button
          type="button"
          onClick={onNewResearch}
          className="flex w-full items-center gap-2 rounded-lg bg-sky-500 px-3 py-2 text-sm font-semibold text-white transition hover:bg-sky-400"
        >
          <Plus className="h-4 w-4 shrink-0" />
          New Research
        </button>
      </div>

      {/* Nav items */}
      <nav className="space-y-0.5 px-2">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon
          const isActive = activeTab === item.id
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onTabChange(item.id)}
              className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-xs font-medium transition ${
                isActive
                  ? 'bg-white/10 text-white'
                  : 'text-slate-400 hover:bg-white/5 hover:text-white'
              }`}
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span className="truncate">{item.label}</span>
            </button>
          )
        })}
      </nav>

      {/* All Research history */}
      <div className="mt-4 flex-1 overflow-y-auto px-3 [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]">
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-widest text-slate-500">
          All Research
        </p>
        {history.length === 0 ? (
          <p className="text-[11px] text-slate-600">No research yet</p>
        ) : (
          history.map((item, i) => (
            <button
              key={i}
              type="button"
              onClick={() => onTabChange('research')}
              className="mb-1 w-full rounded-lg px-2 py-2 text-left transition hover:bg-white/5"
            >
              <p className="truncate text-[11px] text-slate-300">{stripQueryPrefix(item.research_query)}</p>
              <p className="mt-0.5 text-[10px] text-slate-600">{formatDate(item.created_at)}</p>
            </button>
          ))
        )}
      </div>

      {/* Credits */}
      <div className="border-t border-white/10 px-3 py-3">
        <div className="rounded-lg bg-white/5 p-3">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-yellow-400">
            <Zap className="h-3.5 w-3.5 shrink-0" />
            0 credits
          </div>
          <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-white/10">
            <div className="h-full w-0 rounded-full bg-sky-500" />
          </div>
          <p className="mt-1 text-[10px] text-slate-500">0 / 1000 credits used</p>
          <button
            type="button"
            className="mt-2 w-full rounded-md bg-white/10 py-1.5 text-xs text-white transition hover:bg-white/20"
          >
            Buy Credits
          </button>
        </div>
      </div>

      {/* User profile */}
      <div className="border-t border-white/10 px-3 py-3">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-sky-500/20 text-xs font-semibold text-sky-300">
            D
          </div>
          <div className="min-w-0">
            <p className="truncate text-xs font-medium text-white">Demo User</p>
            <p className="text-[10px] text-slate-500">Research Plan</p>
          </div>
        </div>
      </div>
    </aside>
  )
}
