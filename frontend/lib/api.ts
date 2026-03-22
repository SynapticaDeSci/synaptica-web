/**
 * API client for ProvidAI backend
 */

const BACKEND_BASE_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

export interface DatasetHolUseErrorDetail {
  message?: string;
  search_queries?: string[];
  discovered_candidates?: Array<Record<string, any>>;
  rejected_candidates?: Array<Record<string, any>>;
  attempted_errors?: string[];
}

export class ApiRequestError extends Error {
  status?: number;
  detail?: any;

  constructor(message: string, options?: { status?: number; detail?: any }) {
    super(message);
    this.name = 'ApiRequestError';
    this.status = options?.status;
    this.detail = options?.detail;
  }
}

function extractApiErrorMessage(payload: any, fallback: string): string {
  if (!payload) return fallback;

  const detail = payload.detail;
  if (typeof detail === 'string' && detail.trim()) {
    return detail;
  }

  if (detail && typeof detail === 'object') {
    if (typeof detail.message === 'string' && detail.message.trim()) {
      return detail.message;
    }
    if (typeof (detail as any).detail === 'string' && (detail as any).detail.trim()) {
      return (detail as any).detail;
    }
  }

  if (Array.isArray(detail) && detail.length > 0) {
    const messages = detail
      .map((entry) => {
        if (!entry || typeof entry !== 'object') return null;
        const loc = Array.isArray((entry as any).loc)
          ? (entry as any).loc.filter(Boolean).join('.')
          : '';
        const msg = typeof (entry as any).msg === 'string' ? (entry as any).msg : '';
        if (!msg) return null;
        return loc ? `${loc}: ${msg}` : msg;
      })
      .filter(Boolean);

    if (messages.length > 0) {
      return messages.join('; ');
    }
  }

  if (typeof payload.error === 'string' && payload.error.trim()) {
    return payload.error;
  }

  return fallback;
}

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

export interface TaskVerificationData {
  todo_id: string;
  payment_id: string;
  quality_score: number;
  dimension_scores: Record<string, number>;
  feedback: string;
  task_result: any;
  agent_name: string;
  ethics_passed: boolean;
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
  verification_data?: TaskVerificationData;
}

export type ResearchRunStatus =
  | 'pending'
  | 'running'
  | 'waiting_for_review'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type ResearchRunNodeStatus =
  | 'pending'
  | 'running'
  | 'waiting_for_review'
  | 'completed'
  | 'failed'
  | 'blocked'
  | 'cancelled';

export interface CreateResearchRunRequest {
  description: string;
  credit_budget?: number;
  budget_limit?: number;
  verification_mode?: string;
  max_node_attempts?: number;
}

export interface ResearchSourceCard {
  citation_id?: string | null;
  title: string;
  url: string;
  publisher?: string | null;
  published_at?: string | null;
  source_type?: string | null;
  snippet?: string | null;
  display_snippet?: string | null;
  relevance_score?: number | null;
  quality_flags?: string[] | null;
  filtered_reason?: string | null;
}

export interface ResearchClaim {
  claim_id?: string | null;
  claim: string;
  supporting_citation_ids?: string[] | null;
  supporting_citations?: string[];
  confidence?: string;
}

export interface ResearchCriticFinding {
  issue: string;
  severity?: string;
  recommendation?: string;
  round_number?: number;
}

export interface ResearchQualitySummary {
  citation_coverage?: number | null;
  uncovered_claims?: string[] | number | null;
  source_diversity?: string | number | Record<string, number | string> | null;
  verification_notes?: string[] | string | null;
  strict_live_analysis_checks_passed?: boolean | null;
}

export interface ResearchRunAttemptResponse {
  attempt_id: string;
  attempt_number: number;
  status: ResearchRunNodeStatus;
  task_id?: string | null;
  payment_id?: string | null;
  agent_id?: string | null;
  verification_score?: number | null;
  created_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  result?: any;
  error?: string | null;
}

