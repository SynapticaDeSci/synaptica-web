import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface CreditsState {
  credits: number
  isLoading: boolean
  fetchCredits: () => Promise<void>
  addCredits: (n: number) => void
  deductCredits: (n: number) => void
}

export const useCreditsStore = create<CreditsState>()(
  persist(
    (set) => ({
      credits: 0,
      isLoading: false,

      fetchCredits: async () => {
        set({ isLoading: true })
        try {
          const res = await fetch('/api/credits')
          if (res.ok) {
            const data = await res.json()
            set({ credits: data.credits ?? 0 })
          }
        } catch {
          // silently fail — keep cached value
        } finally {
          set({ isLoading: false })
        }
      },

      addCredits: (n) => set((state) => ({ credits: state.credits + n })),
      deductCredits: (n) => set((state) => ({ credits: Math.max(0, state.credits - n) })),
    }),
    { name: 'synaptica-credits' }
  )
)
