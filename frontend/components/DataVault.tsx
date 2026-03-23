'use client'

import { FormEvent, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import * as XLSX from 'xlsx'
import {
  CheckCircle2,
  Copy,
  Database,
  Download,
  Eye,
  FileUp,
  Link2,
  Search,
  ShieldCheck,
  XCircle,
} from 'lucide-react'

import {
  AgentRecord,
  ApiRequestError,
  DataAssetDetailRecord,
  DataAssetRecord,
  DataClassification,
  HolAgentRecord,
  DatasetHolUseErrorDetail,
  DatasetHolUseResponse,
  DataProofStatus,
  DataVerificationStatus,
  DataVisibility,
  DatasetProofBundle,
  anchorDataset,
  downloadDataset,
  getAgents,
  getDataset,
  getDatasetCitation,
  getDatasetProof,
  invokeDatasetHolAgent,
  listDatasets,
  recordDatasetReuse,
  searchHolAgents,
  uploadDataset,
  verifyDataset,
} from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

const MAX_UPLOAD_BYTES = 25 * 1024 * 1024
const ALLOWED_EXTENSIONS = ['.csv', '.tsv', '.json', '.txt', '.xlsx', '.zip']

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(value?: string): string {
  if (!value) return 'N/A'
  try {
    return new Date(value).toLocaleString()
  } catch {
    return value
  }
}

function hasAllowedExtension(filename: string): boolean {
  const lower = filename.toLowerCase()
  return ALLOWED_EXTENSIONS.some((ext) => lower.endsWith(ext))
}

function statusBadgeClass(value: string): string {
  if (value === 'passed' || value === 'anchored') return 'bg-emerald-500/20 text-emerald-200'
  if (value === 'manifest_pinned') return 'bg-sky-500/20 text-sky-200'
  if (value === 'failed') return 'bg-red-500/20 text-red-200'
  return 'bg-slate-700/70 text-slate-200'
}

type ActionFeedback = {
  tone: 'info' | 'success' | 'error'
  message: string
}

const EMPTY_DATASETS: DataAssetRecord[] = []

type DatasetPreview =
  | {
      mode: 'table'
      headers: string[]
      rows: string[][]
      note?: string
    }
  | {
      mode: 'json' | 'text' | 'unsupported'
      text: string
      note?: string
    }

function actionFeedbackClass(tone: ActionFeedback['tone']): string {
  if (tone === 'success') return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
  if (tone === 'error') return 'border-red-500/40 bg-red-500/10 text-red-200'
  return 'border-sky-500/40 bg-sky-500/10 text-sky-200'
}

function normalizeHolErrorDetail(detail: unknown): DatasetHolUseErrorDetail | null {
  if (!detail || typeof detail !== 'object') return null
  return detail as DatasetHolUseErrorDetail
}

function extractHolSessionStatus(brokerResponse: Record<string, any> | null | undefined): {
  mode: string
  fallbackReason?: string | null
} | null {
  if (!brokerResponse || typeof brokerResponse !== 'object') return null
  const mode = typeof brokerResponse.mode === 'string' ? brokerResponse.mode.trim() : ''
  if (!mode) return null
  return {
    mode,
    fallbackReason:
      typeof brokerResponse.fallback_reason === 'string' ? brokerResponse.fallback_reason : null,
  }
}

function holCandidateStatus(agent: HolAgentRecord): {
  label: string
  tone: 'success' | 'warning' | 'error'
  reason: string
  recommendedTransport?: string
} {
  const transports = (agent.transports ?? []).map((item) => String(item).trim().toLowerCase()).filter(Boolean)
  const protocol = String(agent.protocol ?? '').trim().toLowerCase()
  const adapter = String(agent.adapter ?? '').trim().toLowerCase()
  const availability = String(agent.availability_status ?? '').trim().toLowerCase()
  const hasHttp = transports.includes('http')
  const hasUrl = Boolean(agent.source_url)

  if (agent.available === false || ['offline', 'inactive', 'error'].includes(availability)) {
    return {
      label: 'Blocked',
      tone: 'error',
      reason: availability ? `Availability is ${availability}.` : 'Agent is marked unavailable.',
    }
  }
  if (['a2a', 'uagent'].includes(protocol)) {
    return {
      label: 'Blocked',
      tone: 'error',
      reason: `Protocol ${protocol} is not broker-chatable in this flow.`,
    }
  }
  if (['a2a-registry-adapter', 'agentverse-adapter'].includes(adapter)) {
    return {
      label: 'Blocked',
      tone: 'error',
      reason: `Adapter ${adapter} is not broker-chatable in this flow.`,
    }
  }
  if (hasHttp) {
    return {
      label: 'Likely usable',
      tone: 'success',
      reason: 'HTTP transport is advertised.',
      recommendedTransport: 'http',
    }
  }
  if (hasUrl) {
    return {
      label: 'Possible',
      tone: 'warning',
      reason: 'Source URL exists, but transport is not explicit.',
    }
  }
  return {
    label: 'Unclear',
    tone: 'warning',
    reason: 'No explicit HTTP transport or source URL metadata.',
  }
}

function holCandidateBadgeClass(tone: 'success' | 'warning' | 'error'): string {
  if (tone === 'success') return 'bg-emerald-500/20 text-emerald-200'
  if (tone === 'error') return 'bg-red-500/20 text-red-200'
  return 'bg-amber-500/20 text-amber-200'
}

function getFileExtension(filename: string): string {
  const idx = filename.lastIndexOf('.')
  if (idx === -1) return ''
  return filename.slice(idx).toLowerCase()
}

function clipText(value: string, maxChars = 12000): { text: string; truncated: boolean } {
  if (value.length <= maxChars) {
    return { text: value, truncated: false }
  }
  return { text: value.slice(0, maxChars), truncated: true }
}

function buildTabularPreview(text: string, delimiter: string): DatasetPreview {
  const rawLines = text.split(/\r?\n/).filter((line) => line.trim().length > 0)
  if (rawLines.length === 0) {
    return {
      mode: 'text',
      text: 'This dataset is empty.',
    }
  }

  const maxRows = 31
  const limitedLines = rawLines.slice(0, maxRows)
  const rows = limitedLines.map((line) => line.split(delimiter).map((part) => part.trim()))
  const maxColumns = rows.reduce((acc, row) => Math.max(acc, row.length), 1)
  const normalized = rows.map((row) =>
    Array.from({ length: maxColumns }, (_, idx) => (row[idx] === undefined ? '' : row[idx]))
  )

  return {
    mode: 'table',
    headers: normalized[0] || ['Column 1'],
    rows: normalized.slice(1),
    note:
      rawLines.length > maxRows
        ? `Showing first ${maxRows - 1} data rows (${rawLines.length - 1} total).`
        : undefined,
  }
}

function buildDatasetPreview(filename: string, text: string): DatasetPreview {
  const extension = getFileExtension(filename)
  if (extension === '.csv') return buildTabularPreview(text, ',')
  if (extension === '.tsv') return buildTabularPreview(text, '\t')

  if (extension === '.json') {
    try {
      const parsed = JSON.parse(text)
      const pretty = JSON.stringify(parsed, null, 2)
      const clipped = clipText(pretty)
      return {
        mode: 'json',
        text: clipped.text,
        note: clipped.truncated ? 'Preview truncated to first 12,000 characters.' : undefined,
      }
    } catch {
      const clipped = clipText(text)
      return {
        mode: 'text',
        text: clipped.text,
        note: clipped.truncated ? 'Preview truncated to first 12,000 characters.' : 'Invalid JSON format.',
      }
    }
  }

  if (extension === '.txt') {
    const clipped = clipText(text)
    return {
      mode: 'text',
      text: clipped.text,
      note: clipped.truncated ? 'Preview truncated to first 12,000 characters.' : undefined,
    }
  }

  return {
    mode: 'unsupported',
    text: `Preview is not available for ${extension || 'this file type'}. Download to inspect full content.`,
  }
}

function buildXlsxPreview(arrayBuffer: ArrayBuffer): DatasetPreview {
  const workbook = XLSX.read(arrayBuffer, { type: 'array' })
  const firstSheetName = workbook.SheetNames[0]
  if (!firstSheetName) {
    return {
      mode: 'text',
      text: 'No worksheets found in this workbook.',
    }
  }

  const sheet = workbook.Sheets[firstSheetName]
  if (!sheet) {
    return {
      mode: 'text',
      text: `Unable to read worksheet "${firstSheetName}".`,
    }
  }

  const rawRows = XLSX.utils.sheet_to_json<(string | number | boolean | null)[]>(sheet, {
    header: 1,
    defval: '',
    blankrows: false,
  })

  if (!rawRows.length) {
    return {
      mode: 'text',
      text: `Worksheet "${firstSheetName}" is empty.`,
    }
  }

  const maxRows = 31
  const maxColumns = 20
  const limitedRows = rawRows.slice(0, maxRows).map((row) => row.slice(0, maxColumns))
  const columnCount = Math.max(1, ...limitedRows.map((row) => row.length))
  const normalizedRows = limitedRows.map((row) =>
    Array.from({ length: columnCount }, (_, idx) => {
      const value = row[idx]
      return value === null || value === undefined ? '' : String(value)
    })
  )

  const notes: string[] = [`Sheet: ${firstSheetName}`]
  if (rawRows.length > maxRows) {
    notes.push(`showing first ${maxRows - 1} data rows`)
  }
  const maxRawColumns = Math.max(0, ...rawRows.map((row) => row.length))
  if (maxRawColumns > maxColumns) {
    notes.push(`showing first ${maxColumns} columns`)
  }

  return {
    mode: 'table',
    headers: normalizedRows[0] || ['Column 1'],
    rows: normalizedRows.slice(1),
    note: notes.join(' · '),
  }
}

export function DataVault() {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [labName, setLabName] = useState('')
  const [uploaderName, setUploaderName] = useState('')
  const [classification, setClassification] = useState<DataClassification>('underused')
  const [visibility, setVisibility] = useState<DataVisibility>('private')
  const [tagsInput, setTagsInput] = useState('')
  const [failedReason, setFailedReason] = useState('')
  const [reuseDomainsInput, setReuseDomainsInput] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [selectedDataset, setSelectedDataset] = useState<DataAssetDetailRecord | null>(null)
  const [selectedDatasetProof, setSelectedDatasetProof] = useState<DatasetProofBundle | null>(null)
  const [selectedDatasetCitation, setSelectedDatasetCitation] = useState<Record<string, any> | null>(null)
  const [previewDataset, setPreviewDataset] = useState<DataAssetRecord | null>(null)
  const [previewData, setPreviewData] = useState<DatasetPreview | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [previewLoadingId, setPreviewLoadingId] = useState<string | null>(null)
  const [isUploadDialogOpen, setIsUploadDialogOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [tagFilter, setTagFilter] = useState('')
  const [labFilter, setLabFilter] = useState('')
  const [classificationFilter, setClassificationFilter] = useState<'all' | DataClassification>('all')
  const [verificationFilter, setVerificationFilter] = useState<'all' | DataVerificationStatus>('all')
  const [proofFilter, setProofFilter] = useState<'all' | DataProofStatus>('all')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [verifyFeedback, setVerifyFeedback] = useState<ActionFeedback | null>(null)
  const [anchorFeedback, setAnchorFeedback] = useState<ActionFeedback | null>(null)
  const [reuseFeedback, setReuseFeedback] = useState<ActionFeedback | null>(null)
  const [holAgentFeedback, setHolAgentFeedback] = useState<ActionFeedback | null>(null)
  const [holUaidOverride, setHolUaidOverride] = useState('')
  const [holSearchQuery, setHolSearchQuery] = useState('')
  const [holTransport, setHolTransport] = useState('')
  const [holDiagnostics, setHolDiagnostics] = useState<DatasetHolUseErrorDetail | null>(null)
  const [holSessionStatus, setHolSessionStatus] = useState<{
    mode: string
    fallbackReason?: string | null
  } | null>(null)
  const [copiedCitation, setCopiedCitation] = useState(false)

  const query = useQuery({
    queryKey: [
      'data-assets',
      search,
      tagFilter,
      labFilter,
      classificationFilter,
      verificationFilter,
      proofFilter,
    ],
    queryFn: () =>
      listDatasets({
        q: search || undefined,
        tag: tagFilter || undefined,
        lab_name: labFilter || undefined,
        classification: classificationFilter === 'all' ? undefined : classificationFilter,
        verification_status: verificationFilter === 'all' ? undefined : verificationFilter,
        proof_status: proofFilter === 'all' ? undefined : proofFilter,
        limit: 100,
        offset: 0,
      }),
  })

  const localAgentsQuery = useQuery<AgentRecord[], Error>({
    queryKey: ['data-vault-local-agents'],
    queryFn: getAgents,
    staleTime: 60_000,
  })

  const localHolAgents = useMemo(
    () =>
      (localAgentsQuery.data ?? [])
        .filter(
          (agent) =>
            (agent.hol_registration_status || '').toLowerCase() === 'registered' &&
            typeof agent.hol_uaid === 'string' &&
            agent.hol_uaid.trim()
        )
        .sort((a, b) => a.name.localeCompare(b.name)),
    [localAgentsQuery.data]
  )

  const holCandidatePreviewQuery = useMemo(() => {
    if (holSearchQuery.trim()) return holSearchQuery.trim()
    if (!selectedDataset) return 'data agent'
    return [
      selectedDataset.title,
      selectedDataset.lab_name,
      selectedDataset.data_classification,
      'data agent',
    ]
      .map((item) => String(item || '').trim())
      .filter(Boolean)
      .join(' ')
  }, [holSearchQuery, selectedDataset])

  const holCandidatesQuery = useQuery<{ agents: HolAgentRecord[]; query: string }, Error>({
    queryKey: ['data-vault-hol-candidates', selectedDataset?.id ?? null, holCandidatePreviewQuery],
    queryFn: () => searchHolAgents(holCandidatePreviewQuery, { onlyAvailable: true }),
    enabled: Boolean(selectedDataset),
    staleTime: 30_000,
  })

  const uploadMutation = useMutation({
    mutationFn: uploadDataset,
    onSuccess: () => {
      setTitle('')
      setDescription('')
      setLabName('')
      setUploaderName('')
      setClassification('underused')
      setVisibility('private')
      setTagsInput('')
      setFailedReason('')
      setReuseDomainsInput('')
      setFile(null)
      setErrorMessage(null)
      setIsUploadDialogOpen(false)
      void query.refetch()
    },
    onError: (error: Error) => {
      setErrorMessage(error.message || 'Failed to upload dataset')
    },
  })

  const verifyMutation = useMutation({
    mutationFn: verifyDataset,
    onMutate: () => {
      setVerifyFeedback({
        tone: 'info',
        message: 'Verification started. Running checksum, file type, empty-file, and duplicate-hash checks...',
      })
    },
    onSuccess: async (asset) => {
      setErrorMessage(null)
      setSelectedDataset(asset)
      setSelectedDatasetProof(asset.proof_bundle ?? null)
      const checks = asset.verification_report?.checks as Record<string, { passed?: boolean }> | undefined
      const checkResults = checks ? Object.values(checks) : []
      const totalChecks = checkResults.length
      const passedChecks = checkResults.filter((entry) => entry?.passed === true).length
      const failedChecks = totalChecks - passedChecks
      const checkedAt = asset.verification_report?.checked_at
      const checkedAtText = checkedAt ? ` at ${formatDate(checkedAt)}` : ''
      if (asset.verification_status === 'passed') {
        setVerifyFeedback({
          tone: 'success',
          message:
            totalChecks > 0
              ? `Verification complete${checkedAtText}. ${passedChecks}/${totalChecks} checks passed.`
              : `Verification complete${checkedAtText}. All checks passed.`,
        })
      } else {
        setVerifyFeedback({
          tone: 'error',
          message:
            totalChecks > 0
              ? `Verification complete${checkedAtText}. ${failedChecks}/${totalChecks} checks failed. Review the report below.`
              : `Verification complete${checkedAtText}. One or more checks failed.`,
        })
      }
      await query.refetch()
    },
    onError: (error: Error) => {
      const message = error.message || 'Verification failed'
      setErrorMessage(message)
      setVerifyFeedback({
        tone: 'error',
        message: `Verification failed. ${message}`,
      })
    },
  })

  const anchorMutation = useMutation({
    mutationFn: anchorDataset,
    onMutate: () => {
      setAnchorFeedback({
        tone: 'info',
        message: 'Anchoring started. Pinning manifest to IPFS, then submitting proof to Hedera HCS...',
      })
    },
    onSuccess: async (proof) => {
      setErrorMessage(null)
      setSelectedDatasetProof(proof)
      if (selectedDataset) {
        const refreshed = await getDataset(selectedDataset.id)
        setSelectedDataset(refreshed)
      }
      const cidText = proof.manifest_cid ? `CID ${proof.manifest_cid}.` : 'Manifest CID generated.'
      const topicText = proof.hcs_topic_id ? ` Topic ${proof.hcs_topic_id}.` : ''
      setAnchorFeedback({
        tone: 'success',
        message: `Anchoring complete. ${cidText}${topicText}`,
      })
      await query.refetch()
    },
    onError: (error: Error) => {
      const message = error.message || 'Anchoring failed'
      setErrorMessage(message)
      setAnchorFeedback({
        tone: 'error',
        message: `Anchoring failed. ${message}`,
      })
    },
  })

  const reuseMutation = useMutation({
    mutationFn: recordDatasetReuse,
    onMutate: () => {
      setReuseFeedback({
        tone: 'info',
        message: 'Recording reuse event...',
      })
    },
    onSuccess: async (result) => {
      setErrorMessage(null)
      if (selectedDataset) {
        const refreshed = await getDataset(selectedDataset.id)
        setSelectedDataset(refreshed)
      }
      setReuseFeedback({
        tone: 'success',
        message: `Reuse event recorded at ${formatDate(result.last_reused_at)}. Total reuse count: ${result.reuse_count}.`,
      })
      await query.refetch()
    },
    onError: (error: Error) => {
      const message = error.message || 'Failed to record reuse event'
      setErrorMessage(message)
      setReuseFeedback({
        tone: 'error',
        message: `Reuse event failed. ${message}`,
      })
    },
  })

  const holAgentMutation = useMutation({
    mutationFn: async (input: { datasetId: string; uaid?: string; searchQuery?: string; transport?: string }) =>
      invokeDatasetHolAgent(input.datasetId, {
        uaid: input.uaid,
        search_query: input.searchQuery,
        transport: input.transport,
      }),
    onMutate: () => {
      setHolDiagnostics(null)
      setHolSessionStatus(null)
      setHolAgentFeedback({
        tone: 'info',
        message: 'Starting HOL data-agent session...',
      })
    },
    onSuccess: async (result: DatasetHolUseResponse) => {
      setErrorMessage(null)
      setHolDiagnostics(null)
      const sessionStatus = extractHolSessionStatus(result.broker_response)
      setHolSessionStatus(sessionStatus)
      if (selectedDataset) {
        const refreshed = await getDataset(selectedDataset.id)
        setSelectedDataset(refreshed)
        setSelectedDatasetProof(refreshed.proof_bundle ?? null)
      }
      const agentName =
        String(result.selected_agent?.name || result.selected_agent?.uaid || 'HOL agent')
      setHolAgentFeedback({
        tone: 'success',
        message:
          sessionStatus?.mode === 'direct'
            ? `${agentName} responded via direct HOL fallback ${result.session_id}.`
            : `${agentName} responded via HOL session ${result.session_id}.`,
      })
      await query.refetch()
    },
    onError: (error: Error) => {
      const message = error.message || 'HOL data-agent call failed'
      const detail =
        error instanceof ApiRequestError ? normalizeHolErrorDetail(error.detail) : null
      setHolSessionStatus(null)
      setHolDiagnostics(detail)
      setErrorMessage(message)
      setHolAgentFeedback({
        tone: 'error',
        message: `HOL data-agent call failed. ${message}`,
      })
    },
  })

  const datasets = query.data?.datasets ?? EMPTY_DATASETS
  const sortedTagSuggestions = useMemo(() => {
    const tags = new Set<string>()
    datasets.forEach((dataset) => {
      dataset.tags.forEach((tag) => tags.add(tag))
    })
    return Array.from(tags).sort((a, b) => a.localeCompare(b))
  }, [datasets])

  const handleUpload = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setErrorMessage(null)

    if (!title.trim()) {
      setErrorMessage('Title is required.')
      return
    }
    if (!labName.trim()) {
      setErrorMessage('Lab name is required.')
      return
    }
    if (!file) {
      setErrorMessage('Please select a file to upload.')
      return
    }
    if (!hasAllowedExtension(file.name)) {
      setErrorMessage(`Unsupported file type. Allowed: ${ALLOWED_EXTENSIONS.join(', ')}`)
      return
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setErrorMessage('File exceeds 25MB limit.')
      return
    }

    const tags = tagsInput.split(',').map((tag) => tag.trim()).filter(Boolean)
    const reuseDomains = reuseDomainsInput
      .split(',')
      .map((entry) => entry.trim())
      .filter(Boolean)

    await uploadMutation.mutateAsync({
      title: title.trim(),
      description: description.trim(),
      lab_name: labName.trim(),
      uploader_name: uploaderName.trim() || undefined,
      data_classification: classification,
      intended_visibility: visibility,
      tags,
      failed_reason: failedReason.trim() || undefined,
      reuse_domains: reuseDomains,
      file,
    })
  }

  const handleOpenDetails = async (datasetId: string) => {
    try {
      setVerifyFeedback(null)
      setAnchorFeedback(null)
      setReuseFeedback(null)
      setHolAgentFeedback(null)
      setHolUaidOverride('')
      setHolSearchQuery('')
      setHolTransport('')
      setHolDiagnostics(null)
      setHolSessionStatus(null)
      const detail = await getDataset(datasetId)
      setSelectedDataset(detail)
      setSelectedDatasetProof(detail.proof_bundle ?? null)
      const citation = await getDatasetCitation(datasetId)
      setSelectedDatasetCitation(citation.citation)
    } catch (error: any) {
      setErrorMessage(error.message || 'Failed to load dataset details')
    }
  }

  const handleDownloadDataset = async (dataset: DataAssetRecord) => {
    try {
      const blob = await downloadDataset(dataset.id)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = dataset.filename
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
    } catch (error: any) {
      setErrorMessage(error.message || 'Failed to download dataset')
    }
  }

  const handlePreviewDataset = async (dataset: DataAssetRecord) => {
    setPreviewDataset(dataset)
    setPreviewData(null)
    setPreviewError(null)
    setPreviewLoadingId(dataset.id)

    try {
      const extension = getFileExtension(dataset.filename)
      if (extension === '.zip') {
        setPreviewData({
          mode: 'unsupported',
          text: 'Preview is not available for .zip files. Download to inspect full content.',
        })
        return
      }

      const blob = await downloadDataset(dataset.id)
      if (extension === '.xlsx') {
        const arrayBuffer = await blob.arrayBuffer()
        setPreviewData(buildXlsxPreview(arrayBuffer))
      } else {
        const text = await blob.text()
        setPreviewData(buildDatasetPreview(dataset.filename, text))
      }
    } catch (error: any) {
      setPreviewError(error.message || 'Failed to preview dataset')
    } finally {
      setPreviewLoadingId(null)
    }
  }

  const handleRefreshProof = async (datasetId: string) => {
    try {
      const proof = await getDatasetProof(datasetId)
      setSelectedDatasetProof(proof)
    } catch (error: any) {
      setErrorMessage(error.message || 'Failed to load proof bundle')
    }
  }

  const handleCopyCitation = async () => {
    if (!selectedDatasetCitation) return
    await navigator.clipboard.writeText(JSON.stringify(selectedDatasetCitation, null, 2))
    setCopiedCitation(true)
    setTimeout(() => setCopiedCitation(false), 1500)
  }

  const handleDownloadProof = () => {
    if (!selectedDatasetProof) return
    const blob = new Blob([JSON.stringify(selectedDatasetProof, null, 2)], {
      type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `proof-${selectedDatasetProof.dataset_id}.json`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-white">Data Vault</h2>
          <p className="mt-1 text-sm text-slate-400">
            Upload, verify, and anchor underused datasets with Hedera-backed provenance.
          </p>
        </div>
        <Button
          type="button"
          onClick={() => {
            setErrorMessage(null)
            setIsUploadDialogOpen(true)
          }}
          className="bg-gradient-to-r from-sky-500 to-indigo-500 text-white hover:opacity-90"
        >
          <FileUp className="mr-2 h-4 w-4" />
          Upload dataset
        </Button>
      </div>

      <Dialog open={isUploadDialogOpen} onOpenChange={setIsUploadDialogOpen}>
        <DialogContent className="max-h-[85vh] max-w-4xl overflow-y-auto border-white/15 bg-slate-950 text-slate-100">
          <DialogHeader>
            <DialogTitle>Upload dataset</DialogTitle>
            <DialogDescription className="text-slate-400">
              Add failed or underused lab data to the Data Agent catalog.
            </DialogDescription>
          </DialogHeader>
          <form
            onSubmit={handleUpload}
            className="space-y-4 rounded-2xl border border-white/15 bg-slate-900/50 p-5 backdrop-blur-sm"
          >
            <div className="grid gap-3 md:grid-cols-2">
              <Input
                placeholder="Dataset title"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                className="border-white/10 bg-slate-950/40 text-white"
              />
              <Input
                placeholder="Lab name"
                value={labName}
                onChange={(event) => setLabName(event.target.value)}
                className="border-white/10 bg-slate-950/40 text-white"
              />
              <Input
                placeholder="Uploader name (optional)"
                value={uploaderName}
                onChange={(event) => setUploaderName(event.target.value)}
                className="border-white/10 bg-slate-950/40 text-white"
              />
              <Input
                placeholder="Tags (comma separated)"
                value={tagsInput}
                onChange={(event) => setTagsInput(event.target.value)}
                className="border-white/10 bg-slate-950/40 text-white"
              />
              <Input
                placeholder="Failed reason (optional)"
                value={failedReason}
                onChange={(event) => setFailedReason(event.target.value)}
                className="border-white/10 bg-slate-950/40 text-white"
              />
              <Input
                placeholder="Potential reuse domains (comma separated)"
                value={reuseDomainsInput}
                onChange={(event) => setReuseDomainsInput(event.target.value)}
                className="border-white/10 bg-slate-950/40 text-white"
              />
            </div>

            <Textarea
              placeholder="Description (optional)"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              className="min-h-[90px] border-white/10 bg-slate-950/40 text-white"
            />

            <div className="grid gap-3 md:grid-cols-3">
              <select
                value={classification}
                onChange={(event) => setClassification(event.target.value as DataClassification)}
                className="h-10 rounded-md border border-white/10 bg-slate-950/40 px-3 text-sm text-white"
              >
                <option value="underused">Underused</option>
                <option value="failed">Failed</option>
              </select>
              <select
                value={visibility}
                onChange={(event) => setVisibility(event.target.value as DataVisibility)}
                className="h-10 rounded-md border border-white/10 bg-slate-950/40 px-3 text-sm text-white"
              >
                <option value="private">Private (default)</option>
                <option value="org">Org shared</option>
                <option value="public">Public</option>
              </select>
              <Input
                type="file"
                accept={ALLOWED_EXTENSIONS.join(',')}
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                className="border-white/10 bg-slate-950/40 text-white file:mr-3 file:border-0 file:bg-transparent file:text-slate-200"
              />
            </div>

            <p className="text-xs text-slate-400">
              Allowed file types: {ALLOWED_EXTENSIONS.join(', ')}. Max file size: 25MB.
            </p>

            {errorMessage && (
              <div className="rounded-xl border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200">
                {errorMessage}
              </div>
            )}

            <div className="flex justify-end">
              <Button
                type="submit"
                disabled={uploadMutation.isPending}
                className="bg-gradient-to-r from-sky-500 to-indigo-500 text-white hover:opacity-90"
              >
                {uploadMutation.isPending ? 'Uploading...' : 'Upload dataset'}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <div className="space-y-4 rounded-2xl border border-white/15 bg-slate-900/50 p-5 backdrop-blur-sm">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="text-sm font-medium text-white">Dataset catalog</div>
          <div className="text-xs text-slate-400">{query.data?.total ?? 0} datasets</div>
        </div>

        <div className="grid gap-3 md:grid-cols-3">
          <div className="relative md:col-span-2">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
            <Input
              placeholder="Search title, description, lab..."
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              className="border-white/10 bg-slate-950/40 pl-9 text-white"
            />
          </div>
          <Input
            placeholder="Filter by exact tag"
            value={tagFilter}
            onChange={(event) => setTagFilter(event.target.value)}
            className="border-white/10 bg-slate-950/40 text-white"
          />
          <Input
            placeholder="Filter by lab name"
            value={labFilter}
            onChange={(event) => setLabFilter(event.target.value)}
            className="border-white/10 bg-slate-950/40 text-white md:col-span-3"
          />
        </div>

        <div className="grid gap-2 md:grid-cols-3">
          <select
            value={classificationFilter}
            onChange={(event) => setClassificationFilter(event.target.value as 'all' | DataClassification)}
            className="h-10 rounded-md border border-white/10 bg-slate-950/40 px-3 text-sm text-white"
          >
            <option value="all">All classifications</option>
            <option value="failed">Failed</option>
            <option value="underused">Underused</option>
          </select>
          <select
            value={verificationFilter}
            onChange={(event) => setVerificationFilter(event.target.value as 'all' | DataVerificationStatus)}
            className="h-10 rounded-md border border-white/10 bg-slate-950/40 px-3 text-sm text-white"
          >
            <option value="all">All verification states</option>
            <option value="passed">Passed</option>
            <option value="failed">Failed</option>
            <option value="pending">Pending</option>
          </select>
          <select
            value={proofFilter}
            onChange={(event) => setProofFilter(event.target.value as 'all' | DataProofStatus)}
            className="h-10 rounded-md border border-white/10 bg-slate-950/40 px-3 text-sm text-white"
          >
            <option value="all">All proof states</option>
            <option value="anchored">Anchored</option>
            <option value="manifest_pinned">Manifest pinned</option>
            <option value="unanchored">Unanchored</option>
            <option value="failed">Failed</option>
          </select>
        </div>

        {sortedTagSuggestions.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {sortedTagSuggestions.slice(0, 12).map((tag) => (
              <button
                key={tag}
                onClick={() => setTagFilter(tag)}
                className="rounded-md bg-slate-800/70 px-2 py-1 text-xs text-slate-300 hover:bg-slate-700"
              >
                #{tag}
              </button>
            ))}
          </div>
        )}

        {query.isLoading && (
          <div className="rounded-xl border border-white/10 bg-slate-950/40 p-5 text-sm text-slate-300">
            Loading datasets...
          </div>
        )}

        {query.isError && (
          <div className="rounded-xl border border-red-500/40 bg-red-500/10 p-5 text-sm text-red-200">
            {(query.error as Error)?.message || 'Failed to load datasets'}
          </div>
        )}

        {!query.isLoading && !query.isError && datasets.length === 0 && (
          <div className="rounded-xl border border-white/10 bg-slate-950/40 p-5 text-sm text-slate-300">
            No datasets found for the selected filters.
          </div>
        )}

        <div className="grid gap-3">
          {datasets.map((dataset) => (
            <div key={dataset.id} className="rounded-xl border border-white/10 bg-slate-950/40 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2 text-white">
                    <Database className="h-4 w-4 text-sky-400" />
                    <span className="font-medium">{dataset.title}</span>
                  </div>
                  <p className="mt-1 text-sm text-slate-300">{dataset.description || 'No description'}</p>
                </div>
                <div className="text-right text-xs text-slate-400">
                  <div>{formatBytes(dataset.size_bytes)}</div>
                  <div>{formatDate(dataset.created_at)}</div>
                </div>
              </div>

              <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-300">
                <span className="rounded-md bg-slate-800 px-2 py-1">{dataset.data_classification}</span>
                <span className="rounded-md bg-slate-800 px-2 py-1">{dataset.lab_name}</span>
                <span className="rounded-md bg-slate-800 px-2 py-1">{dataset.intended_visibility}</span>
                <span className={`rounded-md px-2 py-1 ${statusBadgeClass(dataset.verification_status)}`}>
                  Local Verified: {dataset.verification_status}
                </span>
                <span className={`rounded-md px-2 py-1 ${dataset.manifest_cid ? 'bg-sky-500/20 text-sky-200' : 'bg-slate-700/70 text-slate-200'}`}>
                  IPFS Manifest
                </span>
                <span className={`rounded-md px-2 py-1 ${statusBadgeClass(dataset.proof_status)}`}>
                  Hedera: {dataset.proof_status}
                </span>
                <span className="rounded-md bg-amber-500/20 px-2 py-1 text-amber-200">
                  Reuse: {dataset.reuse_count}
                </span>
                {dataset.tags.map((tag) => (
                  <span key={tag} className="rounded-md bg-slate-800 px-2 py-1">
                    #{tag}
                  </span>
                ))}
              </div>

              <div className="mt-4 flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className="border-white/20 bg-transparent text-slate-200 hover:bg-white/10"
                  onClick={() => handleOpenDetails(dataset.id)}
                >
                  View details
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="border-white/20 bg-transparent text-slate-200 hover:bg-white/10"
                  onClick={() => handlePreviewDataset(dataset)}
                  disabled={previewLoadingId === dataset.id}
                >
                  <Eye className="mr-2 h-4 w-4" />
                  {previewLoadingId === dataset.id ? 'Loading preview...' : 'Preview data'}
                </Button>
                <Button
                  type="button"
                  className="bg-slate-100 text-slate-900 hover:bg-white"
                  onClick={() => handleDownloadDataset(dataset)}
                >
                  <Download className="mr-2 h-4 w-4" />
                  Download
                </Button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <Dialog
        open={Boolean(previewDataset)}
        onOpenChange={(open) => {
          if (!open) {
            setPreviewDataset(null)
            setPreviewData(null)
            setPreviewError(null)
            setPreviewLoadingId(null)
          }
        }}
      >
        <DialogContent className="max-h-[85vh] max-w-4xl overflow-hidden border-white/15 bg-slate-950 text-slate-100">
          <DialogHeader>
            <DialogTitle>{previewDataset ? `Preview: ${previewDataset.title}` : 'Dataset preview'}</DialogTitle>
            <DialogDescription className="text-slate-400">
              {previewDataset ? `${previewDataset.filename} · ${formatBytes(previewDataset.size_bytes)}` : 'Preview dataset content before downloading.'}
            </DialogDescription>
          </DialogHeader>

          {previewDataset && (
            <div className="max-h-[70vh] space-y-3 overflow-y-auto pr-1">
              {previewLoadingId === previewDataset.id && !previewData && !previewError && (
                <div className="rounded-lg border border-white/10 bg-slate-900/50 p-4 text-sm text-slate-300">
                  Loading preview...
                </div>
              )}

              {previewError && (
                <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-200">
                  {previewError}
                </div>
              )}

              {previewData?.mode === 'table' && (
                <div className="space-y-2">
                  <div className="overflow-auto rounded-lg border border-white/10 bg-slate-900/50">
                    <table className="w-full min-w-[640px] border-collapse text-left text-xs text-slate-200">
                      <thead className="bg-slate-800/80 text-slate-100">
                        <tr>
                          {previewData.headers.map((header, idx) => (
                            <th key={`header-${idx}`} className="border-b border-white/10 px-3 py-2 font-semibold">
                              {header || `Column ${idx + 1}`}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {previewData.rows.length === 0 ? (
                          <tr>
                            <td className="px-3 py-2 text-slate-400" colSpan={previewData.headers.length}>
                              No data rows available.
                            </td>
                          </tr>
                        ) : (
                          previewData.rows.map((row, rowIdx) => (
                            <tr key={`row-${rowIdx}`} className="border-b border-white/5 last:border-b-0">
                              {row.map((cell, colIdx) => (
                                <td key={`cell-${rowIdx}-${colIdx}`} className="px-3 py-2 align-top text-slate-300">
                                  {cell}
                                </td>
                              ))}
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                  {previewData.note && <p className="text-xs text-slate-400">{previewData.note}</p>}
                </div>
              )}

              {previewData && previewData.mode !== 'table' && (
                <div className="space-y-2">
                  <div className="rounded-lg border border-white/10 bg-slate-900/50 p-3">
                    <pre className="max-h-[55vh] overflow-auto whitespace-pre-wrap text-xs text-slate-200">
                      {previewData.text}
                    </pre>
                  </div>
                  {previewData.note && <p className="text-xs text-slate-400">{previewData.note}</p>}
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(selectedDataset)}
        onOpenChange={(open) => {
          if (!open) {
            setSelectedDataset(null)
            setSelectedDatasetProof(null)
            setSelectedDatasetCitation(null)
            setVerifyFeedback(null)
            setAnchorFeedback(null)
            setReuseFeedback(null)
            setHolAgentFeedback(null)
            setHolUaidOverride('')
            setHolSearchQuery('')
            setHolTransport('')
            setHolDiagnostics(null)
            setHolSessionStatus(null)
          }
        }}
      >
        <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto border-white/15 bg-slate-950 text-slate-100">
          <DialogHeader>
            <DialogTitle>{selectedDataset?.title}</DialogTitle>
            <DialogDescription className="text-slate-400">
              Trust summary, proof bundle, and reuse actions.
            </DialogDescription>
          </DialogHeader>
          {selectedDataset && (
            <div className="space-y-4 text-sm text-slate-200">
              <div className="grid gap-2 md:grid-cols-2">
                <div><span className="text-slate-400">Dataset ID:</span> {selectedDataset.id}</div>
                <div><span className="text-slate-400">Filename:</span> {selectedDataset.filename}</div>
                <div><span className="text-slate-400">Lab:</span> {selectedDataset.lab_name}</div>
                <div><span className="text-slate-400">Uploader:</span> {selectedDataset.uploader_name || 'N/A'}</div>
                <div><span className="text-slate-400">Classification:</span> {selectedDataset.data_classification}</div>
                <div><span className="text-slate-400">Visibility:</span> {selectedDataset.intended_visibility}</div>
                <div><span className="text-slate-400">Size:</span> {formatBytes(selectedDataset.size_bytes)}</div>
                <div><span className="text-slate-400">Uploaded:</span> {formatDate(selectedDataset.created_at)}</div>
              </div>

              <div className="flex flex-wrap gap-2">
                <span className={`inline-flex items-center gap-1 rounded-md px-2 py-1 ${statusBadgeClass(selectedDataset.verification_status)}`}>
                  {selectedDataset.verification_status === 'passed' ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
                  Local Verified
                </span>
                <span className={`inline-flex items-center gap-1 rounded-md px-2 py-1 ${selectedDataset.manifest_cid ? 'bg-sky-500/20 text-sky-200' : 'bg-slate-700/70 text-slate-200'}`}>
                  <Link2 className="h-3 w-3" />
                  IPFS Manifest
                </span>
                <span className={`inline-flex items-center gap-1 rounded-md px-2 py-1 ${statusBadgeClass(selectedDataset.proof_status)}`}>
                  <ShieldCheck className="h-3 w-3" />
                  Hedera Anchored
                </span>
              </div>

              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  onClick={() => verifyMutation.mutate(selectedDataset.id)}
                  disabled={verifyMutation.isPending}
                  className="bg-sky-600 text-white hover:bg-sky-500"
                  title="Run integrity and quality checks (hash match, file parsing, empty-file and duplicate detection)."
                  aria-label="Verify dataset integrity and quality checks"
                >
                  {verifyMutation.isPending ? 'Verifying...' : 'Verify'}
                </Button>
                <Button
                  type="button"
                  onClick={() => anchorMutation.mutate(selectedDataset.id)}
                  disabled={anchorMutation.isPending}
                  className="bg-indigo-600 text-white hover:bg-indigo-500"
                  title="Create a canonical manifest, pin it to IPFS, and anchor the provenance record to Hedera HCS."
                  aria-label="Anchor dataset provenance to Hedera with IPFS manifest"
                >
                  {anchorMutation.isPending ? 'Anchoring...' : 'Anchor to Hedera'}
                </Button>
                <Button
                  type="button"
                  onClick={() => reuseMutation.mutate(selectedDataset.id)}
                  disabled={reuseMutation.isPending}
                  className="bg-amber-500 text-black hover:bg-amber-400"
                  title="Record that this dataset was reused to update impact metrics and leaderboard ranking."
                  aria-label="Record dataset reuse event"
                >
                  {reuseMutation.isPending ? 'Recording...' : 'I reused this dataset'}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="border-white/20 bg-transparent text-slate-200 hover:bg-white/10"
                  onClick={() => handleRefreshProof(selectedDataset.id)}
                  title="Reload the latest proof bundle (verification, IPFS manifest CID, and Hedera anchor status)."
                  aria-label="Refresh proof bundle status"
                >
                  Refresh proof
                </Button>
              </div>

              <div className="rounded-lg border border-white/10 bg-slate-900/60 p-3">
                <p className="mb-2 text-xs uppercase tracking-wide text-slate-400">Ask HOL agent about this dataset</p>
                {localHolAgents.length > 0 && (
                  <div className="mb-3 rounded-lg border border-sky-500/20 bg-sky-500/5 p-3">
                    <p className="text-xs uppercase tracking-wide text-sky-200">
                      Your Registered HOL Agents
                    </p>
                    <p className="mt-1 text-xs text-slate-300">
                      Preferred demo path. Pick one to prefill the UAID override and chat your own registered agent directly.
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {localHolAgents.map((agent) => (
                        <Button
                          key={agent.agent_id}
                          type="button"
                          variant="outline"
                          className="border-sky-400/30 bg-transparent text-sky-100 hover:bg-sky-500/10"
                          onClick={() => {
                            setHolUaidOverride(agent.hol_uaid || '')
                            setHolTransport('http')
                          }}
                        >
                          {agent.name}
                        </Button>
                      ))}
                    </div>
                  </div>
                )}
                <div className="grid gap-2 md:grid-cols-2">
                  <Input
                    placeholder="Optional UAID override"
                    value={holUaidOverride}
                    onChange={(event) => setHolUaidOverride(event.target.value)}
                    className="border-white/10 bg-slate-950/40 text-white"
                  />
                  <Input
                    placeholder="Optional HOL search query override"
                    value={holSearchQuery}
                    onChange={(event) => setHolSearchQuery(event.target.value)}
                    className="border-white/10 bg-slate-950/40 text-white"
                  />
                  <select
                    value={holTransport}
                    onChange={(event) => setHolTransport(event.target.value)}
                    className="h-10 rounded-md border border-white/10 bg-slate-950/40 px-3 text-sm text-white"
                  >
                    <option value="">Auto transport</option>
                    <option value="http">Force http</option>
                    <option value="a2a">Force a2a</option>
                  </select>
                  <Button
                    type="button"
                    onClick={() =>
                      holAgentMutation.mutate({
                        datasetId: selectedDataset.id,
                        uaid: holUaidOverride.trim() || undefined,
                        searchQuery: holSearchQuery.trim() || undefined,
                        transport: holTransport.trim() || undefined,
                      })
                    }
                    disabled={holAgentMutation.isPending}
                    className="bg-emerald-600 text-white hover:bg-emerald-500 md:justify-self-start"
                  >
                    {holAgentMutation.isPending ? 'Asking HOL agent...' : 'Ask HOL agent about this dataset'}
                  </Button>
                </div>
                <p className="mt-2 text-xs text-slate-400">
                  Leave UAID empty to auto-discover. Use search query override to broaden or narrow HOL discovery, and transport to force broker routing when you know the agent expects `http` or `a2a`.
                </p>

                <div className="mt-4 rounded-lg border border-white/10 bg-slate-950/40 p-3">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <div>
                      <p className="text-xs uppercase tracking-wide text-slate-400">Search HOL first</p>
                      <p className="text-xs text-slate-500">
                        Preview query: {holCandidatesQuery.data?.query || holCandidatePreviewQuery}
                      </p>
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      className="border-white/20 bg-transparent text-slate-200 hover:bg-white/10"
                      onClick={() => void holCandidatesQuery.refetch()}
                      disabled={holCandidatesQuery.isFetching}
                    >
                      {holCandidatesQuery.isFetching ? 'Searching...' : 'Refresh HOL search'}
                    </Button>
                  </div>

                  {holCandidatesQuery.isLoading && (
                    <div className="rounded-md border border-white/10 bg-slate-900/60 px-3 py-2 text-xs text-slate-300">
                      Searching HOL candidates...
                    </div>
                  )}

                  {holCandidatesQuery.isError && (
                    <div className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
                      {(holCandidatesQuery.error as Error)?.message || 'Failed to search HOL candidates'}
                    </div>
                  )}

                  {!holCandidatesQuery.isLoading && !holCandidatesQuery.isError && (
                    <div className="space-y-2">
                      {(holCandidatesQuery.data?.agents ?? []).slice(0, 6).map((agent) => {
                        const status = holCandidateStatus(agent)
                        return (
                          <div
                            key={agent.uaid}
                            className="rounded-md border border-white/10 bg-slate-900/60 p-3"
                          >
                            <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                              <div className="min-w-0">
                                <div className="flex flex-wrap items-center gap-2">
                                  <div className="font-medium text-white">{agent.name || agent.uaid}</div>
                                  <span className={`rounded-md px-2 py-0.5 text-[11px] ${holCandidateBadgeClass(status.tone)}`}>
                                    {status.label}
                                  </span>
                                  {agent.registry && (
                                    <span className="rounded-md bg-slate-800 px-2 py-0.5 text-[11px] text-slate-300">
                                      {agent.registry}
                                    </span>
                                  )}
                                </div>
                                <div className="mt-1 break-all font-mono text-[11px] text-slate-400">
                                  {agent.uaid}
                                </div>
                                {agent.description && (
                                  <p className="mt-2 text-xs text-slate-300">{agent.description}</p>
                                )}
                                <div className="mt-2 flex flex-wrap gap-1.5">
                                  {(agent.transports ?? []).slice(0, 6).map((transport) => (
                                    <span
                                      key={`${agent.uaid}-${transport}`}
                                      className="rounded-full bg-slate-800/60 px-2 py-0.5 text-[11px] uppercase tracking-wide text-slate-200"
                                    >
                                      {transport}
                                    </span>
                                  ))}
                                  {agent.protocol && (
                                    <span className="rounded-full bg-slate-800/60 px-2 py-0.5 text-[11px] text-slate-200">
                                      proto:{agent.protocol}
                                    </span>
                                  )}
                                  {agent.availability_status && (
                                    <span className="rounded-full bg-slate-800/60 px-2 py-0.5 text-[11px] text-slate-200">
                                      {agent.availability_status}
                                    </span>
                                  )}
                                </div>
                                <div className="mt-2 text-[11px] text-slate-400">{status.reason}</div>
                              </div>
                              <div className="flex shrink-0 flex-wrap gap-2">
                                <Button
                                  type="button"
                                  variant="outline"
                                  className="border-white/20 bg-transparent text-slate-200 hover:bg-white/10"
                                  onClick={() => {
                                    setHolUaidOverride(agent.uaid)
                                    if (status.recommendedTransport) {
                                      setHolTransport(status.recommendedTransport)
                                    }
                                  }}
                                >
                                  Use this agent
                                </Button>
                                <Button
                                  type="button"
                                  className="bg-emerald-600 text-white hover:bg-emerald-500"
                                  onClick={() =>
                                    holAgentMutation.mutate({
                                      datasetId: selectedDataset.id,
                                      uaid: agent.uaid,
                                      searchQuery: holSearchQuery.trim() || undefined,
                                      transport: holTransport.trim() || status.recommendedTransport || undefined,
                                    })
                                  }
                                  disabled={holAgentMutation.isPending || status.tone === 'error'}
                                  title={status.tone === 'error' ? status.reason : 'Run this HOL agent now'}
                                >
                                  Run this agent
                                </Button>
                              </div>
                            </div>
                          </div>
                        )
                      })}

                      {(holCandidatesQuery.data?.agents ?? []).length === 0 && (
                        <div className="rounded-md border border-white/10 bg-slate-900/60 px-3 py-2 text-xs text-slate-300">
                          No HOL candidates found for this query.
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>

              {verifyFeedback && (
                <div className={`rounded-lg border px-3 py-2 text-xs ${actionFeedbackClass(verifyFeedback.tone)}`}>
                  {verifyFeedback.message}
                </div>
              )}

              {anchorFeedback && (
                <div className={`rounded-lg border px-3 py-2 text-xs ${actionFeedbackClass(anchorFeedback.tone)}`}>
                  {anchorFeedback.message}
                </div>
              )}

              {reuseFeedback && (
                <div className={`rounded-lg border px-3 py-2 text-xs ${actionFeedbackClass(reuseFeedback.tone)}`}>
                  {reuseFeedback.message}
                </div>
              )}

              {holAgentFeedback && (
                <div className={`rounded-lg border px-3 py-2 text-xs ${actionFeedbackClass(holAgentFeedback.tone)}`}>
                  {holAgentFeedback.message}
                </div>
              )}

              {holSessionStatus?.mode === 'direct' && (
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-100">
                  <p className="mb-1 font-medium uppercase tracking-wide text-amber-200">HOL fallback mode</p>
                  <p>Using direct UAID messaging because broker session creation was transiently unavailable.</p>
                  {holSessionStatus.fallbackReason && (
                    <p className="mt-2 text-amber-200">{holSessionStatus.fallbackReason}</p>
                  )}
                </div>
              )}

              {holDiagnostics && (
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-100">
                  <p className="mb-2 font-medium uppercase tracking-wide text-amber-200">HOL diagnostics</p>
                  {holDiagnostics.search_queries && holDiagnostics.search_queries.length > 0 && (
                    <div className="mb-2">
                      <div className="text-amber-300">Search queries</div>
                      <div>{holDiagnostics.search_queries.join(' | ')}</div>
                    </div>
                  )}
                  {holDiagnostics.rejected_candidates && holDiagnostics.rejected_candidates.length > 0 && (
                    <div className="mb-2 space-y-1">
                      <div className="text-amber-300">Rejected candidates</div>
                      {holDiagnostics.rejected_candidates.slice(0, 5).map((candidate, index) => (
                        <div key={`${candidate.uaid || candidate.name || 'candidate'}-${index}`}>
                          {candidate.name || candidate.uaid || 'Unknown agent'}: {candidate.reason || 'Rejected by broker-chatable filter'}
                        </div>
                      ))}
                    </div>
                  )}
                  {holDiagnostics.attempted_errors && holDiagnostics.attempted_errors.length > 0 && (
                    <div className="space-y-1">
                      <div className="text-amber-300">Attempted broker errors</div>
                      {holDiagnostics.attempted_errors.slice(0, 5).map((item, index) => (
                        <div key={`attempted-error-${index}`}>{item}</div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {selectedDataset.proof_bundle?.verification_report && (
                <div className="rounded-lg border border-white/10 bg-slate-900/60 p-3">
                  <p className="mb-2 text-xs uppercase tracking-wide text-slate-400">Verification report</p>
                  <pre className="max-h-44 overflow-auto whitespace-pre-wrap text-xs text-slate-200">
                    {JSON.stringify(selectedDataset.proof_bundle.verification_report, null, 2)}
                  </pre>
                </div>
              )}

              {selectedDatasetProof && (
                <div className="rounded-lg border border-white/10 bg-slate-900/60 p-3">
                  <p className="mb-2 text-xs uppercase tracking-wide text-slate-400">Proof bundle</p>
                  <div className="mb-3 grid gap-1 text-xs text-slate-300">
                    <div><span className="text-slate-500">Manifest CID:</span> {selectedDatasetProof.manifest_cid || 'N/A'}</div>
                    <div><span className="text-slate-500">Topic:</span> {selectedDatasetProof.hcs_topic_id || 'N/A'}</div>
                    <div><span className="text-slate-500">Anchor status:</span> {selectedDatasetProof.hcs_message_status || 'N/A'}</div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      className="border-white/20 bg-transparent text-slate-200 hover:bg-white/10"
                      onClick={handleDownloadProof}
                    >
                      Download proof bundle
                    </Button>
                  </div>
                </div>
              )}

              {selectedDatasetCitation && (
                <div className="rounded-lg border border-white/10 bg-slate-900/60 p-3">
                  <p className="mb-2 text-xs uppercase tracking-wide text-slate-400">Citation JSON</p>
                  <pre className="max-h-44 overflow-auto whitespace-pre-wrap text-xs text-slate-200">
                    {JSON.stringify(selectedDatasetCitation, null, 2)}
                  </pre>
                  <Button
                    type="button"
                    variant="outline"
                    className="mt-3 border-white/20 bg-transparent text-slate-200 hover:bg-white/10"
                    onClick={handleCopyCitation}
                  >
                    <Copy className="mr-2 h-4 w-4" />
                    {copiedCitation ? 'Copied' : 'Copy citation JSON'}
                  </Button>
                </div>
              )}

              {selectedDataset.hol_sessions.length > 0 && (
                <div className="rounded-lg border border-white/10 bg-slate-900/60 p-3">
                  <p className="mb-2 text-xs uppercase tracking-wide text-slate-400">Recent HOL sessions</p>
                  <div className="grid gap-2">
                    {selectedDataset.hol_sessions
                      .slice()
                      .reverse()
                      .map((entry, index) => {
                        const selectedAgent = entry.selected_agent as Record<string, any> | undefined
                        const agentName = String(
                          selectedAgent?.name || selectedAgent?.uaid || 'HOL agent'
                        )
                        const responsePreview = JSON.stringify(entry.broker_response ?? {}, null, 2)
                        return (
                          <div
                            key={`${entry.session_id || 'session'}-${index}`}
                            className="rounded-md border border-white/10 bg-black/30 p-2 text-xs text-slate-200"
                          >
                            <div><span className="text-slate-500">Agent:</span> {agentName}</div>
                            <div><span className="text-slate-500">Session:</span> {String(entry.session_id || 'N/A')}</div>
                            <div>
                              <span className="text-slate-500">Mode:</span>{' '}
                              {String((entry.broker_response as Record<string, any> | undefined)?.mode || 'session')}
                            </div>
                            <div><span className="text-slate-500">Started:</span> {formatDate(String(entry.created_at || ''))}</div>
                            {typeof (entry.broker_response as Record<string, any> | undefined)?.fallback_reason === 'string' && (
                              <div>
                                <span className="text-slate-500">Fallback reason:</span>{' '}
                                {String((entry.broker_response as Record<string, any>).fallback_reason)}
                              </div>
                            )}
                            <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap text-xs text-slate-300">
                              {responsePreview}
                            </pre>
                          </div>
                        )
                      })}
                  </div>
                </div>
              )}

              {selectedDataset.similar_datasets.length > 0 && (
                <div className="rounded-lg border border-white/10 bg-slate-900/60 p-3">
                  <p className="mb-2 text-xs uppercase tracking-wide text-slate-400">Similar datasets</p>
                  <div className="grid gap-2">
                    {selectedDataset.similar_datasets.map((entry) => (
                      <div
                        key={entry.id}
                        className="rounded-md border border-white/10 bg-black/30 px-2 py-1 text-xs text-slate-200"
                      >
                        {entry.title} ({entry.data_classification}) score: {entry.similarity_score}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
