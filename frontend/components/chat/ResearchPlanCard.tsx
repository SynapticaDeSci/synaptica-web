'use client'

import { useState } from 'react'
import {
  ArrowRight,
  ChevronDown,
  ChevronUp,
  ClipboardList,
  MessageSquare,
  Zap,
} from 'lucide-react'
import type { ResearchPlan } from '@/store/chatStore'
import { useCreditsStore } from '@/store/creditsStore'

interface ResearchPlanCardProps {
  plan: ResearchPlan
  onApprove: (plan: ResearchPlan, creditBudget: number | null) => void
  onRefine: () => void
  onBuyCredits: () => void
  isLaunching: boolean
  launchError: string | null
}

export function ResearchPlanCard({
  plan,
  onApprove,
  onRefine,
  onBuyCredits,
  isLaunching,
  launchError,
}: ResearchPlanCardProps) {
  const [showSettings, setShowSettings] = useState(false)
  const [noLimit, setNoLimit] = useState(false)
  const [editBudget, setEditBudget] = useState('40')
  const balance = useCreditsStore((s) => s.balance)

  const creditBudget = noLimit ? null : (parseInt(editBudget, 10) || 0)
  const insufficientCredits = creditBudget !== null && creditBudget > balance

  const handleApprove = () => {
    onApprove(plan, creditBudget)
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-sky-500/20 bg-gradient-to-b from-sky-500/5 to-transparent">
      {/* Header */}
      <div className="border-b border-white/5 px-5 py-4">
        <div className="flex items-start gap-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-sky-500/15">
            <ClipboardList className="h-4 w-4 text-sky-400" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold uppercase tracking-[0.3em] text-sky-400">
              Research Plan
            </p>
            <h3 className="mt-1 text-base font-semibold text-white">{plan.title}</h3>
          </div>
        </div>
      </div>

      {/* Description */}
      <div className="border-b border-white/5 px-5 py-4">
        <p className="text-sm leading-relaxed text-slate-300">{plan.description}</p>
      </div>

      {/* Plan steps */}
      <div className="border-b border-white/5 px-5 py-4">
        <p className="mb-3 text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">
          Investigation steps
        </p>
        <ol className="space-y-2">
          {plan.plan_steps.map((step, i) => (
            <li key={i} className="flex gap-3 text-sm text-slate-300">
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-sky-500/15 text-[10px] font-bold text-sky-400">
                {i + 1}
              </span>
              <span className="leading-relaxed">{step}</span>
            </li>
          ))}
        </ol>
      </div>

      {/* Credit budget badge + balance */}
      <div className="flex flex-wrap items-center gap-2 border-b border-white/5 px-5 py-3">
        <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-500/10 px-3 py-1 text-xs text-amber-200">
          <Zap className="h-3 w-3" />
          {noLimit ? 'No limit' : `${creditBudget} credits`}
        </span>
        <span className="text-xs text-slate-500">
          You have {balance} credits
        </span>
      </div>

      {/* Editable settings (collapsible) */}
      <div className="border-b border-white/5">
        <button
          type="button"
          onClick={() => setShowSettings(!showSettings)}
          className="flex w-full items-center justify-between px-5 py-3 text-xs text-slate-400 transition hover:text-slate-300"
        >
          <span>Adjust settings</span>
          {showSettings ? (
            <ChevronUp className="h-3.5 w-3.5" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5" />
          )}
        </button>
        {showSettings && (
          <div className="space-y-3 px-5 pb-4">
            <div className="space-y-2">
              <label className="text-xs font-medium text-slate-400">Credit budget</label>
              <div className="flex items-center gap-3">
                <input
                  type="number"
                  value={editBudget}
                  onChange={(e) => setEditBudget(e.target.value)}
                  min="1"
                  step="1"
                  disabled={noLimit}
                  className="w-full max-w-[140px] rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white outline-none focus:border-sky-400/50 disabled:opacity-40"
                />
                <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={noLimit}
                    onChange={(e) => setNoLimit(e.target.checked)}
                    className="rounded border-white/20 bg-white/5 text-sky-500 focus:ring-sky-500/30"
                  />
                  No limit
                </label>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Insufficient credits warning */}
      {insufficientCredits && (
        <div className="flex items-center justify-between border-b border-amber-500/20 bg-amber-500/5 px-5 py-3">
          <span className="text-sm text-amber-300">
            Not enough credits ({balance} available, {creditBudget} needed)
          </span>
          <button
            type="button"
            onClick={onBuyCredits}
            className="rounded-full bg-amber-500/20 px-3 py-1 text-xs font-medium text-amber-200 transition hover:bg-amber-500/30"
          >
            Buy credits
          </button>
        </div>
      )}

      {/* Error */}
      {launchError && (
        <div className="border-b border-red-500/20 bg-red-500/5 px-5 py-3 text-sm text-red-400">
          {launchError}
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-3 px-5 py-4">
        <button
          type="button"
          onClick={handleApprove}
          disabled={isLaunching || insufficientCredits}
          className="flex items-center gap-2 rounded-full bg-gradient-to-r from-sky-500 via-cyan-500 to-teal-500 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-sky-500/25 transition hover:opacity-90 disabled:opacity-50"
        >
          {isLaunching ? 'Launching...' : 'Approve & Start Research'}
          <ArrowRight className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={onRefine}
          disabled={isLaunching}
          className="flex items-center gap-2 rounded-full border border-white/10 px-4 py-2.5 text-sm text-slate-300 transition hover:bg-white/5 disabled:opacity-50"
        >
          <MessageSquare className="h-4 w-4" />
          Refine further
        </button>
      </div>
    </div>
  )
}
