'use client'

import { useEffect, useState } from 'react'
import Image from 'next/image'
import { useSearchParams } from 'next/navigation'
import { ChevronUp, Database, Microscope, Plus, Receipt, Store, Zap } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useCreditsStore } from '@/store/creditsStore'
import { BuyCreditsModal } from './BuyCreditsModal'
import { UserMenuPopup } from './UserMenuPopup'

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

const MAX_CREDITS = 1000

export function Sidebar({ activeTab, onTabChange, onNewResearch }: SidebarProps) {
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [menuOpen, setMenuOpen] = useState(false)
  const [buyModalOpen, setBuyModalOpen] = useState(false)

  const { balance, fetchCredits } = useCreditsStore()
  const searchParams = useSearchParams()

  // Fetch credits on mount
  useEffect(() => {
    fetchCredits()
  }, [fetchCredits])

  // Re-fetch after successful Stripe redirect
  useEffect(() => {
    if (searchParams.get('payment') === 'success') {
      fetchCredits()
      // Clean the URL without a full page reload
      const url = new URL(window.location.href)
      url.searchParams.delete('payment')
      window.history.replaceState({}, '', url.toString())
    }
  }, [searchParams, fetchCredits])

  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'
    fetch(`${apiUrl}/api/tasks/history`)
      .then((r) => r.json())
      .then((data) => setHistory((Array.isArray(data) ? data : []).slice(0, 8)))
      .catch((err) => console.error('Failed to fetch research history:', err))
  }, [])

  const creditsPct = Math.min(100, (balance / MAX_CREDITS) * 100)

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

      {/* Credits indicator */}
      <div className="border-t border-white/10 px-3 py-2">
        <div className="flex items-center gap-1.5">
          <Zap className="h-3.5 w-3.5 text-yellow-400" />
          <span className="text-xs font-semibold text-yellow-400">{balance} credits</span>
        </div>
        <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-white/10">
          <div
            className="h-full rounded-full bg-sky-500 transition-all duration-500"
            style={{ width: `${creditsPct}%` }}
          />
        </div>
      </div>

      {/* User profile — click to open popup */}
      <div className="relative border-t border-white/10 px-3 py-3">
        {menuOpen && (
          <UserMenuPopup
            balance={balance}
            onClose={() => setMenuOpen(false)}
            onBuyCredits={() => setBuyModalOpen(true)}
          />
        )}

        <button
          type="button"
          onClick={() => setMenuOpen((prev) => !prev)}
          className="flex w-full items-center gap-2 rounded-lg px-1 py-1 text-left transition hover:bg-white/5"
        >
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-sky-500/20 text-xs font-semibold text-sky-300">
            J
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-medium text-white">Jackie Tan</p>
            <p className="text-[10px] text-slate-500">Free Trial Plan</p>
          </div>
          <ChevronUp
            className={`h-3.5 w-3.5 shrink-0 text-slate-500 transition-transform duration-200 ${
              menuOpen ? '' : 'rotate-180'
            }`}
          />
        </button>
      </div>

      <BuyCreditsModal open={buyModalOpen} onOpenChange={setBuyModalOpen} />
    </aside>
  )
}
