'use client'

import React, { useMemo, useRef, useEffect } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useTaskStore, TaskStatus } from '@/store/taskStore'
import { CheckCircle2, Circle, XCircle, Loader2, Pause } from 'lucide-react'
import { cn } from '@/lib/utils'
import { VerificationCard } from '@/components/VerificationCard'
import { HolAgentsPanel } from '@/components/HolAgentsPanel'

const statusConfig: Record<TaskStatus, { label: string; progress: number; icon: React.ReactNode }> = {
  IDLE: { label: 'Ready', progress: 0, icon: <Circle className="h-4 w-4" /> },
  PLANNING: { label: 'Planning...', progress: 10, icon: <Loader2 className="h-4 w-4 animate-spin" /> },
  NEGOTIATING: { label: 'Negotiating...', progress: 40, icon: <Loader2 className="h-4 w-4 animate-spin" /> },
  EXECUTING: { label: 'Executing...', progress: 70, icon: <Loader2 className="h-4 w-4 animate-spin" /> },
  VERIFYING: { label: 'Verifying...', progress: 90, icon: <Loader2 className="h-4 w-4 animate-spin" /> },
  COMPLETE: { label: 'Complete', progress: 100, icon: <CheckCircle2 className="h-4 w-4 text-green-500" /> },
  FAILED: { label: 'Failed', progress: 0, icon: <XCircle className="h-4 w-4 text-red-500" /> },
  CANCELLED: { label: 'Cancelled', progress: 0, icon: <XCircle className="h-4 w-4 text-orange-500" /> },
}

