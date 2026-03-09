'use client'

import { useTaskStore } from '@/store/taskStore'
import { VerificationReviewCard } from '@/components/VerificationReviewCard'

export function VerificationCard() {
  const { verificationData, taskId, approveVerification, rejectVerification } = useTaskStore()

  if (!verificationData || !taskId) {
    return null
  }

  return (
    <VerificationReviewCard
      taskId={taskId}
      verificationData={verificationData}
      onApprove={approveVerification}
      onReject={rejectVerification}
    />
  )
}
