# Phase 1 Handoff

## Context

This branch completes the Phase 1 research-run implementation for the Synaptica DeSci runtime.

Phase 1 moved the product from the narrow Phase 0 task-backed literature workflow into a graph-backed research-run system with:

- bounded deep-research execution
- freshness-aware live-analysis behavior
- citation and source-quality controls
- queryable payment integrity surfaces
- cooperative run controls in the frontend and backend

The existing `POST /execute` path remains supported for the deterministic Phase 0 workflow, but the primary Phase 1 investment is now the research-run path under `/api/research-runs`.

Worktree used for this implementation:

- Path: `/Users/tiencheng/Projects/Personal/synaptica-web`
- Branch: `feat/research-agents-phase-1`

## What Was Done

### 1. Added the research-run backbone and graph persistence

Phase 1 introduced persisted research-run execution in:

- `shared/research_runs/planner.py`
- `shared/research_runs/service.py`
- `api/routes/research_runs.py`
- `shared/database/models.py`

The system now stores:

- `research_runs`
- `research_run_nodes`
- `research_run_edges`
- `execution_attempts`

The runtime persists node state, attempt state, linked task/payment IDs, and terminal outputs instead of relying on transient in-memory orchestration only.

### 2. Replaced the fixed literature template with bounded deep research

The workflow is now a bounded six-node backbone:

`plan_query -> gather_evidence -> curate_sources -> draft_synthesis -> critique_and_fact_check -> revise_final_answer`

Research runs support:

- `research_mode`: `auto | literature | live_analysis | hybrid`
- `depth_mode`: `standard | deep`

The planner now classifies live/current-event queries, adds rewritten research briefs and claim targets, and enforces source/freshness requirements through the run.

### 3. Improved research quality, citation discipline, and trust surfaces

The research agent path now:

- rewrites the query into a tighter research brief
- gathers evidence in bounded rounds
- curates and filters sources
- synthesizes with stable citation IDs like `S1`, `S2`
- runs a critic/fact-check pass
- revises the final answer with dated claims and inline citations

Important active codepaths include:

- `shared/research_runs/deep_research.py`
- `agents/research/phase1_ideation/problem_framer/agent.py`
- `agents/research/phase2_knowledge/literature_miner/agent.py`
- `agents/research/phase2_knowledge/knowledge_synthesizer/agent.py`
- `agents/orchestrator/tools/agent_tools.py`

The frontend beta now renders markdown answers, citations, source cards, quality summaries, and debug payloads instead of treating the run as raw JSON only.

### 4. Migrated the active OpenAI path to native Strands providers

The active runtime no longer depends on the custom OpenAI wrapper for the main research path.

The supported active path is:

- `shared/strands_openai_agent.py`

Legacy/demo-only path retained for reference:

- `shared/openai_agent.py`

Active orchestrator, negotiator, executor, verifier, and research agents now use the Strands-native OpenAI integration.

### 5. Added payment integrity and notification baseline

Phase 1 also landed the payment integrity surfaces that were originally deferred:

- `agent_payment_profiles`
- `payment_notifications`
- `payment_reconciliations`

The active deterministic payment API surface is now:

- `GET /api/payments/{payment_id}`
- `GET /api/payments/{payment_id}/events`
- `POST /api/payments/reconcile`
- `POST /api/agents/{agent_id}/payment-profile/verify`

Key behavior:

- supported paid execution requires a verified payment profile
- release/refund now emit and persist one terminal notification to the payer and one to the payee
- reconciliation can detect and repair missing notification records from persisted A2A events

Important files:

- `shared/payments/runtime.py`
- `api/routes/payments.py`
- `api/routes/agents.py`
- `agents/verifier/tools/payment_tools.py`

### 6. Added cooperative run controls and shaped evidence/report APIs

Research runs now support:

- `POST /api/research-runs/{id}/pause`
- `POST /api/research-runs/{id}/resume`
- `POST /api/research-runs/{id}/cancel`
- `GET /api/research-runs/{id}/evidence`
- `GET /api/research-runs/{id}/report`

Control semantics:

- `pause` is cooperative and stops new node scheduling after the current node settles
- `resume` restarts the executor from persisted state
- `cancel` is cooperative, cancels downstream work, and auto-rejects review-pending work when applicable

### 7. Extended the frontend beta to exercise the full Phase 1 surface

The Phase 1 frontend route is:

