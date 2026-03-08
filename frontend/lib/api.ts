/**
 * API client for ProvidAI backend
 */

const API_BASE_URL = '/api';
const BACKEND_BASE_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

export interface CreateTaskRequest {
  description: string;
  capability_requirements?: string;
  budget_limit?: number;
  min_reputation_score?: number;
  verification_mode?: string;
}

export interface TaskResponse {
  task_id: string;
  status: string;
  message?: string;
  error?: string;
}

export interface TaskStatusResponse {
  task_id: string;
  status: string;
  current_step?: string;
  progress?: Array<{
    step: string;
    status: string;
    timestamp: string;
    data?: any;
  }>;
  plan?: {
    capabilities?: string[];
    budgetLimit?: number;
    minReputation?: number;
    estimatedCost?: number;
  };
  selected_agent?: {
    agentId: string;
    name: string;
    description?: string;
    reputation: number;
    price: number;
    currency: string;
    capabilities: string[];
  };
  payment_details?: {
    paymentId: string;
    amount: number;
    currency: string;
    fromAccount: string;
    toAccount: string;
    agentName: string;
    description?: string;
  };
  execution_logs?: Array<{
    timestamp: string;
    message: string;
    source: string;
  }>;
  result?: {
    success: boolean;
    data?: any;
    error?: string;
    report?: string;
  };
  error?: string;
  verification_pending?: boolean;
  verification_data?: {
    todo_id: string;
    payment_id: string;
    quality_score: number;
    dimension_scores: Record<string, number>;
    feedback: string;
    task_result: any;
    agent_name: string;
    ethics_passed: boolean;
  };
}

/**
 * Create a new task
 */
export async function createTask(request: CreateTaskRequest): Promise<TaskResponse> {
  const response = await fetch(`${BACKEND_BASE_URL}/execute`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: 'Failed to create task' }));
    throw new Error(error.error || 'Failed to create task');
  }

  return response.json();
}

/**
 * List available agents from registry
 */
export async function getAgents(): Promise<AgentRecord[]> {
  const data = await fetchAgents();
  return Array.isArray(data.agents) ? data.agents : [];
}

/**
 * Get task status
 */
export async function getTask(taskId: string): Promise<TaskStatusResponse> {
  const response = await fetch(`${BACKEND_BASE_URL}/api/tasks/${taskId}`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: 'Task not found' }));
    throw new Error(error.error || 'Task not found');
  }

  return response.json();
}

/**
 * Poll task status until completion or error
 */
export async function pollTaskStatus(
  taskId: string,
  onStatusUpdate?: (status: TaskStatusResponse) => void,
  pollInterval: number = 2000,
  maxAttempts: number = 150 // 5 minutes with 2s interval
): Promise<TaskStatusResponse> {
  let attempts = 0;

  return new Promise((resolve, reject) => {
    const poll = async () => {
      try {
        attempts++;
        const status = await getTask(taskId);

        // Notify caller of status update
        if (onStatusUpdate) {
          onStatusUpdate(status);
        }

        // Check if task is complete
        const normalizedStatus = status.status?.toLowerCase();
        if (normalizedStatus === 'completed' || normalizedStatus === 'failed') {
          resolve(status);
          return;
        }

        // Check if max attempts reached
        if (attempts >= maxAttempts) {
          reject(new Error('Polling timeout: task did not complete'));
          return;
        }

        // Continue polling
        setTimeout(poll, pollInterval);
      } catch (error) {
        reject(error);
      }
    };

    poll();
  });
}

/**
 * Approve a payment
 */
export async function approvePayment(paymentId: string): Promise<{ success: boolean; message?: string; error?: string }> {
  const response = await fetch(`${API_BASE_URL}/payments/${paymentId}/approve`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: 'Failed to approve payment' }));
    throw new Error(error.error || 'Failed to approve payment');
  }

  return response.json();
}

/**
 * Reject a payment
 */
export async function rejectPayment(paymentId: string, reason?: string): Promise<{ success: boolean; message?: string; error?: string }> {
  const response = await fetch(`${API_BASE_URL}/payments/${paymentId}/reject`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ reason }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: 'Failed to reject payment' }));
    throw new Error(error.error || 'Failed to reject payment');
  }

  return response.json();
}

// Marketplace ----------------------------------------------------------------

export interface AgentPricing {
  rate: number;
  currency: string;
  rate_type: string;
}

export interface AgentRecord {
  agent_id: string;
  name: string;
  agent_type?: string;
  description?: string;
  capabilities: string[];
  categories: string[];
  status: string;
  endpoint_url?: string;
  health_check_url?: string;
  pricing: AgentPricing;
  reputation_score?: number;
  contact_email?: string;
  logo_url?: string;
  erc8004_metadata_uri?: string;
  metadata_cid?: string;
  metadata_gateway_url?: string;
  hedera_account_id?: string;
  created_at?: string;
}

