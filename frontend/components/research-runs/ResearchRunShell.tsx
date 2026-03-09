import Image from 'next/image'
import Link from 'next/link'

import { Button } from '@/components/ui/button'

interface ResearchRunShellProps {
  eyebrow: string
  title: string
  description: string
  children: React.ReactNode
  actions?: React.ReactNode
}

export function ResearchRunShell({
  eyebrow,
  title,
  description,
  children,
  actions,
}: ResearchRunShellProps) {
  return (
    <div className="relative min-h-screen overflow-hidden bg-slate-950 text-slate-100">
      <div className="pointer-events-none absolute inset-x-0 top-[-220px] h-[420px] bg-[radial-gradient(circle_at_top,rgba(14,165,233,0.28),transparent_58%)]" />
      <div className="pointer-events-none absolute bottom-[-160px] right-[-60px] h-[360px] w-[360px] rounded-full bg-cyan-500/10 blur-3xl" />

      <main className="relative mx-auto flex min-h-screen max-w-6xl flex-col gap-10 px-6 pb-20 pt-10 lg:px-8">
        <nav className="flex flex-wrap items-center justify-between gap-4">
          <Link href="/" className="flex items-center gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-white/10 p-2 shadow-lg shadow-sky-500/20">
              <Image
                src="/images/synaptica-logo.png"
                alt="Synaptica Logo"
                width={48}
                height={48}
                className="h-full w-full object-contain"
              />
            </div>
            <div>
              <p className="text-xl font-semibold text-white">Synaptica</p>
              <p className="text-sm text-slate-300">Deep research runs</p>
            </div>
          </Link>

          <div className="flex flex-wrap items-center gap-3">
            <Button
              asChild
              variant="outline"
              className="border-white/15 bg-white/5 text-white hover:bg-white/10 hover:text-white"
            >
              <Link href="/">Main Console</Link>
            </Button>
            {actions}
          </div>
        </nav>

        <header className="max-w-3xl space-y-5">
          <span className="inline-flex w-fit items-center rounded-full border border-sky-400/20 bg-sky-400/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.35em] text-sky-200">
            {eyebrow}
          </span>
          <div className="space-y-3">
            <h1 className="text-4xl font-semibold tracking-tight text-white md:text-5xl">{title}</h1>
            <p className="max-w-2xl text-base leading-relaxed text-slate-300 md:text-lg">
              {description}
            </p>
          </div>
        </header>

        {children}
      </main>

      <footer className="border-t border-white/10 py-8 text-center text-sm text-slate-400">
        Synaptica research runs are powered by the Phase 1C deep-research runtime.
      </footer>
    </div>
  )
}