export interface ResearchRunNodeResponse {
  node_id: string;
  title: string;
  description: string;
  capability_requirements: string;
  assigned_agent_id: string;
  candidate_agent_ids: string[];
  execution_order: number;
  status: ResearchRunNodeStatus;
  task_id?: string | null;
  payment_id?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  result?: any;
  error?: string | null;
  attempts: ResearchRunAttemptResponse[];
}

export interface ResearchRunEdgeResponse {
  from_node_id: string;
  to_node_id: string;
}

export interface ResearchRunPolicy {
  strict_mode: boolean;
  risk_level: string;
  quorum_policy: string;
  max_node_attempts: number;
  reroute_on_failure: boolean;
  max_swarm_rounds: number;
  escalate_on_dissent: boolean;
}

export interface ResearchRunTraceSummary {
  verification_decision_count: number;
  swarm_handoff_count: number;
  policy_evaluation_count: number;
  unresolved_dissent_count: number;
}

export interface ResearchRunResponse {
  id: string;
  title: string;
  description: string;
  status: ResearchRunStatus;
  workflow_template: string;
  workflow: string;
  budget_limit?: number | null;
  credit_budget?: number | null;
  verification_mode: string;
  research_mode: string;
  classified_mode: string;
  depth_mode: string;
  freshness_required: boolean;
  policy: ResearchRunPolicy;
  trace_summary: ResearchRunTraceSummary;
  source_requirements: {
    total_sources?: number;
    min_academic_or_primary?: number;
    min_fresh_sources?: number;
    freshness_window_days?: number | null;
  };
  rounds_planned: {
    evidence_rounds?: number;
    critique_rounds?: number;
  };
  rounds_completed: {
    evidence_rounds?: number;
    critique_rounds?: number;
  };
  created_at?: string | null;
  updated_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  result?: any;
  error?: string | null;
  quality_tier?: string | null;
  quality_warnings?: string[];
  nodes: ResearchRunNodeResponse[];
  edges: ResearchRunEdgeResponse[];
}

export interface ResearchRunEvidenceResponse {
  research_run_id: string;
  status: ResearchRunStatus;
  claim_targets: Array<Record<string, any>>;
  rewritten_research_brief?: string | null;
  sources: ResearchSourceCard[];
  filtered_sources: ResearchSourceCard[];
  citations: ResearchSourceCard[];
  coverage_summary: Record<string, any>;
  source_summary: Record<string, any>;
  freshness_summary: Record<string, any>;
  search_lanes_used: string[];
  quality_tier?: string | null;
  quality_warnings?: string[];
}

export interface ResearchRunReportResponse {
  research_run_id: string;
  status: ResearchRunStatus;
  answer_markdown?: string | null;
  answer?: string | null;
  claims: ResearchClaim[];
  citations: ResearchSourceCard[];
  limitations: string[];
  critic_findings: ResearchCriticFinding[];
  quality_summary: ResearchQualitySummary;
}

export interface ResearchRunArtifactResponse extends ResearchSourceCard {
  artifact_key: string;
  artifact_type: string;
  origin_node_id?: string | null;
  last_seen_node_id?: string | null;
  order_index?: number | null;
  normalized_url?: string | null;
  curation_status: string;
  freshness_metadata: Record<string, any>;
}

export interface ResearchRunPersistedClaimResponse {
  claim_id: string;
  claim_order: number;
  claim: string;
  confidence?: string | null;
  confidence_score?: number | null;
  contradiction_status?: string | null;
  contradiction_reasons: string[];
  supporting_artifact_keys: string[];
  supporting_citation_ids: string[];
}

export interface ResearchRunClaimLinkResponse {
  claim_id: string;
  artifact_key: string;
  citation_id?: string | null;
  relation_type: string;
  link_order?: number | null;
}

export interface ResearchRunEvidenceGraphResponse {
  schema_version: string;
  research_run_id: string;
  title: string;
  description: string;
  status: ResearchRunStatus;
  workflow: string;
  artifacts: ResearchRunArtifactResponse[];
  claims: ResearchRunPersistedClaimResponse[];
  links: ResearchRunClaimLinkResponse[];
  summary: {
    artifact_count: number;
    cited_artifact_count: number;
    filtered_artifact_count: number;
    claim_count: number;
    link_count: number;
    high_confidence_claim_count: number;
    mixed_evidence_claim_count: number;
    insufficient_evidence_claim_count: number;
  };
}

