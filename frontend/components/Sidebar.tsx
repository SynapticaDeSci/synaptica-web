'use client'

import { useEffect, useState } from 'react'
import Image from 'next/image'
import { FlaskConical, Receipt, Store, Database, Zap, Plus, User } from 'lucide-react'
import { useCreditsStore } from '@/store/creditsStore'
import { useTaskStore } from '@/store/taskStore'
import { BuyCreditsModal } from '@/components/BuyCreditsModal'

interface HistoryItem {
  id: string
  research_query: string
  created_at: string
  status: string
}

const NAV_ITEMS = [
  { id: 'console', label: 'Research Console', icon: FlaskConical },
  { id: 'transactions', label: 'Transactions', icon: Receipt },
  { id: 'marketplace', label: 'Marketplace', icon: Store },
  { id: 'data-vault', label: 'Data Vault', icon: Database },
]

interface SidebarProps {
  activeTab: string
  onTabChange: (tab: string) => void
}

export function Sidebar({ activeTab, onTabChange }: SidebarProps) {
  const { credits, fetchCredits } = useCreditsStore()
  const { reset, status } = useTaskStore()
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [buyModalOpen, setBuyModalOpen] = useState(false)

  useEffect(() => {
    fetchCredits()
  }, [fetchCredits])

  const fetchHistory = () => {
    const apiUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'
    fetch(`${apiUrl}/api/tasks/history`)
      .then((r) => r.ok ? r.json() : [])
      .then((data: HistoryItem[]) => setHistory(data.slice(0, 10)))
      .catch(() => {})
  }

  // Initial fetch
  useEffect(() => {
    fetchHistory()
  }, [])

  // Refetch when a task finishes
  useEffect(() => {
    if (status === 'COMPLETE' || status === 'FAILED') {
      const timer = setTimeout(fetchHistory, 1000)
      return () => clearTimeout(timer)
    }
  }, [status])

  const handleNewResearch = () => {
    reset()
    onTabChange('console')
  }

  const progressPct = Math.min(100, (credits / 1000) * 100)

  return (
    <>
      <aside className="fixed left-0 top-0 h-screen w-[255px] flex flex-col bg-slate-900 border-r border-white/10 z-40">
        {/* Logo */}
        <div className="flex items-center gap-3 px-5 py-5 border-b border-white/10">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-white/10 shadow-lg shadow-sky-500/20 shrink-0">
            <Image
              src="/images/synaptica-logo.png"
              alt="Synaptica Logo"
              width={36}
              height={36}
              className="h-full w-full object-contain"
            />
          </div>
          <span className="text-base font-semibold text-white">Synaptica</span>
        </div>

        {/* New Research CTA */}
        <div className="px-4 pt-4">
          <button
            onClick={handleNewResearch}
            className="flex w-full items-center gap-2 rounded-xl bg-sky-500 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-sky-400"
          >
            <Plus className="h-4 w-4" />
            New Research
          </button>
        </div>

        {/* Nav */}
        <nav className="mt-4 px-3 flex flex-col gap-0.5">
          {NAV_ITEMS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => onTabChange(id)}
              className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-all ${
                activeTab === id
                  ? 'bg-white/10 text-white font-medium'
                  : 'text-slate-400 hover:bg-white/5 hover:text-slate-200'
              }`}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {label}
            </button>
          ))}
        </nav>

        {/* Research History */}
        {history.length > 0 && (
          <div className="mt-5 px-4 flex flex-col gap-1">
            <p className="text-[10px] uppercase tracking-[0.2em] text-slate-500 mb-1">
              All Research
            </p>
            {history.map((item) => (
              <div
                key={item.id}
                className="rounded-lg px-3 py-2 text-xs text-slate-400 hover:bg-white/5 hover:text-slate-200 cursor-default transition-colors"
              >
                <p className="truncate leading-tight">
                  {item.research_query.replace(/^Research:\s*/i, '')}
                </p>
                <p className="text-[10px] text-slate-600 mt-0.5">
                  {new Date(item.created_at).toLocaleDateString()}
                </p>
              </div>
            ))}
          </div>
        )}

        <div className="flex-1" />

        {/* Credits Panel */}
        <div className="mx-4 mb-3 rounded-xl border border-white/10 bg-white/5 p-3">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-1.5 text-sm font-medium text-white">
              <Zap className="h-4 w-4 text-yellow-400" />
              {credits} credits
            </div>
          </div>
          <div className="h-1.5 w-full rounded-full bg-white/10 overflow-hidden">
            <div
              className="h-full rounded-full bg-gradient-to-r from-sky-500 to-blue-400 transition-all"
              style={{ width: `${progressPct}%` }}
            />
          </div>
          <p className="text-[10px] text-slate-500 mt-1">{credits} / 1000 credits used</p>
          <button
            onClick={() => setBuyModalOpen(true)}
            className="mt-2 w-full rounded-lg bg-white/10 px-3 py-1.5 text-xs font-medium text-slate-200 transition hover:bg-white/20"
          >
            Buy Credits
          </button>
        </div>

        {/* User Profile */}
        <div className="flex items-center gap-3 border-t border-white/10 px-5 py-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-sky-500/20 text-sky-300 shrink-0">
            <User className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium text-white truncate">Demo User</p>
            <p className="text-xs text-slate-500">Research Plan</p>
          </div>
        </div>
      </aside>

      <BuyCreditsModal open={buyModalOpen} onOpenChange={setBuyModalOpen} />
    </>
  )
}
