'use client'

import { useEffect, useMemo, useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { cn } from '@/lib/utils'
import {
  AgentSubmissionPayload,
  AgentSubmissionResponse,
  submitAgent,
} from '@/lib/api'
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Copy,
  ExternalLink,
  Sparkles,
} from 'lucide-react'

interface AddAgentModalProps {
  onSuccess?: (agent: AgentSubmissionResponse) => void
}

interface AgentFormValues {
  name: string
  description: string
  capabilitiesRaw: string
  categoriesRaw: string
  endpointUrl: string
  healthCheckUrl: string
  baseRate: string
  rateType: string
  hederaAccount: string
  logoUrl: string
  contactEmail: string
}

const emptyForm: AgentFormValues = {
  name: '',
  description: '',
  capabilitiesRaw: '',
  categoriesRaw: '',
  endpointUrl: '',
  healthCheckUrl: '',
  baseRate: '',
  rateType: 'per_task',
  hederaAccount: '',
  logoUrl: '',
  contactEmail: '',
}

function generateSlug(value: string): string {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 50)
}

function parseList(value: string): string[] {
  return value
    .split(/[\n,]+/)
    .map((entry) => entry.trim())
    .filter(Boolean)
}

function buildPayload(values: AgentFormValues): AgentSubmissionPayload {
  const baseRate = parseFloat(values.baseRate)
  if (Number.isNaN(baseRate) || baseRate <= 0) {
    throw new Error('Base rate must be a positive number.')
  }

  let agentId = generateSlug(values.name)
  if (agentId.length < 3) {
    agentId = `agent-${Date.now()}`
  }

  const payload: AgentSubmissionPayload = {
    agent_id: agentId,
    name: values.name.trim(),
    description: values.description.trim(),
    capabilities: parseList(values.capabilitiesRaw),
    endpoint_url: values.endpointUrl.trim(),
    base_rate: baseRate,
    currency: 'HBAR',
    rate_type: values.rateType.trim() || 'per_task',
  }

  const categories = parseList(values.categoriesRaw)
  if (categories.length) {
    payload.categories = categories
  }
  if (values.healthCheckUrl.trim()) {
    payload.health_check_url = values.healthCheckUrl.trim()
  }
  if (values.hederaAccount.trim()) {
    payload.hedera_account = values.hederaAccount.trim()
  }
  if (values.logoUrl.trim()) {
    payload.logo_url = values.logoUrl.trim()
  }
  if (values.contactEmail.trim()) {
    payload.contact_email = values.contactEmail.trim()
  }

  return payload
}

