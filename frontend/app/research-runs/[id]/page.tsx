import Link from 'next/link'

import { Button } from '@/components/ui/button'
import { ResearchRunDetailView } from '@/components/research-runs/ResearchRunDetailView'
import { ResearchRunShell } from '@/components/research-runs/ResearchRunShell'

export default function ResearchRunDetailPage({
  params,
}: {
  params: { id: string }
}) {
  return (
    <ResearchRunShell
      eyebrow="Live detail"
      title="Monitor your research run"
      description="This page polls the backend every two seconds until the run settles, exposes node-level attempts, and bridges human review through the existing task verification endpoints."
      actions={
        <Button
          asChild
          variant="outline"
          className="border-white/15 bg-white/5 text-white hover:bg-white/10 hover:text-white"
        >
          <Link href="/research-runs">New research run</Link>
        </Button>
      }
    >
      <ResearchRunDetailView researchRunId={params.id} />
    </ResearchRunShell>
  )
}
