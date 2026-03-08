'use client'

import { FormEvent, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Database, Download, FileUp, Search } from 'lucide-react'

import {
  DataAssetRecord,
  DataClassification,
  DataVisibility,
  downloadDataset,
  getDataset,
  listDatasets,
  uploadDataset,
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

function formatDate(value: string): string {
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

export function DataVault() {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [labName, setLabName] = useState('')
  const [uploaderName, setUploaderName] = useState('')
  const [classification, setClassification] = useState<DataClassification>('underused')
  const [visibility, setVisibility] = useState<DataVisibility>('private')
  const [tagsInput, setTagsInput] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [selectedDataset, setSelectedDataset] = useState<DataAssetRecord | null>(null)
  const [search, setSearch] = useState('')
  const [tagFilter, setTagFilter] = useState('')
  const [classificationFilter, setClassificationFilter] = useState<'all' | DataClassification>('all')

  const query = useQuery({
    queryKey: ['data-assets', search, tagFilter, classificationFilter],
    queryFn: () =>
      listDatasets({
        q: search || undefined,
        tag: tagFilter || undefined,
        classification: classificationFilter === 'all' ? undefined : classificationFilter,
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
      setFile(null)
      setFormError(null)
      void query.refetch()
    },
    onError: (error: Error) => {
      setFormError(error.message || 'Failed to upload dataset')
    },
  })

  const datasets = query.data?.datasets ?? []
  const sortedTagSuggestions = useMemo(() => {
    const tags = new Set<string>()
    datasets.forEach((dataset) => {
      dataset.tags.forEach((tag) => tags.add(tag))
    })
    return Array.from(tags).sort((a, b) => a.localeCompare(b))
  }, [datasets])

  const handleUpload = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setFormError(null)

    if (!title.trim()) {
      setFormError('Title is required.')
      return
    }
    if (!labName.trim()) {
      setFormError('Lab name is required.')
      return
    }
    if (!file) {
      setFormError('Please select a file to upload.')
      return
    }
    if (!hasAllowedExtension(file.name)) {
      setFormError(`Unsupported file type. Allowed: ${ALLOWED_EXTENSIONS.join(', ')}`)
      return
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setFormError('File exceeds 25MB limit.')
      return
    }

    const tags = tagsInput
      .split(',')
      .map((tag) => tag.trim())
      .filter(Boolean)

    await uploadMutation.mutateAsync({
      title: title.trim(),
      description: description.trim(),
      lab_name: labName.trim(),
      uploader_name: uploaderName.trim() || undefined,
      data_classification: classification,
      intended_visibility: visibility,
      tags,
      file,
    })
  }

  const handleOpenDetails = async (datasetId: string) => {
    try {
      const data = await getDataset(datasetId)
      setSelectedDataset(data)
    } catch (error: any) {
      setFormError(error.message || 'Failed to load dataset details')
    }
  }

  const handleDownload = async (dataset: DataAssetRecord) => {
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
      setFormError(error.message || 'Failed to download dataset')
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-white">Data Vault</h2>
        <p className="mt-1 text-sm text-slate-400">
          Upload and retrieve failed or underused lab datasets with privacy-ready metadata.
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

        {formError && (
          <div className="rounded-xl border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200">
            {formError}
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
        </div>

        <div className="flex flex-wrap gap-2">
          {(['all', 'underused', 'failed'] as const).map((value) => (
            <button
              key={value}
              onClick={() => setClassificationFilter(value)}
              className={`rounded-lg px-3 py-1.5 text-sm transition ${
                classificationFilter === value
                  ? 'bg-sky-500 text-white'
                  : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
              }`}
            >
              {value === 'all' ? 'All' : value}
            </button>
          ))}
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
            <div
              key={dataset.id}
              className="rounded-xl border border-white/10 bg-slate-950/40 p-4"
            >
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
                {dataset.tags.map((tag) => (
                  <span key={tag} className="rounded-md bg-slate-800 px-2 py-1">
                    #{tag}
                  </span>
                ))}
              </div>

              <div className="mt-4 flex items-center gap-2">
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
                  onClick={() => handleDownload(dataset)}
                >
                  <Download className="mr-2 h-4 w-4" />
                  Download
                </Button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <Dialog open={Boolean(selectedDataset)} onOpenChange={(open) => !open && setSelectedDataset(null)}>
        <DialogContent className="max-w-2xl border-white/15 bg-slate-950 text-slate-100">
          <DialogHeader>
            <DialogTitle>{selectedDataset?.title}</DialogTitle>
            <DialogDescription className="text-slate-400">
              Full metadata for this Data Agent dataset.
            </DialogDescription>
          </DialogHeader>
          {selectedDataset && (
            <div className="space-y-3 text-sm text-slate-200">
              <div><span className="text-slate-400">Dataset ID:</span> {selectedDataset.id}</div>
              <div><span className="text-slate-400">Filename:</span> {selectedDataset.filename}</div>
              <div><span className="text-slate-400">Lab:</span> {selectedDataset.lab_name}</div>
              <div><span className="text-slate-400">Uploader:</span> {selectedDataset.uploader_name || 'N/A'}</div>
              <div><span className="text-slate-400">Classification:</span> {selectedDataset.data_classification}</div>
              <div><span className="text-slate-400">Visibility:</span> {selectedDataset.intended_visibility}</div>
              <div><span className="text-slate-400">Size:</span> {formatBytes(selectedDataset.size_bytes)}</div>
              <div><span className="text-slate-400">Uploaded:</span> {formatDate(selectedDataset.created_at)}</div>
              <div><span className="text-slate-400">SHA-256:</span> {selectedDataset.sha256}</div>
              <div><span className="text-slate-400">Description:</span> {selectedDataset.description || 'N/A'}</div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