export function AddAgentModal({ onSuccess }: AddAgentModalProps) {
  const [open, setOpen] = useState(false)
  const [step, setStep] = useState(0)
  const [formValues, setFormValues] = useState<AgentFormValues>(emptyForm)
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [result, setResult] = useState<AgentSubmissionResponse | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!open) {
      setStep(0)
      setFormValues(emptyForm)
      setError(null)
      setIsSubmitting(false)
      setResult(null)
      setCopied(false)
    }
  }, [open])

  const canProceedStep0 = useMemo(() => {
    const slug = generateSlug(formValues.name)
    return (
      formValues.name.trim().length >= 3 &&
      slug.length >= 3 &&
      formValues.description.trim().length >= 10 &&
      parseList(formValues.capabilitiesRaw).length > 0
    )
  }, [formValues])

  const canProceedStep1 = useMemo(() => {
    const baseRate = parseFloat(formValues.baseRate)
    return (
      formValues.endpointUrl.trim().length > 0 &&
      !Number.isNaN(baseRate) &&
      baseRate > 0
    )
  }, [formValues])

  const handleNext = () => {
    setError(null)
    if (step === 0 && !canProceedStep0) {
      setError('Please complete all required fields before continuing.')
      return
    }
    if (step === 1 && !canProceedStep1) {
      setError('Provide a valid HTTPS endpoint and positive base rate.')
      return
    }
    setStep((prev) => Math.min(prev + 1, 1))
  }

  const handlePrevious = () => {
    setError(null)
    setStep((prev) => Math.max(prev - 1, 0))
  }

  const handleSubmit = async () => {
    setError(null)
    setIsSubmitting(true)
    try {
      const payload = buildPayload(formValues)
      const submission = await submitAgent(payload)
      setResult(submission)
      setStep(2)
      setIsSubmitting(false)
      setCopied(false)
      if (onSuccess) {
        onSuccess(submission)
      }
    } catch (err: any) {
      setIsSubmitting(false)
      setError(err.message || 'Failed to submit agent')
    }
  }

  const handleCopyMetadata = async () => {
    if (!result?.metadata_gateway_url) return
    try {
      await navigator.clipboard.writeText(result.metadata_gateway_url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  const renderStepContent = () => {
    const slug = generateSlug(formValues.name || '')
    const descriptionTooShort = formValues.description.trim().length > 0 && formValues.description.trim().length < 10
    if (step === 2 && result) {
      return (
        <div className="space-y-6">
          <div className="flex items-center gap-3 rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-4">
            <CheckCircle2 className="h-6 w-6 text-emerald-500" />
            <div>
              <p className="text-sm font-semibold text-emerald-300">
                Agent submitted successfully
              </p>
              <p className="text-sm text-slate-200">
                {result.message}
              </p>
            </div>
          </div>

          <div className="rounded-2xl border border-white/10 bg-slate-900/50 p-4">
            <h3 className="text-lg font-semibold text-white">{result.name}</h3>
            <p className="mt-2 text-sm text-slate-300">{result.description}</p>
            <div className="mt-4 grid gap-2 text-sm text-slate-300">
              <div>
                <span className="font-medium text-slate-100">Capabilities: </span>
                {result.capabilities.join(', ')}
              </div>
              <div>
                <span className="font-medium text-slate-100">Pricing: </span>
                {result.pricing.rate} {result.pricing.currency} ({result.pricing.rate_type})
              </div>
              {result.metadata_gateway_url && (
                <div className="flex items-center gap-2">
                  <span className="font-medium text-slate-100">Metadata:</span>
                  <a
                    href={result.metadata_gateway_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-sky-400 hover:text-sky-200"
                  >
                    View on Pinata
                    <ExternalLink className="h-4 w-4" />
                  </a>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleCopyMetadata}
                    className="flex items-center gap-1 text-xs"
                  >
                    <Copy className="h-4 w-4" />
                    {copied ? 'Copied!' : 'Copy'}
                  </Button>
                </div>
              )}
            </div>
          </div>

          <div className="rounded-2xl border border-white/10 bg-slate-900/50 p-4">
            <h4 className="text-sm font-semibold uppercase tracking-[0.25em] text-slate-400">
              Operator Checklist
            </h4>
            <ul className="mt-3 space-y-2 text-sm text-slate-300">
              {result.operator_checklist.map((item) => (
                <li key={item} className="flex items-start gap-2">
                  <Sparkles className="mt-0.5 h-4 w-4 text-sky-400" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )
    }

    const showStep0 = step === 0

    return (
      <div className="space-y-6">
        {showStep0 ? (
          <>
            <div>
              <h3 className="text-sm font-semibold uppercase tracking-[0.35em] text-slate-400">
                Agent Basics
              </h3>
              <p className="mt-2 text-sm text-slate-300">
                Choose a unique agent_id slug and describe what your agent does. Capabilities should be specific tasks your agent performs.
              </p>
            </div>
            <div className="grid gap-4">
              <div className="grid gap-2">
                <label className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-400">
                  Display Name
                </label>
                <Input
                  placeholder="Market Insights Pro"
                  value={formValues.name}
                  onChange={(event) => {
                    const name = event.target.value
                    setFormValues((prev) => ({ ...prev, name }))
                  }}
                  className="rounded-2xl border border-white/20 bg-slate-900/70 px-4 py-3 text-sm text-slate-100 placeholder:text-slate-500 focus-visible:ring-2 focus-visible:ring-sky-500/60 focus-visible:ring-offset-0"
                />
              </div>
              <div className="grid gap-2">
                <label className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-400">
                  Agent ID (auto-generated)
                </label>
                <Input
                  value={slug || 'pending-name'}
                  readOnly
                  className="rounded-2xl border border-dashed border-white/20 bg-slate-900/40 px-4 py-3 text-sm text-slate-300"
                />
                <p className="text-xs text-slate-400">
                  Slug updates as you type the display name. Minimum 3 characters; we’ll ensure uniqueness automatically.
                </p>
                {slug.length > 0 && slug.length < 3 && (
                  <p className="text-xs text-rose-300">Display name must create a slug with at least 3 characters.</p>
                )}
              </div>
              <div className="grid gap-2">
                <label className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-400">
                  Description
                </label>
                <Textarea
                  rows={4}
                  placeholder="Summarize what your agent does and the problems it solves."
                  value={formValues.description}
                  onChange={(event) =>
                    setFormValues((prev) => ({ ...prev, description: event.target.value }))
                  }
                  className="rounded-2xl border border-white/20 bg-slate-900/70 px-4 py-3 text-sm text-slate-100 placeholder:text-slate-500 focus-visible:ring-2 focus-visible:ring-sky-500/60 focus-visible:ring-offset-0"
                />
                {descriptionTooShort && (
                  <p className="text-xs text-rose-300">Description must be at least 10 characters.</p>
                )}
              </div>
              <div className="grid gap-2">
                <label className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-400">
                  Capabilities (one per line)
                </label>
                <Textarea
                  rows={3}
                  placeholder="Trend analysis
Dataset aggregation
Insight synthesis"
                  value={formValues.capabilitiesRaw}
                  onChange={(event) =>
                    setFormValues((prev) => ({ ...prev, capabilitiesRaw: event.target.value }))
                  }
                  className="rounded-2xl border border-white/20 bg-slate-900/70 px-4 py-3 text-sm text-slate-100 placeholder:text-slate-500 focus-visible:ring-2 focus-visible:ring-sky-500/60 focus-visible:ring-offset-0"
                />
              </div>
              <div className="grid gap-2">
                <label className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-400">
                  Categories (comma or newline separated)
                </label>
                <Textarea
                  rows={2}
                  placeholder="Market Research, Data Collection"
                  value={formValues.categoriesRaw}
                  onChange={(event) =>
                    setFormValues((prev) => ({ ...prev, categoriesRaw: event.target.value }))
                  }
                  className="rounded-2xl border border-white/20 bg-slate-900/70 px-4 py-3 text-sm text-slate-100 placeholder:text-slate-500 focus-visible:ring-2 focus-visible:ring-sky-500/60 focus-visible:ring-offset-0"
                />
              </div>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="grid gap-2">
                  <label className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-400">
                    Contact Email (optional)
                  </label>
                  <Input
                    placeholder="team@youragent.com"
                    value={formValues.contactEmail}
                    onChange={(event) =>
                      setFormValues((prev) => ({ ...prev, contactEmail: event.target.value }))
                    }
                    className="rounded-2xl border border-white/20 bg-slate-900/70 px-4 py-3 text-sm text-slate-100 placeholder:text-slate-500 focus-visible:ring-2 focus-visible:ring-sky-500/60 focus-visible:ring-offset-0"
                  />
                </div>
                <div className="grid gap-2">
                  <label className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-400">
                    Logo URL (optional)
                  </label>
                  <Input
                    placeholder="https://example.com/logo.png"
                    value={formValues.logoUrl}
                    onChange={(event) =>
                      setFormValues((prev) => ({ ...prev, logoUrl: event.target.value }))
                    }
                    className="rounded-2xl border border-white/20 bg-slate-900/70 px-4 py-3 text-sm text-slate-100 placeholder:text-slate-500 focus-visible:ring-2 focus-visible:ring-sky-500/60 focus-visible:ring-offset-0"
                  />
                </div>
              </div>
            </div>
          </>
        ) : (
          <>
            <div>
              <h3 className="text-sm font-semibold uppercase tracking-[0.35em] text-slate-400">
                Endpoint & Pricing
              </h3>
              <p className="mt-2 text-sm text-slate-300">
                Provide the HTTPS endpoint that executes your agent. Pricing is denominated in HBAR and used by the negotiator to propose payments.
              </p>
            </div>
            <div className="grid gap-4">
              <div className="grid gap-2">
                <label className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-400">
                  Endpoint URL
                </label>
                <Input
                  placeholder="https://api.youragent.com/execute"
                  value={formValues.endpointUrl}
                  onChange={(event) =>
                    setFormValues((prev) => ({ ...prev, endpointUrl: event.target.value }))
                  }
                  className="rounded-2xl border border-white/20 bg-slate-900/70 px-4 py-3 text-sm text-slate-100 placeholder:text-slate-500 focus-visible:ring-2 focus-visible:ring-sky-500/60 focus-visible:ring-offset-0"
                />
              </div>
              <div className="grid gap-2">
                <label className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-400">
                  Health Check URL (optional)
                </label>
                <Input
                  placeholder="https://api.youragent.com/health"
                  value={formValues.healthCheckUrl}
                  onChange={(event) =>
                    setFormValues((prev) => ({ ...prev, healthCheckUrl: event.target.value }))
                  }
                  className="rounded-2xl border border-white/20 bg-slate-900/70 px-4 py-3 text-sm text-slate-100 placeholder:text-slate-500 focus-visible:ring-2 focus-visible:ring-sky-500/60 focus-visible:ring-offset-0"
                />
              </div>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <div className="grid gap-2">
                  <label className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-400">
                    Base Rate
                  </label>
                  <Input
                    type="number"
                    min="0"
                    step="0.01"
                    value={formValues.baseRate}
                    onChange={(event) =>
                      setFormValues((prev) => ({ ...prev, baseRate: event.target.value }))
                    }
                    className="rounded-2xl border border-white/20 bg-slate-900/70 px-4 py-3 text-sm text-slate-100 placeholder:text-slate-500 focus-visible:ring-2 focus-visible:ring-sky-500/60 focus-visible:ring-offset-0"
                  />
                </div>
                <div className="grid gap-2">
                  <label className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-400">
                    Rate Type
                  </label>
                  <Input
                    value={formValues.rateType}
                    onChange={(event) =>
                      setFormValues((prev) => ({ ...prev, rateType: event.target.value }))
                    }
                    className="rounded-2xl border border-white/20 bg-slate-900/70 px-4 py-3 text-sm text-slate-100 placeholder:text-slate-500 focus-visible:ring-2 focus-visible:ring-sky-500/60 focus-visible:ring-offset-0"
                  />
                </div>
              </div>
              <div className="grid gap-2">
                <label className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-400">
                  Hedera Account (optional)
                </label>
                <Input
                  placeholder="0.0.123456 or 0x..."
                  value={formValues.hederaAccount}
                  onChange={(event) =>
                    setFormValues((prev) => ({ ...prev, hederaAccount: event.target.value }))
                  }
                  className="rounded-2xl border border-white/20 bg-slate-900/70 px-4 py-3 text-sm text-slate-100 placeholder:text-slate-500 focus-visible:ring-2 focus-visible:ring-sky-500/60 focus-visible:ring-offset-0"
                />
              </div>
            </div>
          </>
        )}
      </div>
    )
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button className="flex w-full items-center justify-center gap-2 rounded-full bg-sky-500 px-4 py-2 text-sm font-semibold text-white shadow-lg hover:bg-sky-400">
          <Sparkles className="h-4 w-4" />
          Add Agent
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-3xl border border-white/10 bg-slate-950/95 text-slate-100">
        <DialogHeader>
          <DialogTitle>Add Your Agent</DialogTitle>
          <DialogDescription className="text-slate-300">
            Publish an HTTP agent to the marketplace. Metadata uploads to Pinata automatically after submission.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-6">
          <div className="flex items-center gap-3 text-xs font-semibold uppercase tracking-[0.3em] text-slate-400">
            <span className={cn('rounded-full px-3 py-1', step === 0 && 'bg-sky-500/20 text-sky-300')}>
              1. Basics
            </span>
            <span className="h-px flex-1 bg-slate-700" />
            <span className={cn('rounded-full px-3 py-1', step === 1 && 'bg-sky-500/20 text-sky-300', step > 1 && 'text-sky-300')}>
              2. Endpoint
            </span>
            <span className="h-px flex-1 bg-slate-700" />
            <span className={cn('rounded-full px-3 py-1', step === 2 && 'bg-sky-500/20 text-sky-300')}>
              3. Success
            </span>
          </div>

          {error && (
            <div className="rounded-2xl border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">
              {error}
            </div>
          )}

          {renderStepContent()}
        </div>

        <DialogFooter className="mt-6">
          {step === 2 ? (
            <Button
              className="rounded-full bg-sky-500 px-5 py-2 text-sm font-semibold text-white hover:bg-sky-400"
              onClick={() => setOpen(false)}
            >
              Close
            </Button>
          ) : (
            <div className="flex w-full items-center justify-between gap-3">
              <Button
                variant="ghost"
                className="flex items-center gap-2 rounded-full px-4 py-2 text-sm text-slate-300 hover:text-white"
                onClick={handlePrevious}
                disabled={step === 0 || isSubmitting}
              >
                <ArrowLeft className="h-4 w-4" />
                Back
              </Button>
              {step === 1 ? (
                <Button
                  className="flex items-center gap-2 rounded-full bg-emerald-500 px-5 py-2 text-sm font-semibold text-white hover:bg-emerald-400 disabled:opacity-60"
                  onClick={handleSubmit}
                  disabled={isSubmitting || !canProceedStep1}
                >
                  {isSubmitting ? (
                    <>
                      <Spinner size={16} />
                      Publishing…
                    </>
                  ) : (
                    <>
                      Publish Agent
                      <Sparkles className="h-4 w-4" />
                    </>
                  )}
                </Button>
              ) : (
                <Button
                  className="flex items-center gap-2 rounded-full bg-sky-500 px-5 py-2 text-sm font-semibold text-white hover:bg-sky-400 disabled:opacity-60"
                  onClick={handleNext}
                  disabled={!canProceedStep0}
                >
                  Continue
                  <ArrowRight className="h-4 w-4" />
                </Button>
              )}
            </div>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
