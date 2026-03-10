'use client'

import { useState } from 'react'
import { CheckCircle2, ChevronDown, ChevronUp, Pause, XCircle } from 'lucide-react'

import type { TaskVerificationData } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

interface VerificationReviewCardProps {
  taskId: string
  verificationData: TaskVerificationData
  onApprove: (taskId: string) => Promise<void>
  onReject: (taskId: string, reason?: string) => Promise<void>
  approveLabel?: string
  rejectLabel?: string
}

export function VerificationReviewCard({
  taskId,
  verificationData,
  onApprove,
  onReject,
  approveLabel = 'Approve & Release Payment',
  rejectLabel = 'Reject & Refund',
}: VerificationReviewCardProps) {
  const [isRejecting, setIsRejecting] = useState(false)
  const [rejectionReason, setRejectionReason] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [showDimensions, setShowDimensions] = useState(true)
  const [showOutput, setShowOutput] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const {
    quality_score,
    dimension_scores,
    feedback,
    task_result,
    agent_name,
    ethics_passed,
  } = verificationData

  const handleApprove = async () => {
    setIsLoading(true)
    setError(null)
    try {
      await onApprove(taskId)
    } catch (approveError) {
      console.error('Failed to approve verification:', approveError)
      setError(approveError instanceof Error ? approveError.message : 'Failed to approve verification')
    } finally {
      setIsLoading(false)
    }
  }

  const handleReject = async () => {
    setIsLoading(true)
    setError(null)
    try {
      await onReject(taskId, rejectionReason || 'Quality below standards')
      setIsRejecting(false)
    } catch (rejectError) {
      console.error('Failed to reject verification:', rejectError)
      setError(rejectError instanceof Error ? rejectError.message : 'Failed to reject verification')
    } finally {
      setIsLoading(false)
    }
  }

  const getScoreColor = (score: number) => {
    if (score >= 80) return 'text-emerald-600'
    if (score >= 50) return 'text-sky-600'
    return 'text-red-600'
  }

  const getScoreBgColor = (score: number) => {
    if (score >= 80) return 'bg-emerald-500'
    if (score >= 50) return 'bg-sky-500'
    return 'bg-red-500'
  }

  const getDimensionStatus = (dimension: string, score: number) => {
    const thresholds: Record<string, number> = {
      completeness: 80,
      correctness: 85,
      academic_rigor: 75,
      clarity: 70,
      innovation: 60,
      ethics: 90,
    }
    const threshold = thresholds[dimension] || 70
    return score >= threshold
  }

  const failedDimensions = Object.entries(dimension_scores)
    .filter(([dimension, score]) => !getDimensionStatus(dimension, score))
    .map(([dimension]) => dimension.replace(/_/g, ' '))

  const ethicsScore = dimension_scores.ethics || 0
  const qualityBelowThreshold = quality_score < 50
  const ethicsBelowThreshold = ethicsScore < 50

  const paymentNotice = (() => {
    if (qualityBelowThreshold && ethicsBelowThreshold) {
      return `Quality score below 50 (${quality_score}/100) and Ethics below 50 (${ethicsScore}/100)`
    }
    if (qualityBelowThreshold) {
      return `Quality score below threshold: ${quality_score}/100 (requires 50+)`
    }
    if (ethicsBelowThreshold) {
      return `Ethics score below threshold: ${ethicsScore}/100 (requires 50+)`
    }
    if (failedDimensions.length > 0) {
      return `Failed dimensions: ${failedDimensions.join(', ')}`
    }
    return 'Requires human review'
  })()

  return (
    <div className="rounded-2xl border-2 border-sky-500/40 bg-gradient-to-br from-sky-50 to-indigo-50 p-6 shadow-lg shadow-sky-500/10">
      <div className="mb-4 flex items-start gap-3">
        <div className="rounded-full bg-sky-500/15 p-2">
          <Pause className="h-5 w-5 text-sky-600" />
        </div>
        <div className="flex-1">
          <h3 className="text-lg font-bold text-sky-700">Review Required</h3>
          <p className="text-sm text-slate-600">
            Auto-approval requires Quality ≥50 and Ethics ≥50. Please review the output.
          </p>
        </div>
      </div>

      <div className="mb-4 flex items-center gap-6">
        <div className="relative h-24 w-24 flex-shrink-0">
          <svg className="h-full w-full -rotate-90 transform">
            <circle
              cx="48"
              cy="48"
              r="40"
              stroke="currentColor"
              strokeWidth="8"
              fill="transparent"
              className="text-slate-200"
            />
            <circle
              cx="48"
              cy="48"
              r="40"
              stroke="currentColor"
              strokeWidth="8"
              fill="transparent"
              strokeDasharray={`${(quality_score / 100) * 251} 251`}
              className={getScoreColor(quality_score)}
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className={`text-2xl font-bold ${getScoreColor(quality_score)}`}>
              {quality_score}
            </span>
            <span className="text-[10px] text-slate-500">/ 100</span>
          </div>
        </div>

        <div className="flex-1">
          <div className="text-xs uppercase tracking-wider text-slate-500">Quality Score</div>
          <div className="mt-1 text-sm text-slate-700">
            Agent: <span className="font-medium text-slate-900">{agent_name}</span>
          </div>
          {!ethics_passed && (
            <div className="mt-2 flex items-center gap-1 text-xs text-red-600">
              <XCircle className="h-3 w-3" />
              <span>Ethics: {ethicsScore}/100 (requires 50+)</span>
            </div>
          )}
        </div>
      </div>

      <div className="mb-4">
        <button
          onClick={() => setShowDimensions(!showDimensions)}
          className="flex w-full items-center justify-between rounded-lg border border-slate-200 bg-white p-3 text-left text-sm transition hover:bg-slate-50"
          type="button"
        >
          <span className="font-semibold text-slate-700">Quality Dimensions</span>
          {showDimensions ? (
            <ChevronUp className="h-4 w-4 text-slate-500" />
          ) : (
            <ChevronDown className="h-4 w-4 text-slate-500" />
          )}
        </button>

        {showDimensions && (
          <div className="mt-2 space-y-2 rounded-lg border border-slate-200 bg-slate-50/50 p-3">
            {['completeness', 'correctness', 'academic_rigor', 'clarity', 'innovation', 'ethics'].map((dimension) => {
              const score = dimension_scores[dimension] || 0
              const passed = getDimensionStatus(dimension, score)
              return (
                <div key={dimension} className="space-y-1">
                  <div className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-1.5">
                      {passed ? (
                        <CheckCircle2 className="h-3 w-3 text-emerald-600" />
                      ) : (
                        <XCircle className="h-3 w-3 text-red-600" />
                      )}
                      <span className="capitalize text-slate-700">
                        {dimension.replace(/_/g, ' ')}
                      </span>
                    </div>
                    <span className={passed ? 'font-medium text-emerald-700' : 'font-medium text-red-700'}>
                      {score}/100
                    </span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-slate-200">
                    <div
                      className={`h-full ${getScoreBgColor(score)}`}
                      style={{ width: `${score}%` }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      <div className="mb-4 rounded-lg border border-slate-200 bg-slate-50/50 p-3">
        <div className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-500">
          Verifier Feedback
        </div>
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">{feedback}</p>
      </div>

      <div className="mb-4">
        <button
          onClick={() => setShowOutput(!showOutput)}
          className="flex w-full items-center justify-between rounded-lg border border-slate-200 bg-white p-3 text-left text-sm transition hover:bg-slate-50"
          type="button"
        >
          <span className="font-semibold text-slate-700">Output Preview</span>
          {showOutput ? (
            <ChevronUp className="h-4 w-4 text-slate-500" />
          ) : (
            <ChevronDown className="h-4 w-4 text-slate-500" />
          )}
        </button>

        {showOutput && (
          <div className="mt-2 max-h-48 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50/50 p-3">
            <pre className="whitespace-pre-wrap text-xs text-slate-700">
              {typeof task_result === 'string' ? task_result : JSON.stringify(task_result, null, 2)}
            </pre>
          </div>
        )}
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {!isRejecting ? (
        <div className="flex gap-2">
          <Button
            onClick={handleApprove}
            disabled={isLoading}
            className="flex-1 bg-sky-600 text-sm text-white hover:bg-sky-700"
            size="sm"
          >
            <CheckCircle2 className="mr-1.5 h-4 w-4" />
            {isLoading ? 'Processing...' : approveLabel}
          </Button>
          <Button
            onClick={() => setIsRejecting(true)}
            disabled={isLoading}
            variant="outline"
            size="sm"
            className="flex-1 border-slate-300 bg-white text-sm text-slate-700 hover:bg-slate-50"
          >
            <XCircle className="mr-1.5 h-4 w-4" />
            {rejectLabel}
          </Button>
        </div>
      ) : (
        <div className="space-y-2">
          <Textarea
            placeholder="Enter rejection reason (optional)..."
            value={rejectionReason}
            onChange={(event) => setRejectionReason(event.target.value)}
            className="min-h-[80px] border-slate-300 bg-white text-sm text-slate-700 placeholder:text-slate-400"
          />
          <div className="flex gap-2">
            <Button
              onClick={handleReject}
              disabled={isLoading}
              size="sm"
              className="flex-1 bg-red-600 text-sm text-white hover:bg-red-700"
            >
              {isLoading ? 'Processing...' : 'Confirm Rejection'}
            </Button>
            <Button
              onClick={() => setIsRejecting(false)}
              disabled={isLoading}
              variant="outline"
              size="sm"
              className="flex-1 border-slate-300 bg-white text-sm text-slate-700 hover:bg-slate-50"
            >
              Cancel
            </Button>
          </div>
        </div>
      )}

      <div className="mt-3 rounded-lg border border-sky-200 bg-sky-50/50 p-2 text-center text-xs text-slate-600">
        {paymentNotice}
      </div>
    </div>
  )
}
