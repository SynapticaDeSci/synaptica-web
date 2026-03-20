import { create } from 'zustand'

interface CreditsState {
  balance: number
  isLoading: boolean
  error: string | null
  fetchCredits: () => Promise<void>
  deductCredits: (amount: number) => Promise<void>
}

export const useCreditsStore = create<CreditsState>((set) => ({
  balance: 0,
  isLoading: false,
  error: null,

  fetchCredits: async () => {
    set({ isLoading: true, error: null })
    try {
      const res = await fetch('/api/credits?user_id=default', { cache: 'no-store' })
      if (!res.ok) throw new Error('Failed to fetch credits')
      const data = await res.json()
      set({ balance: data.balance ?? 0 })
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Unknown error'
      set({ error: message })
    } finally {
      set({ isLoading: false })
    }
  },

  deductCredits: async (amount: number) => {
    set((state) => ({ balance: Math.max(0, state.balance - amount) }))
    try {
      const res = await fetch('/api/credits', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: 'default', amount }),
      })
      const data = await res.json()
      if (res.ok) set({ balance: data.balance })
    } catch {
      // optimistic value stays; will sync on next fetchCredits
    }
  },
}))
