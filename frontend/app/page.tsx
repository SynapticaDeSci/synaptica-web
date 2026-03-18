'use client'

import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { HederaInfo } from '@/components/HederaInfo'
import { Sidebar } from '@/components/Sidebar'
import { ResearchInput } from '@/components/ResearchInput'
import { TaskStatusCard } from '@/components/TaskStatusCard'
import { TaskResults } from '@/components/TaskResults'
import { Transactions } from '@/components/Transactions'
import { Marketplace } from '@/components/Marketplace'
import { DataVault } from '@/components/DataVault'
import { ResearchRunDetailView } from '@/components/research-runs/ResearchRunDetailView'
import { useTaskStore } from '@/store/taskStore'
import type { TaskStatus } from '@/store/taskStore'
import type { LucideIcon } from 'lucide-react'
import { Sparkles, ShieldCheck, Coins, ArrowRight, Cpu, Layers } from 'lucide-react'
import { createTask, createResearchRun } from '@/lib/api'
import { Button } from '@/components/ui/button'

const statusMessages: Record<TaskStatus, string> = {
  IDLE: 'Ready for your research query',
  PLANNING: 'Analyzing research requirements',
  NEGOTIATING: 'Matching with specialist agent',
  EXECUTING: 'Research agent collecting & analyzing data',
  VERIFYING: 'Independent verification in progress',
  COMPLETE: 'Research complete & verified',
  FAILED: 'Action required - research interrupted',
  CANCELLED: 'Research cancelled by user',
}

const heroStats = [
  { value: '4.8 / 5', label: 'Average research quality rating' },
  { value: '120+', label: 'Specialized research agents' },
  { value: '~6 min', label: 'Average time to verified insights' },
]

const featureHighlights: Array<{ title: string; description: string; icon: LucideIcon }> = [
  {
    title: 'Specialized research agents',
    description: 'Access expert agents for data collection, statistical analysis, market research, and domain-specific insights.',
    icon: Cpu,
  },
  {
    title: 'Pay-per-research microtransactions',
    description: 'ERC-8004 reputation and escrowed micropayments on Hedera ensure quality research at fair, transparent prices.',
    icon: Coins,
  },
  {
    title: 'Verified insights',
    description: 'Independent verification agents validate data sources, methodology, and conclusions before you pay.',
    icon: ShieldCheck,
  },
]

const flowSteps: Array<{ badge: string; title: string; description: string; icon: LucideIcon }> = [
  {
    badge: 'STEP 01',
    title: 'Submit your research question',
    description:
      'Describe what data or insights you need. Our orchestrator breaks it into specialized research subtasks.',
    icon: Sparkles,
  },
  {
    badge: 'STEP 02',
    title: 'Review research plan',
    description:
      'Approve the methodology, data sources, and estimated microtransaction cost before any payment is made.',
    icon: Layers,
  },
  {
    badge: 'STEP 03',
    title: 'Agent matches & micropayment',
    description:
      'We match your query to the best specialist agent by expertise and reputation, then escrow payment on Hedera.',
    icon: Coins,
  },
  {
    badge: 'STEP 04',
    title: 'Receive verified research',
    description:
      'Specialist agents collect and analyze data in real-time. Independent verifiers validate findings before payment release.',
    icon: ShieldCheck,
  },
]