export interface AgentsListResponse {
  total: number;
  agents: AgentRecord[];
  sync_status?: string;
  synced_at?: string;
}

export interface AgentSubmissionPayload {
  agent_id: string;
  name: string;
  description: string;
  capabilities: string[];
  categories?: string[];
  endpoint_url: string;
  health_check_url?: string;
  base_rate: number;
  currency?: string;
  rate_type?: string;
  hedera_account?: string;
  logo_url?: string;
  contact_email?: string;
}

export interface AgentSubmissionResponse extends AgentRecord {
  metadata_gateway_url?: string;
  metadata_cid?: string;
  operator_checklist: string[];
  message: string;
}

export async function fetchAgents(): Promise<AgentsListResponse> {
  const response = await fetch(`${BACKEND_BASE_URL}/api/agents`, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
  });

  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    const message =
      (payload && (payload as any).detail) ||
      (payload && (payload as any).error) ||
      'Failed to fetch agents';
    throw new Error(message);
  }

  if (!payload || !Array.isArray((payload as AgentsListResponse).agents)) {
    return {
      total: 0,
      agents: [],
      sync_status: (payload as any)?.sync_status,
      synced_at: (payload as any)?.synced_at,
    };
  }

  return payload as AgentsListResponse;
}

export async function submitAgent(payload: AgentSubmissionPayload): Promise<AgentSubmissionResponse> {
  const response = await fetch(`${BACKEND_BASE_URL}/api/agents`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to submit agent' }));
    throw new Error(error.detail || error.error || 'Failed to submit agent');
  }

  return response.json();
}

// Data Agent ----------------------------------------------------------------

export type DataClassification = 'failed' | 'underused';
export type DataVisibility = 'private' | 'org' | 'public';
export type DataVerificationStatus = 'pending' | 'passed' | 'failed';
export type DataProofStatus = 'unanchored' | 'manifest_pinned' | 'anchored' | 'failed';

export interface SimilarDataset {
  id: string;
  title: string;
  data_classification: DataClassification;
  tags: string[];
  similarity_score: number;
}

export interface DatasetProofBundle {
  dataset_id: string;
  file_sha256: string;
  manifest_cid?: string;
  manifest_sha256?: string;
  manifest_gateway_url?: string;
  hcs_topic_id?: string;
  hcs_message_status?: string;
  anchor_payload?: Record<string, any>;
  anchored_at?: string;
  verification_status: DataVerificationStatus | string;
  verification_report?: Record<string, any>;
  proof_status: DataProofStatus | string;
}

export interface DataAssetRecord {
  id: string;
  title: string;
  description?: string;
  lab_name: string;
  uploader_name?: string;
  data_classification: DataClassification;
  tags: string[];
  intended_visibility: DataVisibility;
  filename: string;
  size_bytes: number;
  content_type?: string;
  sha256: string;
  created_at: string;
  verification_status: DataVerificationStatus | string;
  proof_status: DataProofStatus | string;
  manifest_cid?: string;
  reuse_count: number;
  last_reused_at?: string;
  failed_reason?: string;
  reuse_domains: string[];
}

export interface DataAssetDetailRecord extends DataAssetRecord {
  verification_report?: Record<string, any>;
  proof_bundle?: DatasetProofBundle;
  similar_datasets: SimilarDataset[];
}

export interface DataAssetListResponse {
  total: number;
  limit: number;
  offset: number;
  datasets: DataAssetRecord[];
}

export interface UploadDatasetPayload {
  title: string;
  description?: string;
  lab_name: string;
  data_classification: DataClassification;
  tags?: string[] | string;
  intended_visibility?: DataVisibility;
  uploader_name?: string;
  failed_reason?: string;
  reuse_domains?: string[] | string;
  file: File;
}

export interface UploadDatasetResponse extends DataAssetRecord {
  message: string;
}

export interface ListDatasetsParams {
  q?: string;
  tag?: string;
  classification?: DataClassification;
  verification_status?: DataVerificationStatus | string;
  proof_status?: DataProofStatus | string;
  lab_name?: string;
  limit?: number;
  offset?: number;
}