export interface ResearchRunReportPackResponse {
  schema_version: string;
  research_run_id: string;
  title: string;
  description: string;
  status: ResearchRunStatus;
  workflow: string;
  generated_at?: string | null;
  rewritten_research_brief?: string | null;
  answer_markdown?: string | null;
  answer?: string | null;
  claims: ResearchRunPersistedClaimResponse[];
  citations: ResearchRunArtifactResponse[];
  supporting_evidence: ResearchRunArtifactResponse[];
  claim_lineage: ResearchRunClaimLinkResponse[];
  quality_summary: Record<string, any>;
  critic_findings: Array<Record<string, any>>;
  limitations: any[];
}

export interface ResearchRunVerificationDecisionResponse {
  id: number;
  research_run_id: string;
  node_id: string;
  attempt_id: string;
  task_id?: string | null;
  payment_id?: string | null;
  agent_id?: string | null;
  decision: string;
  approved: boolean;
  decision_source: string;
  overall_score?: number | null;
  dimension_scores: Record<string, any>;
  rationale?: string | null;
  dissent_count?: number | null;
  quorum_policy?: string | null;
  policy_snapshot: Record<string, any>;
  created_at?: string | null;
  meta: Record<string, any>;
}

export interface ResearchRunSwarmHandoffResponse {
  id: number;
  research_run_id: string;
  node_id: string;
  attempt_id: string;
  handoff_index: number;
  from_agent_id?: string | null;
  to_agent_id?: string | null;
  handoff_type: string;
  round_number: number;
  status: string;
  budget_remaining?: number | null;
  verification_mode?: string | null;
  idempotency_key?: string | null;
  blackboard_delta: Record<string, any>;
  decision_log: Record<string, any>;
  created_at?: string | null;
  meta: Record<string, any>;
}

export interface ResearchRunPolicyEvaluationResponse {
  id: number;
  research_run_id: string;
  node_id: string;
  attempt_id: string;
  task_id?: string | null;
  payment_id?: string | null;
  evaluation_type: string;
  status: string;
  outcome?: string | null;
  summary?: string | null;
  details: Record<string, any>;
  created_at?: string | null;
  meta: Record<string, any>;
}

export interface PaymentProfileVerificationResponse {
  success: boolean;
  agent_id: string;
  hedera_account_id: string;
  status: string;
  verification_method?: string | null;
  verified_at?: string | null;
  last_error?: string | null;
  meta?: Record<string, any>;
}

export interface PaymentDetailResponse {
  id: string;
  task_id: string;
  from_agent_id: string;
  to_agent_id: string;
  amount: number;
  currency: string;
  status: string;
  transaction_id?: string | null;
  authorization_id?: string | null;
  created_at?: string | null;
  completed_at?: string | null;
  a2a_thread_id?: string | null;
  payment_mode?: string | null;
  worker_account_id?: string | null;
  verification_notes?: string | null;
  rejection_reason?: string | null;
  payment_profile?: PaymentProfileVerificationResponse | null;
  notification_summary: Record<string, number>;
}

export interface PaymentEventsResponse {
  payment: PaymentDetailResponse;
  state_transitions: Array<Record<string, any>>;
  notifications: Array<Record<string, any>>;
  a2a_events: Array<Record<string, any>>;
  reconciliations: Array<Record<string, any>>;
}

// HOL Registry ----------------------------------------------------------------

export interface HolAgentRecord {
  uaid: string;
  name: string;
  description: string;
  capabilities: string[];
  categories: string[];
  transports: string[];
  pricing: {
    rate?: number;
    currency?: string;
    rate_type?: string;
    [key: string]: any;
  };
  registry?: string | null;
  available?: boolean | null;
  availability_status?: string | null;
  source_url?: string | null;
  adapter?: string | null;
  protocol?: string | null;
}

export type HolRegisterMode = 'quote' | 'register';