export function TaskStatusCard() {
  const { status, plan, selectedAgent, executionLogs, result, error, progressLogs, verificationPending, verificationData } = useTaskStore()
  const progressLogsEndRef = useRef<HTMLDivElement>(null)

  const config = statusConfig[status]

  console.log('[TaskStatusCard] Render:', {
    status,
    progressLogsCount: progressLogs?.length || 0,
    progressLogs: progressLogs,
  })

  // Auto-scroll to bottom when new progress logs are added
  useEffect(() => {
    if (progressLogsEndRef.current) {
      progressLogsEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [progressLogs])

  // Group progress logs by step and keep only the latest status for each step
  // Merge data from multiple updates for the same step
  const latestProgressByStep = useMemo(() => {
    if (!progressLogs || progressLogs.length === 0) return []

    const stepMap = new Map()
    progressLogs.forEach(log => {
      const existing = stepMap.get(log.step)
      if (existing) {
        // Merge data, keeping all fields from both updates
        stepMap.set(log.step, {
          ...existing,
          ...log,
          data: {
            ...existing.data,
            ...log.data
          }
        })
      } else {
        stepMap.set(log.step, log)
      }
    })

    return Array.from(stepMap.values())
  }, [progressLogs])

  // Extract TODO list and track completion status
  const { todoList, todoCompletionStatus } = useMemo(() => {
    if (!progressLogs || progressLogs.length === 0) return { todoList: null, todoCompletionStatus: {} }

    // Find the planning step that contains the TODO list
    const planningLog = progressLogs.find(log => log.step === 'planning' && log.data?.todo_list)

    if (!planningLog?.data?.todo_list) return { todoList: null, todoCompletionStatus: {} }

    // Track which TODOs are completed based on microtask completion logs
    const completionStatus: Record<string, boolean> = {}
    progressLogs.forEach(log => {
      // Check for microtask completion (e.g., "microtask_todo_0" with status "completed")
      if (log.step.startsWith('microtask_todo_') && log.status === 'completed') {
        const todoId = log.step.replace('microtask_', '') // Extract "todo_0", "todo_1", etc.
        completionStatus[todoId] = true
      }
    })

    return {
      todoList: planningLog.data.todo_list,
      todoCompletionStatus: completionStatus
    }
  }, [progressLogs])

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {config.icon}
          Status: {config.label}
        </CardTitle>
        <CardDescription>Real-time execution logs and progress</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">

        {/* Task Plan, HOL Agents, and Progress Logs */}
        {latestProgressByStep && latestProgressByStep.length > 0 && (
          <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">

            {/* Task Plan Column (1/3 width on large screens) */}
            {todoList && (
              <div className="lg:col-span-1">
                <div className="sticky top-0">
                  <h4 className="text-sm font-semibold text-slate-700 mb-3">Task Plan:</h4>
                  <div className="space-y-2">
                    {todoList.map((todo: any, index: number) => {
                      const isCompleted = todoCompletionStatus[todo.id] || false
                      return (
                        <div
                          key={index}
                          className={cn(
                            "p-3 rounded-lg border transition-all",
                            isCompleted
                              ? "bg-green-50 border-green-200"
                              : "bg-white border-slate-200"
                          )}
                        >
                          <div className="flex items-start gap-2">
                            {isCompleted ? (
                              <CheckCircle2 className="h-4 w-4 text-green-600 mt-0.5 flex-shrink-0" />
                            ) : (
                              <Circle className="h-4 w-4 text-slate-400 mt-0.5 flex-shrink-0" />
                            )}
                            <div className="flex-1 min-w-0">
                              <p className={cn(
                                "text-sm font-medium",
                                isCompleted
                                  ? "text-green-900 line-through"
                                  : "text-slate-900"
                              )}>
                                {todo.title || todo.content}
                              </p>
                              {todo.description && (
                                <p className={cn(
                                  "text-xs mt-1",
                                  isCompleted
                                    ? "text-green-700 line-through"
                                    : "text-slate-600"
                                )}>
                                  {todo.description}
                                </p>
                              )}
                            </div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              </div>
            )}

            {/* HOL Agents + Progress Logs Column (2/3 width on large screens) */}
            <div className={cn("lg:col-span-3 space-y-4", !todoList && "lg:col-span-4")}>
              <HolAgentsPanel />
              <h4 className="text-sm font-semibold text-slate-700 mb-3">Progress Logs:</h4>
              <div className="max-h-96 overflow-y-auto space-y-2 pr-2 scrollbar-thin scrollbar-thumb-slate-300 scrollbar-track-slate-100">
                {latestProgressByStep.map((log, index) => {
                const isCompleted = log.status === 'completed' || log.status === 'success';
                const isFailed = log.status === 'failed' || log.status === 'error';
                const isRunning = log.status === 'running' || log.status === 'started';

                // Special aesthetic block for web search phase
                if (log.step === 'web_search') {
                  return (
                    <div key={`web-search-${index}`} className="space-y-2">
                      <div
                        className={cn(
                          'relative overflow-hidden rounded-lg border p-4',
                          isCompleted && 'bg-gradient-to-br from-emerald-50 to-white border-emerald-200',
                          isFailed && 'bg-gradient-to-br from-red-50 to-white border-red-200',
                          isRunning && 'bg-gradient-to-br from-sky-50 to-white border-sky-200',
                          !isCompleted && !isFailed && !isRunning && 'bg-slate-50 border-slate-200'
                        )}
                      >
                        {isRunning && (
                          <div className="absolute inset-0 -translate-x-1/2 animate-[shimmer_2s_infinite] bg-[linear-gradient(110deg,rgba(255,255,255,0)_0%,rgba(255,255,255,0.7)_40%,rgba(255,255,255,0)_80%)]" />
                        )}
                        <div className="flex items-start gap-3 relative">
                          <div className={cn(
                            "flex h-8 w-8 items-center justify-center rounded-full",
                            isCompleted ? "bg-emerald-100" : isFailed ? "bg-red-100" : "bg-sky-100"
                          )}>
                            {isCompleted ? (
                              <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                            ) : isFailed ? (
                              <XCircle className="h-4 w-4 text-red-600" />
                            ) : (
                              <Loader2 className="h-4 w-4 text-sky-600 animate-spin" />
                            )}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className={cn(
                                "font-semibold text-xs",
                                isCompleted && 'text-emerald-700',
                                isFailed && 'text-red-700',
                                isRunning && 'text-sky-700'
                              )}>
                                [web_search]
                              </span>
                              <span className="text-xs text-slate-500">
                                {new Date(log.timestamp).toLocaleTimeString()}
                              </span>
                            </div>
                            <p className={cn(
                              "mt-1 text-sm",
                              isCompleted && 'text-emerald-800',
                              isFailed && 'text-red-800',
                              isRunning && 'text-sky-800',
                            )}>
                              {log.data?.message || (isRunning ? 'Searching via Tavily + academic sources...' : 'Web search results retrieved')}
                            </p>
                            {log.data?.response_preview && isCompleted && (
                              <div className="mt-2 rounded border border-slate-200 bg-white p-2">
                                <p className="text-[11px] text-slate-600 line-clamp-4">
                                  {log.data.response_preview}
                                </p>
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  )
                }

                // Special handling for verification steps
                if (log.step.startsWith('verification_')) {
                  const isWaitingForHuman = log.status === 'waiting_for_human'
                  const isHumanApproved = log.data?.human_approved
                  const isHumanRejected = log.data?.human_rejected
                  const qualityScore = log.data?.quality_score

                  return (
                    <div key={`verification-${index}`} className="space-y-2">
                      <div
                        className={cn(
                          'relative overflow-hidden rounded-lg border p-4',
                          isCompleted && 'bg-gradient-to-br from-emerald-50 to-white border-emerald-200',
                          isFailed && 'bg-gradient-to-br from-red-50 to-white border-red-200',
                          isWaitingForHuman && 'bg-gradient-to-br from-yellow-50 to-white border-yellow-300',
                          isRunning && !isWaitingForHuman && 'bg-gradient-to-br from-purple-50 to-white border-purple-200',
                        )}
                      >
                        <div className="flex items-start gap-3">
                          <div className={cn(
                            "flex h-8 w-8 items-center justify-center rounded-full",
                            isCompleted && "bg-emerald-100",
                            isFailed && "bg-red-100",
                            isWaitingForHuman && "bg-yellow-100",
                            isRunning && !isWaitingForHuman && "bg-purple-100"
                          )}>
                            {isCompleted ? (
                              <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                            ) : isFailed ? (
                              <XCircle className="h-4 w-4 text-red-600" />
                            ) : isWaitingForHuman ? (
                              <Pause className="h-4 w-4 text-yellow-600" />
                            ) : (
                              <Loader2 className="h-4 w-4 text-purple-600 animate-spin" />
                            )}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className={cn(
                                "font-semibold text-xs",
                                isCompleted && 'text-emerald-700',
                                isFailed && 'text-red-700',
                                isWaitingForHuman && 'text-yellow-700',
                                isRunning && !isWaitingForHuman && 'text-purple-700'
                              )}>
                                [verification]
                              </span>
                              <span className="text-xs text-slate-500">
                                {new Date(log.timestamp).toLocaleTimeString()}
                              </span>
                              {qualityScore !== undefined && (
                                <span className={cn(
                                  "text-xs px-2 py-0.5 rounded-full",
                                  qualityScore >= 80 ? "bg-emerald-100 text-emerald-700" :
                                  qualityScore >= 50 ? "bg-yellow-100 text-yellow-700" :
                                  "bg-red-100 text-red-700"
                                )}>
                                  Score: {qualityScore}/100
                                </span>
                              )}
                              {isHumanApproved && (
                                <span className="text-xs px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">
                                  Human Approved
                                </span>
                              )}
                              {log.data?.auto_approved && (
                                <span className="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700">
                                  Auto-Approved
                                </span>
                              )}
                            </div>
                            <p className={cn(
                              "mt-1 text-sm",
                              isCompleted && 'text-emerald-800',
                              isFailed && 'text-red-800',
                              isWaitingForHuman && 'text-yellow-800',
                              isRunning && !isWaitingForHuman && 'text-purple-800'
                            )}>
                              {log.data?.message || 'Analyzing output quality...'}
                            </p>
                            {log.data?.rejection_reason && (
                              <div className="mt-2 rounded border border-red-200 bg-red-50 p-2">
                                <p className="text-xs text-red-800">
                                  <span className="font-semibold">Rejection reason:</span> {log.data.rejection_reason}
                                </p>
                              </div>
                            )}
                          </div>
                        </div>
                      </div>

                      {/* Show VerificationCard if waiting for human */}
                      {isWaitingForHuman && verificationPending && verificationData && (
                        <VerificationCard />
                      )}
                    </div>
                  )
                }

                return (
                  <div key={index} className="space-y-2">
                    <div
                      className={cn(
                        'flex items-start gap-2 text-sm p-2 rounded border',
                        isCompleted && 'bg-green-50 border-green-200',
                        isFailed && 'bg-red-50 border-red-200',
                        isRunning && 'bg-blue-50 border-blue-200',
                        !isCompleted && !isFailed && !isRunning && 'bg-slate-100 border-slate-200'
                      )}
                    >
                      {isCompleted ? (
                        <CheckCircle2 className="h-4 w-4 text-green-600 mt-0.5 flex-shrink-0" />
                      ) : isFailed ? (
                        <XCircle className="h-4 w-4 text-red-600 mt-0.5 flex-shrink-0" />
                      ) : isRunning ? (
                        <Loader2 className="h-4 w-4 text-blue-600 mt-0.5 flex-shrink-0 animate-spin" />
                      ) : (
                        <Circle className="h-4 w-4 text-slate-400 mt-0.5 flex-shrink-0" />
                      )}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          {/* Only show step name if not a microtask or negotiator (they show task name in message) */}
                          {!log.step.startsWith('microtask_') && !log.step.startsWith('negotiator_') && (
                            <span className={cn(
                              "font-semibold text-xs",
                              isCompleted && 'text-green-700',
                              isFailed && 'text-red-700',
                              isRunning && 'text-blue-700',
                              !isCompleted && !isFailed && !isRunning && 'text-slate-700'
                            )}>
                              [{log.step}]
                            </span>
                          )}
                          <span className="text-xs text-slate-500">
                            {new Date(log.timestamp).toLocaleTimeString()}
                          </span>
                        </div>
                        {log.data?.message && (
                          <p className={cn(
                            "mt-1 text-xs font-medium",
                            isCompleted && 'text-green-700',
                            isFailed && 'text-red-700',
                            isRunning && 'text-blue-700',
                            !isCompleted && !isFailed && !isRunning && 'text-slate-600'
                          )}>
                            {log.data.message}
                          </p>
                        )}
                        {log.data?.error && (
                          <p className="text-red-600 mt-1 text-xs font-mono">
                            Error: {log.data.error}
                          </p>
                        )}
                      </div>
                    </div>

                    {/* Show discovered agents if present */}
                    {log.data?.ranked_agents && (
                      <div className="ml-6 p-3 bg-white rounded border border-slate-200">
                        <h5 className="text-xs font-semibold text-slate-700 mb-2">Discovered Agents:</h5>
                        <ul className="space-y-2">
                          {log.data.ranked_agents.slice(0, 3).map((agent: any, agentIndex: number) => (
                            <li key={agentIndex} className="flex items-start gap-2 text-xs p-2 bg-slate-50 rounded">
                              <div className="flex-1">
                                <div className="flex items-center gap-2">
                                  <span className="font-medium text-slate-800">{agent.domain}</span>
                                  <span className="text-xs px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded">
                                    #{agent.rank}
                                  </span>
                                </div>
                                <div className="text-slate-600 mt-1">
                                  Quality Score: {agent.quality_score}/100
                                </div>
                              </div>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Show selected agent if present */}
                    {log.data?.best_agent && (
                      <div className="ml-6 p-3 bg-green-50 rounded border border-green-200">
                        <h5 className="text-xs font-semibold text-green-800 mb-2">✓ Selected Agent:</h5>
                        <div className="text-xs">
                          <div className="font-medium text-green-900">{log.data.best_agent.domain}</div>
                          <div className="text-green-700 mt-1">
                            Quality Score: {log.data.best_agent.quality_score}/100
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
              {/* Invisible element at the end to scroll to */}
              <div ref={progressLogsEndRef} />
              </div>
            </div>
          </div>
        )}

        {plan && (
          <div className="mt-4 p-4 bg-muted rounded-lg">
            <h4 className="font-semibold mb-2">Plan Details:</h4>
            <ul className="list-disc list-inside space-y-1 text-sm">
              <li>Capabilities: {plan.capabilities.join(', ')}</li>
              {plan.estimatedCost && (
                <li>Estimated Cost: ${plan.estimatedCost.toFixed(2)}</li>
              )}
              {plan.minReputation && (
                <li>Min Reputation: {plan.minReputation.toFixed(1)} stars</li>
              )}
            </ul>
          </div>
        )}

        {error && (
          <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-sm text-red-600">{error}</p>
          </div>
        )}

      </CardContent>
    </Card>
  )
}
