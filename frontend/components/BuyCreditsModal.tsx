'use client'

import { useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { Zap, X, Loader2 } from 'lucide-react'

interface Tier {
  credits: number
  price: string
  label: string
  popular?: boolean
}

const TIERS: Tier[] = [
  { credits: 10,  price: '$1.00',  label: 'Starter' },
  { credits: 50,  price: '$4.00',  label: 'Basic' },
  { credits: 100, price: '$7.00',  label: 'Pro', popular: true },
  { credits: 500, price: '$30.00', label: 'Power' },
]

interface BuyCreditsModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function BuyCreditsModal({ open, onOpenChange }: BuyCreditsModalProps) {
  const [loadingTier, setLoadingTier] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleBuy = async (tier: Tier) => {
    setLoadingTier(tier.credits)
    setError(null)
    try {
      const res = await fetch('/api/credits', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ credits: tier.credits, user_id: 'default' }),
      })
      const data = await res.json()
      if (!res.ok || !data.checkout_url) {
        throw new Error(data.error || 'Failed to start checkout')
      }
      window.location.href = data.checkout_url
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Unknown error'
      setError(message)
      setLoadingTier(null)
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={(v) => { if (!v) setError(null); onOpenChange(v) }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2
                     rounded-2xl border border-white/10 bg-slate-900 p-6 shadow-2xl"
        >
          {/* Header */}
          <div className="mb-5 flex items-start justify-between">
            <div>
              <Dialog.Title className="flex items-center gap-2 text-base font-semibold text-white">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-yellow-400/10">
                  <Zap className="h-4 w-4 text-yellow-400" />
                </span>
                Buy Credits
              </Dialog.Title>
              <Dialog.Description className="mt-0.5 text-xs text-slate-500">
                Top up your credits instantly
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button className="rounded-md p-1 text-slate-400 transition hover:bg-white/5 hover:text-white">
                <X className="h-4 w-4" />
              </button>
            </Dialog.Close>
          </div>

          {error && (
            <p className="mb-4 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-400">
              {error}
            </p>
          )}

          {/* Tier grid */}
          <div className="grid grid-cols-2 gap-3">
            {TIERS.map((tier) => (
              <button
                key={tier.credits}
                onClick={() => handleBuy(tier)}
                disabled={loadingTier !== null}
                className={`relative flex flex-col items-center justify-center rounded-xl border p-4 text-center transition
                  ${tier.popular
                    ? 'border-sky-500/50 bg-sky-500/10 hover:bg-sky-500/20'
                    : 'border-white/10 bg-white/5 hover:bg-white/10'
                  }
                  disabled:cursor-not-allowed disabled:opacity-50`}
              >
                {tier.popular && (
                  <span className="absolute -top-2.5 left-1/2 -translate-x-1/2 rounded-full bg-sky-500 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-white">
                    Popular
                  </span>
                )}
                {loadingTier === tier.credits ? (
                  <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
                ) : (
                  <>
                    <div className="flex items-center gap-1">
                      <Zap className="h-3.5 w-3.5 text-yellow-400" />
                      <span className="text-xl font-bold text-white">{tier.credits}</span>
                    </div>
                    <span className="mt-2 text-sm font-semibold text-sky-400">{tier.price}</span>
                    <span className="text-[10px] text-slate-500">{tier.label}</span>
                  </>
                )}
              </button>
            ))}
          </div>

          <p className="mt-5 text-center text-[10px] text-slate-600">
            Powered by Stripe &bull; Secure payment &bull; Credits never expire &bull; 1 credit = 1 research iteration
          </p>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