export interface HolRegisterAgentRequest {
  agent_id: string;
  mode?: HolRegisterMode;
  endpoint_url_override?: string;
  metadata_uri_override?: string;
}

export interface HolRegisterAgentResponse {
  success: boolean;
  agent_id: string;
  mode: HolRegisterMode;
  hol_registration_status: string;
  hol_uaid?: string | null;
  hol_last_error?: string | null;
  estimated_credits?: number | null;
  broker_response?: Record<string, any>;
}

export interface HolRegisterAgentStatusResponse {
  agent_id: string;
  hol_registration_status: string;
  hol_uaid?: string | null;
  hol_last_error?: string | null;
  updated_at?: string | null;
}

export interface HolChatMessageRecord {
  role: string;
  content: string;
  timestamp?: string | null;
  raw?: Record<string, any>;
}

export interface HolChatSessionResponse {
  success: boolean;
  session_id: string;
  uaid?: string | null;
  broker_response?: Record<string, any>;
  history: HolChatMessageRecord[];
}

export async function searchHolAgents(
  query: string,
  options?: { onlyAvailable?: boolean }
): Promise<{ agents: HolAgentRecord[]; query: string }> {
  const q = query.trim() || 'agent';
  const url = new URL(`${BACKEND_BASE_URL}/api/hol/agents/search`);
  url.searchParams.set('q', q);
  if (options?.onlyAvailable) {
    url.searchParams.set('only_available', 'true');
  }

  const response = await fetch(url.toString(), {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const message = extractApiErrorMessage(payload, 'Failed to search HOL agents');
    throw new Error(message);
  }

  return response.json();
}

export async function registerAgentOnHol(
  payload: HolRegisterAgentRequest
): Promise<HolRegisterAgentResponse> {
  const response = await fetch(`${BACKEND_BASE_URL}/api/hol/register-agent`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      agent_id: payload.agent_id,
      mode: payload.mode ?? 'register',
      endpoint_url_override: payload.endpoint_url_override,
      metadata_uri_override: payload.metadata_uri_override,
    }),
  });

  const result = await response.json().catch(() => null);
  if (!response.ok) {
    const message = extractApiErrorMessage(result, 'Failed to register agent on HOL');
    throw new Error(message);
  }

  return result as HolRegisterAgentResponse;
}

export async function getHolRegistrationStatus(
  agentId: string
): Promise<HolRegisterAgentStatusResponse> {
  const response = await fetch(`${BACKEND_BASE_URL}/api/hol/register-agent/${agentId}/status`, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
  });

  const result = await response.json().catch(() => null);
  if (!response.ok) {
    const message = extractApiErrorMessage(result, 'Failed to fetch HOL registration status');
    throw new Error(message);
  }

  return result as HolRegisterAgentStatusResponse;
}

export async function createHolChatSession(payload: {
  uaid: string;
  transport?: string;
  as_uaid?: string;
}): Promise<HolChatSessionResponse> {
  const response = await fetch(`${BACKEND_BASE_URL}/api/hol/chat/session`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  const result = await response.json().catch(() => null);
  if (!response.ok) {
    const message = extractApiErrorMessage(result, 'Failed to create HOL chat session');
    throw new ApiRequestError(message, {
      status: response.status,
      detail: result?.detail ?? result,
    });
  }

  return result as HolChatSessionResponse;
}

export async function sendHolChatMessage(payload: {
  session_id: string;
  message: string;
  as_uaid?: string;
}): Promise<HolChatSessionResponse> {
  const response = await fetch(`${BACKEND_BASE_URL}/api/hol/chat/message`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  const result = await response.json().catch(() => null);
  if (!response.ok) {
    const message = extractApiErrorMessage(result, 'Failed to send HOL chat message');
    throw new ApiRequestError(message, {
      status: response.status,
      detail: result?.detail ?? result,
    });
  }

  return result as HolChatSessionResponse;
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
 * Create and immediately start a research run.
 */
export async function createResearchRun(
  request: CreateResearchRunRequest
): Promise<ResearchRunResponse> {
  const response = await fetch(`${BACKEND_BASE_URL}/api/research-runs`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: 'Failed to create research run' }));
    const detail = error.detail;
    // Structured error from backend (e.g. {error: "insufficient_credits", ...})
    if (typeof detail === 'object' && detail?.error) {
      throw new Error(detail.error);
    }
    throw new Error(typeof detail === 'string' ? detail : error.error || 'Failed to create research run');
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
 * Get research run status and node graph.
 */
export async function getResearchRun(researchRunId: string): Promise<ResearchRunResponse> {
  const response = await fetch(`${BACKEND_BASE_URL}/api/research-runs/${researchRunId}`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
    },
    cache: 'no-store',
  });

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: 'Research run not found' }));
    throw new Error(error.detail || error.error || 'Research run not found');
  }

  return response.json();
}

