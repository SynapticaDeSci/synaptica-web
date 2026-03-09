'use client'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { useTaskStore } from '@/store/taskStore'
import { CheckCircle2, XCircle, Download, Star, FileText, FileJson } from 'lucide-react'
import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import jsPDF from 'jspdf'
import { Document, Paragraph, TextRun, HeadingLevel, AlignmentType, Packer } from 'docx'
import { saveAs } from 'file-saver'

export function TaskResults() {
  const { result, selectedAgent, status, progressLogs } = useTaskStore()
  const [rating, setRating] = useState<number>(0)

  if (status !== 'COMPLETE' && status !== 'FAILED' && status !== 'CANCELLED') {
    return null
  }

  if (!result) {
    return null
  }

  // Extract verification details from progress logs
  const verificationLog = progressLogs?.find(log => log.step.startsWith('verification_'))
  const verificationData = verificationLog?.data
  const qualityScore = verificationData?.quality_score
  const isAutoApproved = verificationData?.auto_approved
  const isHumanApproved = verificationData?.human_approved
  const rejectionReason = verificationData?.rejection_reason

  // Extract orchestrator's synthesized response
  // The orchestrator should return a markdown-formatted response in result.data.orchestrator_response
  const getOrchestratorResponse = (): string | null => {
    if (!result.data) return null

    return result.data.orchestrator_response
  }

  const orchestratorResponse = getOrchestratorResponse()

  const handleDownload = () => {
    // Generate and download report
    if (result.data) {
      const blob = new Blob([JSON.stringify(result.data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'task-report.json'
      a.click()
      URL.revokeObjectURL(url)
    }
  }

  const handleDownloadPDF = () => {
    if (!result.data) return

    const doc = new jsPDF()
    const pageWidth = doc.internal.pageSize.getWidth()
    const margin = 15
    let yPosition = 20

    // Helper to add text with word wrap
    const addText = (text: string, fontSize: number, isBold: boolean = false, align: 'left' | 'center' = 'left') => {
      doc.setFontSize(fontSize)
      doc.setFont('helvetica', isBold ? 'bold' : 'normal')

      const lines = doc.splitTextToSize(text, pageWidth - (margin * 2))

      if (align === 'center') {
        lines.forEach((line: string) => {
          const textWidth = doc.getTextWidth(line)
          doc.text(line, (pageWidth - textWidth) / 2, yPosition)
          yPosition += fontSize * 0.4
        })
      } else {
        doc.text(lines, margin, yPosition)
        yPosition += lines.length * fontSize * 0.4
      }

      yPosition += 5
    }

    // Title
    addText('ProvidAI Research Report', 20, true, 'center')
    yPosition += 5

    // Timestamp
    const timestamp = new Date().toLocaleString()
    addText(`Generated: ${timestamp}`, 10, false, 'center')
    yPosition += 10

    // Status
    addText(`Status: ${result.success ? 'COMPLETED ✓' : 'FAILED ✗'}`, 14, true)

    // Agent info
    if (selectedAgent) {
      addText(`Agent: ${selectedAgent.name}`, 12, false)
    }
    yPosition += 5

    // Verification Summary
    if (qualityScore !== undefined || isAutoApproved || isHumanApproved) {
      addText('Verification Summary', 16, true)

      if (qualityScore !== undefined) {
        addText(`Quality Score: ${qualityScore}/100`, 12, false)
      }

      if (isAutoApproved) {
        addText('✓ Auto-Approved - High quality output met all standards', 11, false)
      }

      if (isHumanApproved) {
        addText('✓ Human Approved - Manually reviewed and approved', 11, false)
      }

      yPosition += 5
    }

    // Rejection reason
    if (rejectionReason) {
      addText('Rejection Reason', 14, true)
      addText(rejectionReason, 11, false)
      yPosition += 5
    }

    // Research Findings
    if (orchestratorResponse) {
      addText('Research Findings', 16, true)
      // Remove markdown formatting for PDF (simple version)
      const cleanText = orchestratorResponse
        .replace(/#{1,6}\s/g, '')
        .replace(/\*\*/g, '')
        .replace(/\*/g, '')
        .replace(/`/g, '')
      addText(cleanText, 11, false)
    }

    // Verifier's Report
    if (result.report) {
      if (yPosition > 250) {
        doc.addPage()
        yPosition = 20
      }
      addText("Verifier's Report", 14, true)
      addText(result.report, 11, false)
    }

    // Save PDF
    doc.save('research-report.pdf')
  }

  const handleDownloadWord = async () => {
    if (!result.data) return

    const paragraphs: Paragraph[] = []

    // Title
    paragraphs.push(
      new Paragraph({
        text: 'ProvidAI Research Report',
        heading: HeadingLevel.HEADING_1,
        alignment: AlignmentType.CENTER,
        spacing: { after: 200 },
      })
    )

    // Timestamp
    const timestamp = new Date().toLocaleString()
    paragraphs.push(
      new Paragraph({
        text: `Generated: ${timestamp}`,
        alignment: AlignmentType.CENTER,
        spacing: { after: 400 },
      })
    )

    // Status
    paragraphs.push(
      new Paragraph({
        children: [
          new TextRun({
            text: `Status: ${result.success ? 'COMPLETED ✓' : 'FAILED ✗'}`,
            bold: true,
            size: 28,
          }),
        ],
        spacing: { after: 200 },
      })
    )

    // Agent info
    if (selectedAgent) {
      paragraphs.push(
        new Paragraph({
          text: `Agent: ${selectedAgent.name}`,
          spacing: { after: 200 },
        })
      )
    }

    // Verification Summary
    if (qualityScore !== undefined || isAutoApproved || isHumanApproved) {
      paragraphs.push(
        new Paragraph({
          text: 'Verification Summary',
          heading: HeadingLevel.HEADING_2,
          spacing: { before: 400, after: 200 },
        })
      )

      if (qualityScore !== undefined) {
        paragraphs.push(
          new Paragraph({
            text: `Quality Score: ${qualityScore}/100`,
            spacing: { after: 100 },
          })
        )
      }

      if (isAutoApproved) {
        paragraphs.push(
          new Paragraph({
            text: '✓ Auto-Approved - High quality output met all standards',
            spacing: { after: 100 },
          })
        )
      }

      if (isHumanApproved) {
        paragraphs.push(
          new Paragraph({
            text: '✓ Human Approved - Manually reviewed and approved',
            spacing: { after: 100 },
          })
        )
      }
    }

    // Rejection reason
    if (rejectionReason) {
      paragraphs.push(
        new Paragraph({
          text: 'Rejection Reason',
          heading: HeadingLevel.HEADING_2,
          spacing: { before: 400, after: 200 },
        })
      )
      paragraphs.push(
        new Paragraph({
          text: rejectionReason,
          spacing: { after: 200 },
        })
      )
    }

    // Research Findings
    if (orchestratorResponse) {
      paragraphs.push(
        new Paragraph({
          text: 'Research Findings',
          heading: HeadingLevel.HEADING_2,
          spacing: { before: 400, after: 200 },
        })
      )

      // Split by paragraphs and add each
      const cleanText = orchestratorResponse
        .replace(/#{1,6}\s/g, '')
        .replace(/\*\*/g, '')
        .replace(/\*/g, '')
        .replace(/`/g, '')

      cleanText.split('\n\n').forEach((para) => {
        if (para.trim()) {
          paragraphs.push(
            new Paragraph({
              text: para.trim(),
              spacing: { after: 200 },
            })
          )
        }
      })
    }

    // Verifier's Report
    if (result.report) {
      paragraphs.push(
        new Paragraph({
          text: "Verifier's Report",
          heading: HeadingLevel.HEADING_2,
          spacing: { before: 400, after: 200 },
        })
      )
      paragraphs.push(
        new Paragraph({
          text: result.report,
          spacing: { after: 200 },
        })
      )
    }

    // Create document
    const doc = new Document({
      sections: [
        {
          properties: {},
          children: paragraphs,
        },
      ],
    })

    // Generate and save
    const blob = await Packer.toBlob(doc)
    saveAs(blob, 'research-report.docx')
  }

  const handleRating = (stars: number) => {
    setRating(stars)
    // TODO: Submit rating to ERC-8004 ReputationRegistry
    console.log('Rating submitted:', stars)
  }

  return (
    <Card className={result.success ? 'border-green-200' : 'border-red-200'}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {result.success ? (
            <>
              <CheckCircle2 className="h-6 w-6 text-green-500" />
              Task Complete!
            </>
          ) : (
            <>
              <XCircle className="h-6 w-6 text-red-500" />
              Task Failed Verification
            </>
          )}
        </CardTitle>
        <CardDescription>
          {result.success
            ? `Payment has been released to ${selectedAgent?.name || 'agent'}`
            : `Rejected: Payment has been refunded to your wallet`}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Verification Details */}
        {(qualityScore !== undefined || isAutoApproved || isHumanApproved || rejectionReason) && (
          <div className={`p-4 rounded-lg border ${result.success ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200'}`}>
            <h4 className="font-semibold mb-3 text-sm">Verification Summary</h4>
            <div className="space-y-2 text-sm">
              {qualityScore !== undefined && (
                <div className="flex items-center justify-between">
                  <span className="text-slate-700">Quality Score:</span>
                  <span className={`font-semibold px-2 py-1 rounded ${
                    qualityScore >= 80 ? 'bg-emerald-100 text-emerald-700' :
                    qualityScore >= 50 ? 'bg-yellow-100 text-yellow-700' :
                    'bg-red-100 text-red-700'
                  }`}>
                    {qualityScore}/100
                  </span>
                </div>
              )}
              {isAutoApproved && (
                <div className="flex items-center gap-2">
                  <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full bg-green-100 text-green-700 text-xs font-medium">
                    <CheckCircle2 className="h-3 w-3" />
                    Auto-Approved
                  </span>
                  <span className="text-xs text-slate-600">High quality output met all standards</span>
                </div>
              )}
              {isHumanApproved && (
                <div className="flex items-center gap-2">
                  <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full bg-blue-100 text-blue-700 text-xs font-medium">
                    <CheckCircle2 className="h-3 w-3" />
                    Human Approved
                  </span>
                  <span className="text-xs text-slate-600">Manually reviewed and approved</span>
                </div>
              )}
              {rejectionReason && (
                <div className="p-3 bg-red-100 border border-red-200 rounded">
                  <div className="font-semibold text-red-800 text-xs mb-1">Rejection Reason:</div>
                  <p className="text-red-700 text-xs">{rejectionReason}</p>
                </div>
              )}
            </div>
          </div>
        )}

        {result.report && (
          <div className="p-4 bg-muted rounded-lg">
            <h4 className="font-semibold mb-2">Verifier&apos;s Report:</h4>
            <p className="text-sm whitespace-pre-wrap">{result.report}</p>
          </div>
        )}

        {result.data && (
          <div className="p-4 bg-muted rounded-lg">
            {orchestratorResponse ? (
              <div className="prose prose-sm max-w-none dark:prose-invert">
                <ReactMarkdown>{orchestratorResponse}</ReactMarkdown>
              </div>
            ) : (
              <div>
                <h4 className="font-semibold mb-2 text-sm text-slate-700">Raw Output:</h4>
                <pre className="text-xs overflow-auto max-h-96 bg-slate-50 p-3 rounded border border-slate-200">
                  {JSON.stringify(result.data, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}

        {result.error && (
          <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
            <h4 className="font-semibold mb-2 text-red-800">Error:</h4>
            <p className="text-sm text-red-600">{result.error}</p>
          </div>
        )}

        <div className="flex flex-col gap-4">
          {result.success && (
            <>
              <div className="flex flex-wrap gap-2">
                <div className="flex gap-2">
                  <Button onClick={handleDownloadPDF} variant="outline">
                    <FileText className="mr-2 h-4 w-4" />
                    Download PDF
                  </Button>
                  <Button onClick={handleDownloadWord} variant="outline">
                    <FileText className="mr-2 h-4 w-4" />
                    Download Word
                  </Button>
                  <Button onClick={handleDownload} variant="outline">
                    <FileJson className="mr-2 h-4 w-4" />
                    Download JSON
                  </Button>
                </div>
              </div>
              {selectedAgent && (
                <div className="flex items-center gap-2">
                  <span className="text-sm">Rate this agent:</span>
                  {[1, 2, 3, 4, 5].map((stars) => (
                    <button
                      key={stars}
                      onClick={() => handleRating(stars)}
                      className={rating >= stars ? 'text-yellow-400' : 'text-gray-300'}
                    >
                      <Star className="h-5 w-5 fill-current" />
                    </button>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
