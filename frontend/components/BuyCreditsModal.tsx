'use client'

import { useState } from 'react'
import { Check } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'

const TIERS = [
  { credits: 10, price: 15, label: 'Starter' },
  { credits: 100, price: 150, label: 'Pro', popular: true },
  { credits: 500, price: 750, label: 'Team' },
  { credits: 1000, price: 1500, label: 'Enterprise' },
]

interface BuyCreditsModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function BuyCreditsModal({ open, onOpenChange }: BuyCreditsModalProps) {
  const [selected, setSelected] = useState(TIERS[1])
  const [isLoading, setIsLoading] = useState(false)

  const handleCheckout = async () => {
    setIsLoading(true)
    try {
      const res = await fetch('/api/credits', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ credits: selected.credits }),
      })
      const data = await res.json()
      if (data.session_url) {
        window.location.href = data.session_url
      } else {
        console.error('No session_url returned:', data)
      }
    } catch (err) {
      console.error('Checkout error:', err)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg border-white/10 bg-slate-900 text-white">
        <DialogHeader>
          <DialogTitle className="text-xl text-white">Buy Credits</DialogTitle>
          <DialogDescription className="text-slate-400">
            Select a credit bundle to continue your research.
          </DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-2 gap-3 mt-2">
          {TIERS.map((tier) => (
            <button
              key={tier.credits}
              onClick={() => setSelected(tier)}
              className={`relative flex flex-col gap-1 rounded-xl border p-4 text-left transition-all ${
                selected.credits === tier.credits
                  ? 'border-sky-400 bg-sky-500/10 ring-1 ring-sky-400'
                  : 'border-white/10 bg-white/5 hover:border-white/20'
              }`}
            >
              {tier.popular && (
                <span className="absolute right-2 top-2 rounded-full bg-sky-500 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white">
                  Popular
                </span>
              )}
              <span className="text-xs font-medium uppercase tracking-wider text-slate-400">
                {tier.label}
              </span>
              <span className="text-2xl font-bold text-white">{tier.credits}</span>
              <span className="text-sm text-slate-300">credits</span>
              <span className="mt-1 text-lg font-semibold text-sky-300">${tier.price}</span>
              {selected.credits === tier.credits && (
                <Check className="absolute bottom-3 right-3 h-4 w-4 text-sky-400" />
              )}
            </button>
          ))}
        </div>

        <p className="text-xs text-slate-500 text-center mt-1">
          1 credit = 1 research iteration. Credits never expire.
        </p>

        <div className="flex gap-3 mt-2">
          <Button
            variant="outline"
            className="flex-1 border-white/10 text-slate-300 hover:bg-white/5"
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            className="flex-1 bg-sky-500 hover:bg-sky-400 text-white"
            onClick={handleCheckout}
            disabled={isLoading}
          >
            {isLoading ? 'Redirecting…' : `Proceed to Payment · $${selected.price}`}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