export async function uploadDataset(payload: UploadDatasetPayload): Promise<UploadDatasetResponse> {
  const formData = new FormData();
  formData.set('title', payload.title);
  formData.set('description', payload.description ?? '');
  formData.set('lab_name', payload.lab_name);
  formData.set('data_classification', payload.data_classification);
  formData.set('intended_visibility', payload.intended_visibility ?? 'private');
  if (payload.uploader_name) {
    formData.set('uploader_name', payload.uploader_name);
  }
  if (payload.failed_reason) {
    formData.set('failed_reason', payload.failed_reason);
  }

  if (Array.isArray(payload.tags)) {
    formData.set('tags', payload.tags.join(','));
  } else if (typeof payload.tags === 'string') {
    formData.set('tags', payload.tags);
  }
  if (Array.isArray(payload.reuse_domains)) {
    formData.set('reuse_domains', payload.reuse_domains.join(','));
  } else if (typeof payload.reuse_domains === 'string') {
    formData.set('reuse_domains', payload.reuse_domains);
  }

  formData.set('file', payload.file);

  const response = await fetch(`${BACKEND_BASE_URL}/api/data-agent/datasets`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to upload dataset' }));
    throw new Error(error.detail || error.error || 'Failed to upload dataset');
  }

  return response.json();
}

export async function listDatasets(params: ListDatasetsParams = {}): Promise<DataAssetListResponse> {
  const query = new URLSearchParams();
  if (params.q) query.set('q', params.q);
  if (params.tag) query.set('tag', params.tag);
  if (params.classification) query.set('classification', params.classification);
  if (params.verification_status) query.set('verification_status', params.verification_status);
  if (params.proof_status) query.set('proof_status', params.proof_status);
  if (params.lab_name) query.set('lab_name', params.lab_name);
  if (typeof params.limit === 'number') query.set('limit', String(params.limit));
  if (typeof params.offset === 'number') query.set('offset', String(params.offset));

  const suffix = query.toString() ? `?${query.toString()}` : '';
  const response = await fetch(`${BACKEND_BASE_URL}/api/data-agent/datasets${suffix}`, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to list datasets' }));
    throw new Error(error.detail || error.error || 'Failed to list datasets');
  }

  return response.json();
}

export async function getDataset(datasetId: string): Promise<DataAssetDetailRecord> {
  const response = await fetch(`${BACKEND_BASE_URL}/api/data-agent/datasets/${datasetId}`, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to fetch dataset' }));
    throw new Error(error.detail || error.error || 'Failed to fetch dataset');
  }

  return response.json();
}

export async function verifyDataset(datasetId: string): Promise<DataAssetDetailRecord> {
  const response = await fetch(`${BACKEND_BASE_URL}/api/data-agent/datasets/${datasetId}/verify`, {
    method: 'POST',
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to verify dataset' }));
    throw new Error(error.detail || error.error || 'Failed to verify dataset');
  }

  return response.json();
}

export async function anchorDataset(datasetId: string): Promise<DatasetProofBundle> {
  const response = await fetch(`${BACKEND_BASE_URL}/api/data-agent/datasets/${datasetId}/anchor`, {
    method: 'POST',
  });

  if (!response.ok) {
    const raw = await response.text().catch(() => '');
    let detail = '';

    if (raw) {
      try {
        const parsed = JSON.parse(raw) as { detail?: string; error?: string };
        detail = parsed.detail || parsed.error || '';
      } catch {
        detail = raw.replace(/\s+/g, ' ').slice(0, 240).trim();
      }
    }

    if (!detail) {
      detail = `Failed to anchor dataset (HTTP ${response.status})`;
    }

    throw new Error(detail);
  }

  return response.json();
}

export async function getDatasetProof(datasetId: string): Promise<DatasetProofBundle> {
  const response = await fetch(`${BACKEND_BASE_URL}/api/data-agent/datasets/${datasetId}/proof`, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to fetch proof bundle' }));
    throw new Error(error.detail || error.error || 'Failed to fetch proof bundle');
  }

  return response.json();
}

export async function getDatasetCitation(datasetId: string): Promise<{ citation: Record<string, any> }> {
  const response = await fetch(`${BACKEND_BASE_URL}/api/data-agent/datasets/${datasetId}/citation`, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to fetch citation' }));
    throw new Error(error.detail || error.error || 'Failed to fetch citation');
  }

  return response.json();
}

export async function recordDatasetReuse(
  datasetId: string
): Promise<{ dataset_id: string; reuse_count: number; last_reused_at: string; message: string }> {
  const response = await fetch(`${BACKEND_BASE_URL}/api/data-agent/datasets/${datasetId}/reuse-events`, {
    method: 'POST',
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to record reuse event' }));
    throw new Error(error.detail || error.error || 'Failed to record reuse event');
  }

  return response.json();
}

export async function downloadDataset(datasetId: string): Promise<Blob> {
  const response = await fetch(`${BACKEND_BASE_URL}/api/data-agent/datasets/${datasetId}/download`, {
    method: 'GET',
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to download dataset' }));
    throw new Error(error.detail || error.error || 'Failed to download dataset');
  }

  return response.blob();
}