export async function pauseResearchRun(researchRunId: string): Promise<ResearchRunResponse> {
  const response = await fetch(`${BACKEND_BASE_URL}/api/research-runs/${researchRunId}/pause`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: 'Failed to pause research run' }));
    throw new Error(error.detail || error.error || 'Failed to pause research run');
  }

  return response.json();
}

export async function resumeResearchRun(researchRunId: string): Promise<ResearchRunResponse> {
  const response = await fetch(`${BACKEND_BASE_URL}/api/research-runs/${researchRunId}/resume`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: 'Failed to resume research run' }));
    throw new Error(error.detail || error.error || 'Failed to resume research run');
  }

  return response.json();
}

export async function cancelResearchRun(researchRunId: string): Promise<ResearchRunResponse> {
  const response = await fetch(`${BACKEND_BASE_URL}/api/research-runs/${researchRunId}/cancel`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: 'Failed to cancel research run' }));
    throw new Error(error.detail || error.error || 'Failed to cancel research run');
  }

  return response.json();
}

export async function getResearchRunEvidence(
  researchRunId: string
): Promise<ResearchRunEvidenceResponse> {
  const response = await fetch(`${BACKEND_BASE_URL}/api/research-runs/${researchRunId}/evidence`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
    },
    cache: 'no-store',
  });

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: 'Research run evidence not found' }));
    throw new Error(error.detail || error.error || 'Research run evidence not found');
  }

  return response.json();
}

export async function getResearchRunReport(
  researchRunId: string
): Promise<ResearchRunReportResponse> {
  const response = await fetch(`${BACKEND_BASE_URL}/api/research-runs/${researchRunId}/report`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
    },
    cache: 'no-store',
  });

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: 'Research run report not found' }));
    throw new Error(error.detail || error.error || 'Research run report not found');
  }

  return response.json();
}

export async function getResearchRunEvidenceGraph(
  researchRunId: string
): Promise<ResearchRunEvidenceGraphResponse> {
  const response = await fetch(
    `${BACKEND_BASE_URL}/api/research-runs/${researchRunId}/evidence-graph`,
    {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
      cache: 'no-store',
    }
  );

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: 'Research run evidence graph not found' }));
    throw new Error(error.detail || error.error || 'Research run evidence graph not found');
  }

  return response.json();
}

export async function getResearchRunReportPack(
  researchRunId: string
): Promise<ResearchRunReportPackResponse> {
  const response = await fetch(
    `${BACKEND_BASE_URL}/api/research-runs/${researchRunId}/report-pack`,
    {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
      cache: 'no-store',
    }
  );

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: 'Research run report pack not found' }));
    throw new Error(error.detail || error.error || 'Research run report pack not found');
  }

  return response.json();
}

export async function getResearchRunVerificationDecisions(
  researchRunId: string
): Promise<ResearchRunVerificationDecisionResponse[]> {
  const response = await fetch(
    `${BACKEND_BASE_URL}/api/research-runs/${researchRunId}/verification-decisions`,
    {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
      cache: 'no-store',
    }
  );

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: 'Research run verification decisions not found' }));
    throw new Error(
      error.detail || error.error || 'Research run verification decisions not found'
    );
  }

  return response.json();
}

