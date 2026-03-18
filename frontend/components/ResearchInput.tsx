'use client'

import { useState } from 'react'
import { Send, ArrowRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useTaskStore } from '@/store/taskStore'
import type { TaskStatus } from '@/store/taskStore'
import type {
  CreateResearchRunRequest,
  ResearchMode,
  DepthMode,
  ResearchRunRiskLevel,
  ResearchRunQuorumPolicy,
} from '@/lib/api'

interface ResearchInputProps {
  onSubmitStandard: (description: string, budget: number) => void
  isStandardProcessing: boolean
  standardStatus: TaskStatus
  onSubmitDeep: (request: CreateResearchRunRequest) => Promise<void>
  isDeepSubmitting: boolean
  deepError?: string | null
}

export function ResearchInput({
  onSubmitStandard,
  isStandardProcessing,
  standardStatus,
  onSubmitDeep,
  isDeepSubmitting,
  deepError,
}: ResearchInputProps) {
  const { setDescription: setTaskDescription } = useTaskStore()

  const [mode, setMode] = useState<'standard' | 'deep'>('standard')
  const [description, setDescription] = useState('')
  const [budget, setBudget] = useState('100')

  // Deep Research advanced options
  const [verificationMode, setVerificationMode] = useState('standard')
  const [researchMode, setResearchMode] = useState<ResearchMode>('auto')
  const [depthMode, setDepthMode] = useState<DepthMode>('standard')
  const [strictMode, setStrictMode] = useState(false)
  const [riskLevel, setRiskLevel] = useState<ResearchRunRiskLevel>('medium')
  const [quorumPolicy, setQuorumPolicy] = useState<ResearchRunQuorumPolicy>('single_verifier')
  const [maxNodeAttempts, setMaxNodeAttempts] = useState('')
  const [validationError, setValidationError] = useState<string | null>(null)

  const standardIsLocked = !['IDLE', 'FAILED', 'CANCELLED'].includes(standardStatus)
  const isDisabled =
    mode === 'standard' ? standardIsLocked || isStandardProcessing : isDeepSubmitting

  const handleSubmit = async () => {
    setValidationError(null)

    if (!description.trim()) {
      setValidationError('Please describe your research question.')
      return
    }

    const parsedBudget = parseFloat(budget)
    if (isNaN(parsedBudget) || parsedBudget <= 0) {
      setValidationError('Please enter a valid budget amount.')
      return
    }

    setTaskDescription(description)

    if (mode === 'standard') {
      onSubmitStandard(description.trim(), parsedBudget)
    } else {
      const trimmedAttempts = maxNodeAttempts.trim()
      const parsedAttempts = trimmedAttempts ? parseInt(trimmedAttempts, 10) : undefined
      if (
        trimmedAttempts &&
        (!Number.isInteger(parsedAttempts) || parsedAttempts! < 1 || parsedAttempts! > 5)
      ) {
        setValidationError('Max node attempts must be a whole number between 1 and 5.')
        return
      }
      await onSubmitDeep({
        description: description.trim(),
        budget_limit: parsedBudget,
        verification_mode: verificationMode,
        research_mode: researchMode,
        depth_mode: depthMode,
        strict_mode: strictMode,
        risk_level: riskLevel,
        quorum_policy: strictMode ? quorumPolicy : undefined,
        max_node_attempts: parsedAttempts,
      })
    }
  }

  return (
    <Card className="overflow-hidden rounded-[28px] border-0 shadow-none">
      <CardHeader className="space-y-4 border-b border-slate-100 pb-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-2">
            <span className="inline-flex w-fit items-center rounded-full border border-sky-100 bg-sky-50 px-3 py-1 text-xs font-semibold uppercase tracking-[0.35em] text-sky-700">
              Research query
            </span>
            <CardTitle className="text-2xl text-slate-950">Start new research</CardTitle>
            <CardDescription className="text-sm leading-relaxed text-slate-500">
              {mode === 'standard'
                ? 'ProvidAI will draft a research plan and match you with specialist agents.'
                : 'Freshness-aware run with evidence gathering, critique, and revision rounds.'}
            </CardDescription>
          </div>

          {/* Mode toggle pill */}
          <div className="flex shrink-0 overflow-hidden rounded-full border border-slate-200 bg-slate-50 p-0.5 text-sm">
            <button
              type="button"
              onClick={() => setMode('standard')}
              className={
                mode === 'standard'
                  ? 'rounded-full bg-sky-500 px-4 py-1.5 font-semibold text-white transition'
                  : 'rounded-full px-4 py-1.5 text-slate-500 transition hover:text-slate-700'
              }
            >
              Standard
            </button>
            <button
              type="button"
              onClick={() => setMode('deep')}
              className={
                mode === 'deep'
                  ? 'rounded-full bg-sky-500 px-4 py-1.5 font-semibold text-white transition'
                  : 'rounded-full px-4 py-1.5 text-slate-500 transition hover:text-slate-700'
              }
            >
              Deep Research
            </button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-6 pt-6">
        {/* Shared: description */}
        <div className="space-y-2">
          <label htmlFor="research-description" className="text-sm font-medium text-slate-700">
            Research brief
          </label>
          <Textarea
            id="research-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={mode === 'deep' ? 6 : 7}
            placeholder={
              mode === 'standard'
                ? 'Example: Analyze cryptocurrency market trends across DeFi protocols and identify the top three growth catalysts for Q2 2025.'
                : 'Example: Review literature on autonomous agent payments in DeSci, identify verification patterns, and summarize the strongest implementation tradeoffs.'
            }
            className="min-h-[140px] rounded-2xl border-slate-200 px-4 py-3 text-slate-700 shadow-inner focus:border-sky-400 focus:ring-sky-300/40"
            disabled={isDisabled}
          />
        </div>

        {/* Shared: budget */}
        <div className="space-y-2">
          <label htmlFor="research-budget" className="text-sm font-medium text-slate-700">
            Budget limit (USD)
          </label>
          <Input
            id="research-budget"
            type="number"
            value={budget}
            onChange={(e) => setBudget(e.target.value)}
            min="0.01"
            step="0.01"
            className="max-w-[200px] rounded-2xl border-slate-200 px-4 py-3 text-slate-700 shadow-inner focus:border-sky-400 focus:ring-sky-300/40"
            disabled={isDisabled}
          />
        </div>

        {/* Deep Research advanced options */}
        {mode === 'deep' && (
          <div className="space-y-4 border-t border-slate-100 pt-4">
            <p className="text-xs font-semibold uppercase tracking-[0.35em] text-slate-400">
              Advanced options
            </p>

            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <div className="space-y-2">
                <label htmlFor="verification-mode" className="text-sm font-medium text-slate-700">
                  Verification
                </label>
                <select
                  id="verification-mode"
                  value={verificationMode}
                  onChange={(e) => setVerificationMode(e.target.value)}
                  className="flex h-10 w-full rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm text-slate-700 shadow-inner outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-300/40"
                  disabled={isDisabled}
                >
                  <option value="standard">Standard</option>
                  <option value="enhanced">Enhanced</option>
                </select>
              </div>

              <div className="space-y-2">
                <label htmlFor="research-mode" className="text-sm font-medium text-slate-700">
                  Research mode
                </label>
                <select
                  id="research-mode"
                  value={researchMode}
                  onChange={(e) => setResearchMode(e.target.value as ResearchMode)}
                  className="flex h-10 w-full rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm text-slate-700 shadow-inner outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-300/40"
                  disabled={isDisabled}
                >
                  <option value="auto">Auto-detect</option>
                  <option value="literature">Literature</option>
                  <option value="live_analysis">Live analysis</option>
                  <option value="hybrid">Hybrid</option>
                </select>
              </div>

              <div className="space-y-2">
                <label htmlFor="depth-mode" className="text-sm font-medium text-slate-700">
                  Depth
                </label>
                <select
                  id="depth-mode"
                  value={depthMode}
                  onChange={(e) => setDepthMode(e.target.value as DepthMode)}
                  className="flex h-10 w-full rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm text-slate-700 shadow-inner outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-300/40"
                  disabled={isDisabled}
                >
                  <option value="standard">Standard</option>
                  <option value="deep">Deep</option>
                </select>
              </div>

              <div className="space-y-2">
                <label htmlFor="strict-mode" className="text-sm font-medium text-slate-700">
                  Strict review
                </label>
                <select
                  id="strict-mode"
                  value={strictMode ? 'strict' : 'standard'}
                  onChange={(e) => setStrictMode(e.target.value === 'strict')}
                  className="flex h-10 w-full rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm text-slate-700 shadow-inner outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-300/40"
                  disabled={isDisabled}
                >
                  <option value="standard">Standard</option>
                  <option value="strict">Strict</option>
                </select>
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              <div className="space-y-2">
                <label htmlFor="risk-level" className="text-sm font-medium text-slate-700">
                  Risk level
                </label>
                <select
                  id="risk-level"
                  value={riskLevel}
                  onChange={(e) => setRiskLevel(e.target.value as ResearchRunRiskLevel)}
                  className="flex h-10 w-full rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm text-slate-700 shadow-inner outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-300/40"
                  disabled={isDisabled}
                >
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                </select>
              </div>

              <div className="space-y-2">
                <label htmlFor="quorum-policy" className="text-sm font-medium text-slate-700">
                  Quorum policy
                </label>
                <select
                  id="quorum-policy"
                  value={quorumPolicy}
                  onChange={(e) => setQuorumPolicy(e.target.value as ResearchRunQuorumPolicy)}
                  className="flex h-10 w-full rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm text-slate-700 shadow-inner outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-300/40 disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={isDisabled || !strictMode}
                >
                  <option value="single_verifier">Single verifier</option>
                  <option value="two_of_three">Two of three</option>
                  <option value="three_of_five">Three of five</option>
                  <option value="unanimous">Unanimous</option>
                </select>
              </div>

              <div className="space-y-2">
                <label htmlFor="max-attempts" className="text-sm font-medium text-slate-700">
                  Max node attempts
                </label>
                <Input
                  id="max-attempts"
                  type="number"
                  value={maxNodeAttempts}
                  onChange={(e) => setMaxNodeAttempts(e.target.value)}
                  min="1"
                  max="5"
                  step="1"
                  placeholder={strictMode ? '2' : '1'}
                  className="rounded-2xl border-slate-200 px-4 py-3 text-slate-700 shadow-inner focus:border-sky-400 focus:ring-sky-300/40"
                  disabled={isDisabled}
                />
              </div>
            </div>
          </div>
        )}

        {/* Error display */}
        {(validationError || (mode === 'deep' && deepError)) && (
          <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {validationError || deepError}
          </div>
        )}

        {/* Footer */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4">
          <p className="max-w-sm text-xs text-slate-400">
            {mode === 'standard'
              ? 'ProvidAI will match you with specialist agents and escrow payment on Hedera until results are verified.'
              : 'Synaptica will classify the query, start the run immediately, and stream node-level progress below.'}
          </p>
          <Button
            type="button"
            onClick={handleSubmit}
            disabled={isDisabled}
            className="rounded-full bg-gradient-to-r from-sky-500 via-cyan-500 to-teal-500 px-6 py-5 text-sm font-semibold text-white shadow-lg shadow-sky-500/25 hover:opacity-95 disabled:opacity-50"
          >
            {mode === 'standard' ? (
              <>
                {isStandardProcessing ? 'Running…' : 'Start research'}
                <Send className="ml-2 h-4 w-4" />
              </>
            ) : (
              <>
                {isDeepSubmitting ? 'Launching…' : 'Launch research run'}
                <ArrowRight className="ml-2 h-4 w-4" />
              </>
            )}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
