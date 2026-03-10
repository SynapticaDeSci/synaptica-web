'use client'

import { useRouter } from 'next/navigation'
import { useMutation } from '@tanstack/react-query'

import { createResearchRun } from '@/lib/api'
import { ResearchRunForm } from '@/components/research-runs/ResearchRunForm'
import { ResearchRunShell } from '@/components/research-runs/ResearchRunShell'

export default function ResearchRunsPage() {
  const router = useRouter()

  const createMutation = useMutation({
    mutationFn: createResearchRun,
    onSuccess: (researchRun) => {
      router.push(`/research-runs/${researchRun.id}`)
    },
  })

  return (
    <ResearchRunShell
      eyebrow="Phase 1C"
      title="Deep research runs are live"
      description="Create a freshness-aware research run, watch the six-node backbone execute, and inspect evidence, critique, and revision from a dedicated detail page."
    >
      <ResearchRunForm
        onSubmit={async (request) => {
          await createMutation.mutateAsync(request)
        }}
        isSubmitting={createMutation.isPending}
        error={createMutation.error instanceof Error ? createMutation.error.message : null}
      />
    </ResearchRunShell>
  )
}