- `/research-runs`
- `/research-runs/[id]`

The detail page now exposes:

- live polling of run state
- pause/resume/cancel controls
- evidence and report views
- node-level inspection
- review handling
- payment activity for node-linked payments

Important files:

- `frontend/components/research-runs/ResearchRunDetailView.tsx`
- `frontend/components/research-runs/ResearchRunStatusBadge.tsx`
- `frontend/lib/api.ts`

## Validation Completed

During the final Phase 1 finish slice:

- `npm run lint` in `frontend/`
- `npm run build` in `frontend/`
- `make test`
- `make smoke`

The focused regression coverage for the finish slice also covers:

- payment profile verification
- dual-recipient terminal notifications
- payment detail/event/reconcile routes
- research-run pause/resume/cancel behavior
- evidence/report routes

## Main Files Added

- `docs/PHASE1_HANDOFF.md`
- `shared/payments/runtime.py`
- `alembic/versions/0d4a7b9c3f11_add_payment_integrity_tables.py`

## Main Files Changed

- `api/main.py`
- `api/routes/research_runs.py`
- `api/routes/payments.py`
- `api/routes/agents.py`
- `agents/orchestrator/tools/agent_tools.py`
- `agents/verifier/tools/payment_tools.py`
- `shared/database/models.py`
- `shared/research_runs/__init__.py`
- `shared/research_runs/service.py`
- `shared/runtime/contracts.py`
- `shared/runtime/task_state.py`
- `frontend/components/research-runs/ResearchRunDetailView.tsx`
- `frontend/components/research-runs/ResearchRunStatusBadge.tsx`
- `frontend/lib/api.ts`
- `README.md`
- `AGENTS.md`
- `docs/Research-Agents.md`

## What Is Next

### 1. Run the manual Phase 1 signoff matrix

The code surface is in place, but Phase 1 should be treated as fully signed off only after a real manual sweep covering:

- one live-analysis query
- one literature query
- one hybrid query
- one review-required query
- one refund/reconcile scenario

This is the main remaining acceptance task from the Phase 1 finish plan.

### 2. Start Phase 2 with evidence graph and claim lineage

Phase 2 should build on the existing run outputs instead of reopening Phase 1 topology again.

Recommended first Phase 2 slice:

- persist evidence artifacts as first-class entities
- persist claims and citation/lineage links
- move from shaped report payloads to a real evidence graph
- generate exportable report packs from verified claim state

That work should follow the design direction already outlined in `docs/Research-Agents.md`.

### 3. Add a proper eval harness for research quality

The product is now feature-complete enough that evaluation quality matters more than new control surfaces.

Recommended next evaluation work:

- fixed benchmark queries for live-analysis, literature, and hybrid modes
- rubric-based scoring for citation coverage, freshness, and uncertainty handling
- regression snapshots for source quality and claim grounding

### 4. Keep the legacy OpenAI wrapper inactive

Do not route active runtime work back through `shared/openai_agent.py`.

The supported active path should remain:

- `shared/strands_openai_agent.py`

### 5. Treat payment mutation routes as internal runtime behavior

The active public payment API is intentionally read/reconcile/profile-oriented.

Do not reintroduce public approve/reject/release/refund REST mutations unless there is a deliberate product decision to expose them outside the orchestrator/verifier runtime.

## Notes For The Next Person

- Treat `shared/research_runs/service.py` and `api/routes/research_runs.py` as the source of truth for active Phase 1 research-run behavior.
- Treat `shared/payments/runtime.py` and `api/routes/payments.py` as the source of truth for the active payment integrity baseline.
- The frontend beta is now good enough for real manual testing; prefer testing Phase 1 features there before adding more backend-only surfaces.
- If you touch cancellation, keep it cooperative unless the runtime gains a real in-flight abort capability.
- If you touch payment profiles, preserve the current Phase 1 gate that supported paid execution requires a verified payee profile.
- If you start Phase 2, do not replace the current shaped evidence/report payloads until there is a persisted evidence/claim model ready to take their place.

## Recommended PR Summary

If this branch needs to be summarized quickly:

Phase 1 adds graph-backed research runs with bounded deep-research execution, freshness-aware live analysis, citation-grounded report generation, Strands-native agent construction, deterministic payment integrity APIs, cooperative run controls, frontend report/payment visibility, and tests covering the supported end-to-end slice.
