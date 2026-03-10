# Research Pipeline PRD (Implementation-Focused)

Date: March 8, 2026
Owner: Synaptica Core Team
Status: Draft

## 1. Objective

Build a production research pipeline that runs end-to-end from user query to verified report using multi-agent orchestration, explicit payment settlement, and reproducible artifacts.

## 2. Scope

In scope:
- Research-run-based execution (`query -> DAG -> verified outputs`).
- Dynamic agent discovery and assignment from registry/marketplace.
- Swarm collaboration (parallel branches, debate, merge, quorum).
- x402 + TaskEscrow payment lifecycle with A2A payment events.
- Evidence graph, claim lineage, verification records, and final report pack.
- Migration from legacy orchestration to Strands SDK + Swarm.

Out of scope (v1):
- Wet lab/robotic execution.
- Regulated medical decision support.
- Fully unsupervised high-risk policy recommendations.

## 3. Core Architecture

### 3.1 Research run primitive

Each research run stores:
- Intent: query, constraints, budget, verification mode.
- Execution graph: nodes, edges, retries, fallback policy.
- Agent assignments: selected providers per node attempt.
- Evidence graph: artifacts, extraction lineage, source links.
- Verification decisions: scores, pass/fail rationale, dissent.
- Settlement ledger: payment proposals, authorization, release/refund.
- Deliverables: JSON package + human report + reproducibility bundle.

### 3.2 DAG runtime

Each node defines:
- Objective.
- Input/output schema.
- Capability requirements.
- Budget envelope.
- Gate thresholds.
- Retry policy.

Execution rule:
- Node can run only when dependencies are complete and payment state allows execution.
- DAG scheduling, dependency resolution, and parallel branches should use Strands Workflow/Graph primitives.

### 3.3 Agent roles

- Orchestrator: planning, scheduling, synthesis.
- Negotiator: discovery, selection, pricing/proposal.
- Executor: endpoint invocation + fallback.
- Verifier: quality scoring, arbitration, settlement decision.
- Optional specialists: scout, method critic, synthesis, replication, report composer.

### 3.4 Swarm collaboration protocol

Runtime split:
- Use Strands Workflow/Graph for deterministic DAG structure and parallel execution.
- Use Strands Swarm for adaptive agent-to-agent handoffs inside collaboration-heavy nodes.

Required behavior:
- Shared blackboard with typed artifacts (`evidence_cards`, `claim_drafts`, `critic_notes`, `decision_logs`).
- Parallel scout branches for discovery-heavy nodes (scheduled by Workflow/Graph).
- Critic-led debate loop for contested claims.
- Merge node tracks support, opposition, unresolved uncertainty.
- Strict mode supports configurable quorum (`2/3`, `3/5`, unanimous).
- Loop bounds: max rounds, timeout, budget cap.
- Escalation to human review on unresolved dissent or repeated verifier failure.
- Enable repetitive handoff detection/timeouts to prevent ping-pong loops between swarm agents.

Required swarm handoff context:
- `research_run_id`
- `node_id`
- `attempt_id`
- `payment_id`
- `budget_remaining`
- `verification_mode`
- `idempotency_key`

Session persistence requirement:
- Use Strands session manager for research-run resumability, including orchestrator state, node transition history, and shared multi-agent context.

### 3.5 Payment architecture (x402 + TaskEscrow + A2A)

Payment lifecycle:
- `pending -> authorized -> completed`
- `pending -> authorized -> refunded`
- `pending -> failed`
- `authorized -> failed`

Flow per node attempt:
1. Negotiator creates payment proposal + `payment/proposal` A2A message.
2. Orchestrator authorizes escrow via x402 (`createEscrow`).
3. Executor runs only after `authorized`.
4. Verifier calls `approveRelease` or `approveRefund`.
5. System emits terminal A2A event (`payment/released` or `payment/refunded`) to payer and payee.
6. Reconciler validates platform state against on-chain escrow status.

How receiver knows payment status:
- A2A terminal event in payment thread.
- Payment API by `payment_id`.
- On-chain transaction receipt (source of truth).

Protocol profile clarification:
- Current implementation profile is escrow-first (`createEscrow`, `approveRelease`, `approveRefund`) plus internal A2A payment events.
- This is compatible with the project payment model but is not the full HTTP x402 challenge/response flow by default.
- If external x402 HTTP compliance is required, endpoints must implement `402 Payment Required` with `PAYMENT-REQUIRED` challenge and accept `PAYMENT-SIGNATURE`/`X-PAYMENT`, then return `PAYMENT-RESPONSE` on success.
- For A2A interoperability, support mapping to x402 A2A metadata states (e.g., `payment-required`, `payment-submitted`, `payment-verified`, `payment-completed`, `payment-failed`).

### 3.6 Wallet and key management

Production policy:
- Marketplace agents are non-custodial (store payout address + ownership proof only).
- No private keys in agent metadata, payment records, or logs.
- Platform-managed signing uses HSM/KMS or delegated signer service.
- Environment variables in production store secret references/endpoints, not raw long-lived keys.

Development policy:
- `.env` test keys allowed only for local development.
- `X402_OFFLINE` allowed only for local/simulation.

## 4. API Surface

Research run APIs:
- `POST /api/research-runs`
- `GET /api/research-runs/{id}`
- `POST /api/research-runs/{id}/pause|resume|cancel`
- `GET /api/research-runs/{id}/evidence`
- `GET /api/research-runs/{id}/report`

Payment APIs:
- `GET /api/payments/{payment_id}`
- `GET /api/payments/{payment_id}/events`
- `POST /api/payments/reconcile`

