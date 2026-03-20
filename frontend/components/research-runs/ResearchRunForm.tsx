'use client'

import { useState, type FormEvent } from 'react'
import { ArrowRight, Layers3, Network, ShieldCheck, Sparkles } from 'lucide-react'

import type { CreateResearchRunRequest } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

interface ResearchRunFormProps {
  onSubmit: (request: CreateResearchRunRequest) => Promise<void>
  isSubmitting: boolean
  error?: string | null
}

const fixedSteps = [
  {
    title: 'Query planning',
    description: 'Auto-classifies the brief, sets freshness rules, and expands the investigation plan.',
    icon: Sparkles,
  },
  {
    title: 'Evidence gathering',
    description: 'Runs bounded scout searches across fresh web, official, and literature-oriented sources.',
    icon: Network,
  },
  {
    title: 'Source curation',
    description: 'Deduplicates evidence, checks freshness, and assesses source quality before synthesis.',
    icon: ShieldCheck,
  },
  {
    title: 'Draft, critique, revise',
    description: 'Builds a draft answer, runs a critic pass, and revises into a citation-backed final answer.',
    icon: Layers3,
  },
]

export function ResearchRunForm({
  onSubmit,
  isSubmitting,
  error,
}: ResearchRunFormProps) {
  const [description, setDescription] = useState('')
  const [budgetLimit, setBudgetLimit] = useState('25')
  const [validationError, setValidationError] = useState<string | null>(null)

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()

    if (!description.trim()) {
      setValidationError('Please describe the research run you want to execute.')
      return
    }

    const trimmedBudget = budgetLimit.trim()
    const parsedBudget = trimmedBudget ? Number.parseFloat(trimmedBudget) : undefined
    if (
      trimmedBudget &&
      (parsedBudget === undefined || !Number.isFinite(parsedBudget) || parsedBudget <= 0)
    ) {
      setValidationError('Budget limit must be a positive number when provided.')
      return
    }

    setValidationError(null)
    await onSubmit({
      description: description.trim(),
      budget_limit: parsedBudget,
    })
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1.15fr_0.85fr]">
      <Card className="overflow-hidden rounded-[28px] border border-white/15 bg-white/95 shadow-[0_40px_100px_-50px_rgba(56,189,248,0.8)]">
        <CardHeader className="space-y-4 border-b border-slate-100 pb-6">
          <span className="inline-flex w-fit items-center rounded-full border border-sky-100 bg-sky-50 px-3 py-1 text-xs font-semibold uppercase tracking-[0.35em] text-sky-700">
            Deep research run
          </span>
          <div className="space-y-2">
            <CardTitle className="text-3xl text-slate-950">Launch a research run</CardTitle>
            <CardDescription className="text-base leading-relaxed text-slate-500">
              Describe your research question. The platform will automatically determine the best approach, gather evidence, and produce a citation-backed answer.
            </CardDescription>
          </div>
        </CardHeader>

        <CardContent className="pt-6">
          <form className="space-y-6" onSubmit={handleSubmit}>
            <div className="space-y-3">
              <label htmlFor="research-run-description" className="text-sm font-medium text-slate-700">
                Research brief
              </label>
              <Textarea
                id="research-run-description"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                rows={8}
                placeholder="Example: Review literature on autonomous agent payments in DeSci, identify verification patterns, and summarize the strongest implementation tradeoffs."
                className="min-h-[180px] rounded-2xl border-slate-200 px-4 py-3 text-slate-700 shadow-inner focus:border-sky-400 focus:ring-sky-300/40"
                disabled={isSubmitting}
              />
              <p className="text-xs text-slate-400">
                Include the domain, desired output, and any sources or constraints that matter.
              </p>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-3">
                <label htmlFor="research-run-budget" className="text-sm font-medium text-slate-700">
                  Budget limit (USD)
                </label>
                <Input
                  id="research-run-budget"
                  type="number"
                  value={budgetLimit}
                  onChange={(event) => setBudgetLimit(event.target.value)}
                  min="0.01"
                  step="0.01"
                  className="rounded-2xl border-slate-200 px-4 py-3 text-slate-700 shadow-inner focus:border-sky-400 focus:ring-sky-300/40"
                  disabled={isSubmitting}
                />
              </div>
            </div>

            {(validationError || error) && (
              <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {validationError || error}
              </div>
            )}

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-5">
              <p className="max-w-xl text-sm text-slate-500">
                Synaptica will auto-detect the best research approach, gather evidence, and produce a citation-backed answer.
              </p>
              <Button
                type="submit"
                disabled={isSubmitting}
                className="rounded-full bg-gradient-to-r from-sky-500 via-cyan-500 to-teal-500 px-6 py-5 text-sm font-semibold text-white shadow-lg shadow-sky-500/25 hover:opacity-95"
              >
                {isSubmitting ? 'Launching…' : 'Launch research run'}
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <Card className="rounded-[28px] border border-white/15 bg-slate-900/70 text-slate-100 shadow-[0_40px_100px_-60px_rgba(16,185,129,0.5)] backdrop-blur-xl">
        <CardHeader className="space-y-3">
          <span className="inline-flex w-fit items-center rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.35em] text-emerald-200">
            How it works
          </span>
          <CardTitle className="text-2xl text-white">Automated research pipeline</CardTitle>
          <CardDescription className="text-slate-300">
            Your query runs through a graph-backed workflow with freshness-aware evidence gathering and a bounded critique/revision loop.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {fixedSteps.map((step, index) => {
            const Icon = step.icon
            return (
              <div
                key={step.title}
                className="rounded-2xl border border-white/10 bg-white/5 p-4 transition hover:bg-white/10"
              >
                <div className="mb-2 flex items-center gap-3">
                  <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-white/10 text-xs font-semibold text-white">
                    {index + 1}
                  </span>
                  <Icon className="h-4 w-4 text-sky-300" />
                  <p className="font-medium text-white">{step.title}</p>
                </div>
                <p className="text-sm leading-relaxed text-slate-300">{step.description}</p>
              </div>
            )
          })}
        </CardContent>
      </Card>
    </div>
  )
}