export default function Home() {
  const {
    status,
    description,
    setStatus,
    setTaskId,
    addExecutionLog,
    setProgressLogs,
    setVerificationPending,
    setVerificationData,
    setResult,
    setError,
    reset,
  } = useTaskStore()

  const [isProcessing, setIsProcessing] = useState(false)
  const [activeTab, setActiveTab] = useState('research')
  const [activeResearchRunId, setActiveResearchRunId] = useState<string | null>(null)

  const createResearchRunMutation = useMutation({
    mutationFn: createResearchRun,
    onSuccess: (researchRun) => {
      reset()
      setActiveResearchRunId(researchRun.id)
    },
  })

  const handleScrollToConsole = () => {
    const consoleSection = document.getElementById('task-console')
    if (consoleSection) {
      consoleSection.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }

  // Handle task submission
  const handleStartTask = async (taskDescription: string, budget: number = 100) => {
    if (!taskDescription.trim()) {
      alert('Please enter a task description')
      return
    }

    try {
      setIsProcessing(true)
      setStatus('PLANNING')
      setError(null)
      setResult(null)
      setActiveResearchRunId(null)

      addExecutionLog({
        timestamp: new Date().toLocaleTimeString(),
        message: `Task submitted with budget: $${budget}. Starting analysis...`,
        source: 'orchestrator',
      })

      // Create task via BFF
      const response = await createTask({
        description: taskDescription,
        budget_limit: budget,
        min_reputation_score: 0.7,
        verification_mode: 'standard',
      })

      if (response.error) {
        throw new Error(response.error)
      }

      setTaskId(response.task_id)
      addExecutionLog({
        timestamp: new Date().toLocaleTimeString(),
        message: `Task created: ${response.task_id}. Orchestrator running in background...`,
        source: 'orchestrator',
      })

      // Start polling for progress updates
      await pollTaskUpdates(response.task_id)
    } catch (error: any) {
      console.error('Error creating task:', error)
      setError(error.message || 'Failed to create task')
      setStatus('FAILED')
      addExecutionLog({
        timestamp: new Date().toLocaleTimeString(),
        message: `Error: ${error.message}`,
        source: 'orchestrator',
      })
    } finally {
      setIsProcessing(false)
    }
  }

  // Poll for task updates
  const pollTaskUpdates = async (taskId: string) => {
    const maxAttempts = 60 // 5 minutes with 5s intervals
    let attempts = 0

    const poll = async () => {
      // Check if task was already cancelled in the store - if so, stop polling
      const currentStatus = useTaskStore.getState().status
      if (currentStatus === 'CANCELLED') {
        console.log('[pollTaskUpdates] Task already cancelled in store, stopping poll')
        return
      }

      if (attempts >= maxAttempts) {
        setError('Task timeout - please check backend logs')
        setStatus('FAILED')
        return
      }

      try {
        // Import getTask from api.ts instead of using pollTaskStatus
        const { getTask } = await import('@/lib/api')
        const task = await getTask(taskId)

        console.log('[pollTaskUpdates] Received task update:', {
          taskId: task.task_id,
          status: task.status,
          progressCount: task.progress?.length || 0,
          currentStep: task.current_step,
        })

        // Update progress logs from API
        if (task.progress && Array.isArray(task.progress)) {
          console.log('[pollTaskUpdates] Setting progress logs:', task.progress.length, 'items')
          setProgressLogs(task.progress)
        }

        // Check for verification pending
        if (task.verification_pending && task.verification_data) {
          console.log('[pollTaskUpdates] Verification pending, showing modal')
          setVerificationPending(true)
          setVerificationData(task.verification_data)
          setStatus('VERIFYING')
          // Continue polling to wait for human decision
          attempts++
          setTimeout(poll, 5000)
          return
        } else {
          setVerificationPending(false)
          setVerificationData(null)
        }

        // Determine status from progress logs
        const lastProgress = task.progress?.[task.progress.length - 1]
        if (lastProgress) {
          console.log('[pollTaskUpdates] Last progress step:', lastProgress.step, lastProgress.status)
          // Map backend progress to frontend status
          if (lastProgress.step === 'initialization' || lastProgress.step === 'orchestrator_analysis') {
            setStatus('PLANNING')
          } else if (lastProgress.step === 'planning') {
            setStatus('PLANNING')
          } else if (lastProgress.step === 'negotiator' || lastProgress.step.startsWith('negotiator_')) {
            setStatus('NEGOTIATING')
          } else if (lastProgress.step === 'executor' || lastProgress.step.startsWith('executor_')) {
            setStatus('EXECUTING')
          } else if (
            lastProgress.step === 'verifier' ||
            lastProgress.step.startsWith('verification_')
          ) {
            setStatus('VERIFYING')
          }
        }

        if (task.status === 'completed') {
          setStatus('COMPLETE')
          setResult({
            success: true,
            data: task.result,
          })
          return
        } else if (task.status === 'failed') {
          setStatus('FAILED')
          setResult({
            success: false,
            error: task.error || 'Task execution failed',
          })
          return
        } else if (task.status === 'CANCELLED') {
          // Task was cancelled - stop polling immediately
          console.log('[pollTaskUpdates] Task cancelled, stopping poll')
          setStatus('CANCELLED')
          setResult({
            success: false,
            error: 'Task cancelled by user',
          })
          return
        }

        attempts++
        setTimeout(poll, 5000)
      } catch (error: any) {
        console.error('Error polling task:', error)
        attempts++
        if (attempts < maxAttempts) {
          setTimeout(poll, 5000)
        } else {
          setError('Failed to get task status')
          setStatus('FAILED')
        }
      }
    }

    poll()
  }

  const statusIndicatorClass =
    status === 'FAILED'
      ? 'bg-red-400'
      : status === 'CANCELLED'
        ? 'bg-orange-400'
        : status === 'COMPLETE'
          ? 'bg-emerald-400'
          : 'bg-sky-400 animate-pulse'

  const researchContent = (
    <>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <span className="text-xs uppercase tracking-[0.4em] text-slate-400">Live research status</span>
        <span className="flex items-center gap-2 text-sm text-slate-300">
          <span className={`inline-flex h-2.5 w-2.5 rounded-full ${statusIndicatorClass}`} />
          {statusMessages[status]}
        </span>
      </div>

      <div className="space-y-6">
        <div className="rounded-2xl border border-white/15 bg-white/95 p-1 text-slate-900 shadow-[0_30px_80px_-45px_rgba(59,130,246,0.7)]">
          <ResearchInput
            onSubmitStandard={handleStartTask}
            isStandardProcessing={isProcessing}
            standardStatus={status}
            onSubmitDeep={async (request) => {
              await createResearchRunMutation.mutateAsync(request)
            }}
            isDeepSubmitting={createResearchRunMutation.isPending}
            deepError={createResearchRunMutation.error instanceof Error ? createResearchRunMutation.error.message : null}
          />
        </div>

        {!['IDLE', 'FAILED', 'CANCELLED', 'COMPLETE'].includes(status) && (
          <div className="rounded-2xl border border-white/15 bg-white/95 p-1 text-slate-900 shadow-[0_30px_80px_-45px_rgba(59,130,246,0.7)]">
            <TaskStatusCard />
          </div>
        )}

        {(status === 'COMPLETE' || status === 'FAILED' || status === 'CANCELLED') && (
          <div className="space-y-4">
            <div className="rounded-2xl border border-white/15 bg-white/95 p-1 text-slate-900 shadow-[0_30px_80px_-45px_rgba(59,130,246,0.7)]">
              <TaskResults />
            </div>
            <Button
              onClick={reset}
              variant="outline"
              className="w-full border-slate-200 bg-white/10 text-white transition hover:bg-white/20"
            >
              Start new research
            </Button>
          </div>
        )}

        {activeResearchRunId && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-xs uppercase tracking-[0.4em] text-slate-400">Research run active</span>
              <Button
                variant="outline"
                className="border-white/15 bg-white/5 text-white hover:bg-white/10 hover:text-white"
                onClick={() => setActiveResearchRunId(null)}
              >
                New research run
              </Button>
            </div>
            <ResearchRunDetailView researchRunId={activeResearchRunId} />
          </div>
        )}

        {description && (
          <div className="rounded-2xl border border-white/15 bg-white/5 p-5 text-slate-200">
            <div className="text-xs uppercase tracking-[0.3em] text-slate-400">Research query</div>
            <p className="mt-2 text-sm leading-relaxed text-slate-100">{description}</p>
          </div>
        )}
      </div>
    </>
  )

  return (
    <div className="flex h-screen overflow-hidden bg-slate-950 text-slate-100">
      <Sidebar
        activeTab={activeTab}
        onTabChange={setActiveTab}
        onNewResearch={() => {
          reset()
          setActiveResearchRunId(null)
          setActiveTab('research')
        }}
      />

      <main className="flex flex-1 flex-col overflow-y-auto">
        <div className="mx-auto w-full max-w-5xl px-6 py-8">
          <div className="relative">
            <div className="absolute inset-0 rounded-[28px] bg-gradient-to-br from-sky-500/15 via-transparent to-purple-600/20 blur-2xl" />
            <div className="relative overflow-hidden rounded-[28px] border border-white/20 bg-slate-900/75 p-6 shadow-[0_45px_90px_-50px_rgba(56,189,248,0.9)] backdrop-blur-xl">
              {activeTab === 'research'     && researchContent}
              {activeTab === 'transactions' && <Transactions />}
              {activeTab === 'marketplace'  && <Marketplace />}
              {activeTab === 'data-vault'   && <DataVault />}
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
