'use client'

import { useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { Sidebar } from '@/components/Sidebar'
import { TaskForm } from '@/components/TaskForm'
import { TaskStatusCard } from '@/components/TaskStatusCard'
import { PaymentModal } from '@/components/PaymentModal'
import { TaskResults } from '@/components/TaskResults'
import { Transactions } from '@/components/Transactions'
import { Marketplace } from '@/components/Marketplace'
import { DataVault } from '@/components/DataVault'
import { useTaskStore } from '@/store/taskStore'
import { useCreditsStore } from '@/store/creditsStore'
import type { TaskStatus } from '@/store/taskStore'
import { createTask } from '@/lib/api'
import { Button } from '@/components/ui/button'

const statusMessages: Record<TaskStatus, string> = {
  IDLE: 'Ready for your research query',
  PLANNING: 'Analyzing research requirements',
  APPROVING_PLAN: 'Research plan ready for review',
  NEGOTIATING: 'Matching with specialist agent',
  PAYING: 'Processing microtransaction on Hedera',
  EXECUTING: 'Research agent collecting & analyzing data',
  VERIFYING: 'Independent verification in progress',
  COMPLETE: 'Research complete & verified',
  FAILED: 'Action required - research interrupted',
  CANCELLED: 'Research cancelled by user',
}

export default function Home() {
  const {
    status,
    taskId,
    description,
    setStatus,
    setTaskId,
    setSelectedAgent,
    setPaymentDetails,
    addExecutionLog,
    setProgressLogs,
    setVerificationPending,
    setVerificationData,
    setResult,
    setError,
    reset,
  } = useTaskStore()

  const { deductCredits, fetchCredits } = useCreditsStore()

  const [isProcessing, setIsProcessing] = useState(false)
  const [activeTab, setActiveTab] = useState('console')

  // On mount: fetch credits; handle ?payment=success redirect
  useEffect(() => {
    fetchCredits()
    const params = new URLSearchParams(window.location.search)
    if (params.get('payment') === 'success') {
      fetchCredits()
      // Clean URL
      window.history.replaceState({}, '', '/')
    }
  }, [fetchCredits])

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

      // Deduct 1 credit per research iteration
      deductCredits(1)

      addExecutionLog({
        timestamp: new Date().toLocaleTimeString(),
        message: `Task submitted with budget: $${budget}. Starting analysis...`,
        source: 'orchestrator',
      })

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

  const pollTaskUpdates = async (taskId: string) => {
    const maxAttempts = 60
    let attempts = 0

    const poll = async () => {
      const currentStatus = useTaskStore.getState().status
      if (currentStatus === 'CANCELLED') return

      if (attempts >= maxAttempts) {
        setError('Task timeout - please check backend logs')
        setStatus('FAILED')
        return
      }

      try {
        const { getTask } = await import('@/lib/api')
        const task = await getTask(taskId)

        if (task.progress && Array.isArray(task.progress)) {
          setProgressLogs(task.progress)
        }

        if (task.verification_pending && task.verification_data) {
          setVerificationPending(true)
          setVerificationData(task.verification_data)
          setStatus('VERIFYING')
          attempts++
          setTimeout(poll, 5000)
          return
        } else {
          setVerificationPending(false)
          setVerificationData(null)
        }

        const lastProgress = task.progress?.[task.progress.length - 1]
        if (lastProgress) {
          if (lastProgress.step === 'initialization' || lastProgress.step === 'orchestrator_analysis') {
            setStatus('PLANNING')
          } else if (lastProgress.step === 'planning') {
            setStatus('APPROVING_PLAN')
          } else if (lastProgress.step === 'negotiator') {
            setStatus('NEGOTIATING')
          } else if (lastProgress.step === 'payment') {
            setStatus('PAYING')
          } else if (lastProgress.step === 'executor') {
            setStatus('EXECUTING')
          } else if (lastProgress.step.startsWith('verification_')) {
            setStatus('VERIFYING')
          }
        }

        if (task.status === 'completed') {
          setStatus('COMPLETE')
          setResult({ success: true, data: task.result })
          return
        } else if (task.status === 'failed') {
          setStatus('FAILED')
          setResult({ success: false, error: task.error || 'Task execution failed' })
          return
        } else if (task.status === 'CANCELLED') {
          setStatus('CANCELLED')
          setResult({ success: false, error: 'Task cancelled by user' })
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

  const handleApprovePlan = async () => {
    if (!taskId) return

    try {
      setStatus('NEGOTIATING')
      addExecutionLog({
        timestamp: new Date().toLocaleTimeString(),
        message: 'Finding suitable agent...',
        source: 'negotiator',
      })

      setTimeout(() => {
        const mockAgent = {
          agentId: 'databot_v3',
          name: 'DataBot_v3',
          description: 'AI agent specialized in data analysis',
          reputation: 4.8,
          price: 4.5,
          currency: 'USDC',
          capabilities: ['Python data analysis', 'CSV ingestion', 'Statistical analysis'],
        }

        setSelectedAgent(mockAgent)
        setPaymentDetails({
          paymentId: `payment_${Date.now()}`,
          amount: 4.5,
          currency: 'USDC',
          fromAccount: 'user_wallet',
          toAccount: mockAgent.agentId,
          agentName: mockAgent.name,
          description: `Task execution payment for ${mockAgent.name}`,
        })

        addExecutionLog({
          timestamp: new Date().toLocaleTimeString(),
          message: `Agent found: ${mockAgent.name} (${mockAgent.reputation} stars) for $${mockAgent.price}`,
          source: 'negotiator',
        })
      }, 2000)
    } catch (error: any) {
      setError(error.message || 'Failed to approve plan')
      setStatus('FAILED')
    }
  }

  const statusIndicatorClass =
    status === 'FAILED'
      ? 'bg-red-400'
      : status === 'CANCELLED'
        ? 'bg-orange-400'
        : status === 'COMPLETE'
          ? 'bg-emerald-400'
          : 'bg-sky-400 animate-pulse'

  return (
    <div className="flex h-screen overflow-hidden bg-slate-950 text-slate-100">
      <Sidebar activeTab={activeTab} onTabChange={setActiveTab} />

      <main className="flex-1 ml-[255px] overflow-y-auto">
        <div className="max-w-4xl mx-auto px-6 py-8">
          {activeTab === 'console' && (
            <div className="relative">
              <div className="absolute inset-0 rounded-[28px] bg-gradient-to-br from-sky-500/15 via-transparent to-purple-600/20 blur-2xl pointer-events-none" />
              <div className="relative overflow-hidden rounded-[28px] border border-white/20 bg-slate-900/75 p-6 shadow-[0_45px_90px_-50px_rgba(56,189,248,0.9)] backdrop-blur-xl">
                <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
                  <span className="text-xs uppercase tracking-[0.4em] text-slate-400">Live research status</span>
                  <span className="flex items-center gap-2 text-sm text-slate-300">
                    <span className={`inline-flex h-2.5 w-2.5 rounded-full ${statusIndicatorClass}`} />
                    {statusMessages[status]}
                  </span>
                </div>

                <div className="space-y-6">
                  <div className="rounded-2xl border border-white/15 bg-white/95 p-1 text-slate-900 shadow-[0_30px_80px_-45px_rgba(59,130,246,0.7)]">
                    {(status === 'IDLE' || status === 'FAILED' || status === 'CANCELLED') ? (
                      <TaskForm onSubmit={handleStartTask} />
                    ) : (
                      <TaskStatusCard />
                    )}
                  </div>

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

                  {description && (
                    <div className="rounded-2xl border border-white/15 bg-white/5 p-5 text-slate-200">
                      <div className="text-xs uppercase tracking-[0.3em] text-slate-400">Research query</div>
                      <p className="mt-2 text-sm leading-relaxed text-slate-100">{description}</p>
                    </div>
                  )}
                </div>

                <PaymentModal />
              </div>
            </div>
          )}

          {activeTab === 'transactions' && <Transactions />}
          {activeTab === 'marketplace' && <Marketplace />}
          {activeTab === 'data-vault' && <DataVault />}
        </div>
      </main>
    </div>
  )
}
