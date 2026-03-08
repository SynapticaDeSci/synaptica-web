'use client'

import { FormEvent, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  Award,
  CheckCircle2,
  Copy,
  Database,
  Download,
  FileUp,
  Link2,
  Search,
  ShieldCheck,
  Star,
  XCircle,
} from 'lucide-react'

import {
  DataAssetDetailRecord,
  DataAssetRecord,
  DataClassification,
  DataProofStatus,
  DataVerificationStatus,
  DataVisibility,
  DatasetProofBundle,
  anchorDataset,
  downloadDataset,
  getDataset,
  getDatasetCitation,
  getDatasetProof,
  listDatasets,
  recordDatasetReuse,
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

function actionFeedbackClass(tone: ActionFeedback['tone']): string {
  if (tone === 'success') return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
  if (tone === 'error') return 'border-red-500/40 bg-red-500/10 text-red-200'
  return 'border-sky-500/40 bg-sky-500/10 text-sky-200'
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

  const datasets = query.data?.datasets ?? []
  const failedLeaderboard = useMemo(
    () =>
      datasets
        .filter((item) => item.data_classification === 'failed')
        .sort((a, b) => (b.reuse_count || 0) - (a.reuse_count || 0))
        .slice(0, 5),
    [datasets]
  )

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
      <div>
        <h2 className="text-2xl font-semibold text-white">Data Vault</h2>
        <p className="mt-1 text-sm text-slate-400">
          Upload, verify, and anchor underused datasets with Hedera-backed provenance.
        </p>
      </div>

      <form
        onSubmit={handleUpload}
        className="space-y-4 rounded-2xl border border-white/15 bg-slate-900/50 p-5 backdrop-blur-sm"
      >
        <div className="flex items-center gap-2 text-sm font-medium text-white">
          <FileUp className="h-4 w-4 text-sky-400" />
          Upload dataset
        </div>

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

        <Button
          type="submit"
          disabled={uploadMutation.isPending}
          className="bg-gradient-to-r from-sky-500 to-indigo-500 text-white hover:opacity-90"
        >
          {uploadMutation.isPending ? 'Uploading...' : 'Upload dataset'}
        </Button>
      </form>

      <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-amber-200">
          <Award className="h-4 w-4" />
          Most reused failed datasets
        </div>
        {failedLeaderboard.length === 0 ? (
          <p className="text-sm text-amber-100/80">No failed datasets reused yet.</p>
        ) : (
          <div className="grid gap-2">
            {failedLeaderboard.map((item, index) => (
              <div
                key={item.id}
                className="flex items-center justify-between rounded-lg border border-amber-500/20 bg-black/20 px-3 py-2 text-sm text-amber-100"
              >
                <span>
                  {index + 1}. {item.title}
                </span>
                <span className="inline-flex items-center gap-1 rounded-md bg-amber-400/20 px-2 py-0.5 text-xs">
                  <Star className="h-3 w-3" />
                  {item.reuse_count}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

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
        open={Boolean(selectedDataset)}
        onOpenChange={(open) => {
          if (!open) {
            setSelectedDataset(null)
            setSelectedDatasetProof(null)
            setSelectedDatasetCitation(null)
            setVerifyFeedback(null)
            setAnchorFeedback(null)
            setReuseFeedback(null)
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