export async function getResearchRunSwarmHandoffs(
  researchRunId: string
): Promise<ResearchRunSwarmHandoffResponse[]> {
  const response = await fetch(
    `${BACKEND_BASE_URL}/api/research-runs/${researchRunId}/swarm-handoffs`,
    {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
      cache: 'no-store',
    }
  );

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: 'Research run swarm handoffs not found' }));
    throw new Error(error.detail || error.error || 'Research run swarm handoffs not found');
  }

  return response.json();
}

export async function getResearchRunPolicyEvaluations(
  researchRunId: string
): Promise<ResearchRunPolicyEvaluationResponse[]> {
  const response = await fetch(
    `${BACKEND_BASE_URL}/api/research-runs/${researchRunId}/policy-evaluations`,
    {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
      cache: 'no-store',
    }
  );

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: 'Research run policy evaluations not found' }));
    throw new Error(error.detail || error.error || 'Research run policy evaluations not found');
  }

  return response.json();
}

export async function getPayment(paymentId: string): Promise<PaymentDetailResponse> {
  const response = await fetch(`${BACKEND_BASE_URL}/api/payments/${paymentId}`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
    },
    cache: 'no-store',
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Payment not found' }));
    throw new Error(error.detail || error.error || 'Payment not found');
  }

  return response.json();
}

export async function getPaymentEvents(paymentId: string): Promise<PaymentEventsResponse> {
  const response = await fetch(`${BACKEND_BASE_URL}/api/payments/${paymentId}/events`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
    },
    cache: 'no-store',
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Payment events not found' }));
    throw new Error(error.detail || error.error || 'Payment events not found');
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
 * Approve a verification review for a task.
 */
export async function approveVerification(
  taskId: string
): Promise<{ success: boolean; message?: string; error?: string }> {
  const response = await fetch(`${BACKEND_BASE_URL}/api/tasks/${taskId}/approve_verification`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: 'Failed to approve verification' }));
    throw new Error(error.error || 'Failed to approve verification');
  }

  return response.json();
}

/**
 * Reject a verification review for a task.
 */
export async function rejectVerification(
  taskId: string,
  reason?: string
): Promise<{ success: boolean; message?: string; error?: string }> {
  const query = reason ? `?reason=${encodeURIComponent(reason)}` : '';
  const response = await fetch(`${BACKEND_BASE_URL}/api/tasks/${taskId}/reject_verification${query}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: 'Failed to reject verification' }));
    throw new Error(error.error || 'Failed to reject verification');
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
  support_tier?: 'supported' | 'experimental' | 'legacy';
  hol_uaid?: string;
  hol_registration_status?: string;
  hol_last_error?: string;
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
    const message = extractApiErrorMessage(payload, 'Failed to fetch agents');
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
    const errorPayload = await response.json().catch(() => null);
    throw new Error(extractApiErrorMessage(errorPayload, 'Failed to submit agent'));
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
  hol_sessions: Array<Record<string, any>>;
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

export interface DatasetHolUseRequest {
  uaid?: string;
  search_query?: string;
  required_capabilities?: string[];
  instructions?: string;
  transport?: string;
  as_uaid?: string;
  limit?: number;
}

export interface DatasetHolUseResponse {
  success: boolean;
  selected_agent: Record<string, any>;
  session_id: string;
  broker_response: Record<string, any>;
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
    const errorPayload = await response.json().catch(() => null);
    throw new Error(extractApiErrorMessage(errorPayload, 'Failed to upload dataset'));
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
    const errorPayload = await response.json().catch(() => null);
    throw new Error(extractApiErrorMessage(errorPayload, 'Failed to list datasets'));
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

export async function invokeDatasetHolAgent(
  datasetId: string,
  payload: DatasetHolUseRequest = {}
): Promise<DatasetHolUseResponse> {
  const response = await fetch(`${BACKEND_BASE_URL}/api/data-agent/datasets/${datasetId}/hol-use`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to use HOL data agent' }));
    const message = extractApiErrorMessage(error, 'Failed to use HOL data agent');
    throw new ApiRequestError(message, {
      status: response.status,
      detail: error?.detail ?? error,
    });
  }

  return response.json();
}