Payment identity APIs:
- `POST /api/agents/{agent_id}/payment-profile/verify`

Internal runtime-only payment actions:
- proposal / authorize / release / refund remain tool-driven inside the deterministic orchestrator-verifier flow and are not mounted as public REST routes in Phase 1.

## 5. Data Model

Core entities:
- `research_runs`
- `research_run_nodes`
- `research_run_edges`
- `execution_attempts`
- `evidence_artifacts`
- `claims`
- `claim_links`
- `verification_decisions`
- `payment_state_transitions`
- `swarm_handoffs`
- `policy_evaluations`
- `agent_payment_profiles`
- `payment_notifications`
- `payment_reconciliations`

Compatibility:
- Keep existing `tasks` and `payments` during migration.
- Migrate traffic to research-run-backed execution.

## 6. Functional Requirements

Planning and execution:
- Create research run from natural language query.
- Generate typed DAG with explicit dependencies.
- Discover/select agents by capability, quality, cost, latency.
- Execute node inputs/outputs with deterministic schemas.
- Persist all artifacts and execution attempts.

Verification and arbitration:
- Multi-dimensional quality score per node.
- Configurable pass thresholds and retry/reroute policy.
- Strict mode quorum for high-risk claims.
- Verifier controls terminal settlement decision.

Swarm collaboration:
- Shared memory artifacts across participating agents.
- Contested claims must go through debate + merge.
- Persist agreement/disagreement traces per final claim.
- Deterministic loop stop conditions and escalation events.

Payments and settlement:
- Payment actions available as first-class tools.
- Idempotent payment mutations (`research_run_id + node_id + attempt_id + action`).
- Block execution unless payment is `authorized` (except explicit simulation mode).
- Persist transition metadata and transaction receipts.
- Emit terminal payment events to both payer and payee.
- Reconcile platform state with chain state automatically.
- When exposing external paid HTTP endpoints, implement x402 transport headers/status codes end-to-end.

Security and custody:
- Validate payment profile before paid execution.
- Reject private-key material in API payloads.
- Use managed signing path in production.

Migration:
- Strands SDK becomes primary runtime, with Workflow/Graph for DAG execution and Swarm for adaptive handoffs.
- Legacy flow behind compatibility flag only.
- Keep tool contracts backward-compatible during migration.

## 7. Non-Functional Requirements

- Deterministic JSON contracts for node I/O.
- Full provenance/audit trail for outputs and payments.
- Idempotent APIs and exactly-once settlement semantics.
- Replayable policy decisions from persisted events.
- P95 research-run status transition latency < 3s.
- P95 merge-node decision latency < 5s.
- P95 chain reconciliation lag < 60s.
- Secret material never logged or returned by APIs.
- Key rotation support with no research-run downtime.
- No duplicate terminal payout for same idempotency key.

## 8. Implementation Plan

Phase 0 (2 weeks): foundation
- Remove simulation-only paths from primary runtime.
- Standardize node/executor/verifier schemas.
- Add handoff context schema and telemetry envelope.
- Add idempotent payment wrappers.
- Introduce signer abstraction (`dev_env_signer`, `managed_signer`).
- Add private-key payload/log guardrails.

Phase 1 (4 weeks): research-run MVP
- Implement research-run entities + DAG planner.
- Move orchestrator loop to research-run node execution.
- Add verification gates + settlement integration.
- Implement dual-recipient terminal A2A payment notifications.
- Add payment-profile verification + reconciliation worker baseline.
- Ship minimal research-run graph UI.

Phase 2 (4 weeks): evidence + report
- Build evidence ingestion and claim linking.
- Add contradiction/confidence scoring.
- Generate report pack from verified claims.
- Migrate executor/verifier interactions to Strands-native model.

Phase 3 (4 weeks): adaptive orchestration
- Add routing policy from historical outcomes.
- Add alternate-agent reruns and strict quorum tuning.
- Add risk-aware settlement policy adaptations.
- Disable legacy non-Strands path by default after parity checks.

Phase 4 (ongoing): domain templates
- Publish reusable research-run templates for research domains.

## 9. Success Metrics

- End-to-end verified research-run completion rate.
- Median time to verified report.
- Claims with full source lineage.
- First-pass verification rate.
- Refund rate.
- Collaboration gain vs single-agent baseline.
- Median rounds to contested-claim convergence.
- Unresolved dissent rate.
- Payment notification delivery success rate.
- Chain/platform reconciliation mismatch rate.

## 10. Acceptance Criteria (v1)

- User can run query -> verified report without manual backend intervention.
- >=90% of final claims include source links + extraction lineage.
- Every paid microtask has persisted verification and settlement records.
- Failed verification triggers configured retry/refund behavior.
- Production orchestration runs on Strands runtime with legacy disabled by default.
- Strict-mode research runs persist quorum decision traces.
- Contested-claim test scenario triggers deterministic debate resolution or escalation.
- Payer and payee both receive terminal payment events.
- No private-key material appears in DB snapshots, logs, or API payload captures.
- Reconciler resolves or flags all chain/platform mismatches within SLA.

## 11. Ideas Backlog

- Counterfactual mode: auto-generate disproof tasks for major claims.
- Debate pods: multiple synthesis agents + critic before acceptance.
- Confidence market overlay for claim calibration.
- Living report updates on new evidence deltas.
- Reproducibility scorecard from rerun outcomes.

## 12. Open Decisions

- Hard-fail vs soft-fail verification dimensions per domain.
- Quorum policy defaults by research-run risk class.
- Minimum evidence threshold by claim type.
- Rules for allowing `mock` settlement outside local development.
- Whether payee acknowledgement is required before closing payment thread.
