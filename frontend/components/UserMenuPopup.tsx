'use client'

import { useEffect, useRef } from 'react'
import { Zap, BarChart2, Activity, Settings, Users, LogOut } from 'lucide-react'

interface UserMenuPopupProps {
  balance: number
  onClose: () => void
  onBuyCredits: () => void
}

const MAX_CREDITS = 1000

const MENU_ITEMS = [
  { icon: BarChart2, label: 'Usage' },
  { icon: Activity,  label: 'Activity' },
  { icon: Settings,  label: 'Settings' },
  { icon: Users,     label: 'Invite & Earn' },
]

export function UserMenuPopup({ balance, onClose, onBuyCredits }: UserMenuPopupProps) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleOutsideClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose()
      }
    }
    document.addEventListener('mousedown', handleOutsideClick)
    return () => document.removeEventListener('mousedown', handleOutsideClick)
  }, [onClose])

  const pct = Math.min(100, (balance / MAX_CREDITS) * 100)

  return (
    <div
      ref={ref}
      className="absolute bottom-[calc(100%+4px)] left-0 right-0 z-50
                 rounded-xl border border-white/10 bg-slate-800 p-3 shadow-2xl"
    >
      {/* Credits bar */}
      <div className="mb-2 rounded-lg bg-white/5 p-3">
        <div className="flex items-center gap-1.5">
          <Zap className="h-3.5 w-3.5 text-yellow-400" />
          <span className="text-xs font-semibold text-yellow-400">{balance} credits</span>
        </div>
        <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-white/10">
          <div
            className="h-full rounded-full bg-sky-500 transition-all duration-500"
            style={{ width: `${pct}%` }}
          />
        </div>
        <p className="mt-1 text-[10px] text-slate-500">{balance} / {MAX_CREDITS} credits used</p>

        <div className="mt-2 flex gap-2">
          <button
            onClick={() => { onBuyCredits(); onClose() }}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-md bg-white/10 py-1.5 text-xs font-medium text-white transition hover:bg-white/20"
          >
            <Zap className="h-3 w-3 text-yellow-400" />
            Buy Credits
          </button>
          <button
            className="flex flex-1 items-center justify-center gap-1.5 rounded-md bg-sky-500 py-1.5 text-xs font-semibold text-white transition hover:bg-sky-400"
          >
            Upgrade
          </button>
        </div>
      </div>

      {/* Menu items */}
      <div className="space-y-0.5">
        {MENU_ITEMS.map(({ icon: Icon, label }) => (
          <button
            key={label}
            className="flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left text-xs text-slate-300 transition hover:bg-white/5 hover:text-white"
          >
            <Icon className="h-3.5 w-3.5 shrink-0 text-slate-500" />
            {label}
          </button>
        ))}

        <div className="my-1 border-t border-white/5" />

        <button
          className="flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left text-xs text-red-400 transition hover:bg-red-500/10"
        >
          <LogOut className="h-3.5 w-3.5 shrink-0" />
          Sign out
        </button>
      </div>
    </div>
  )
}
