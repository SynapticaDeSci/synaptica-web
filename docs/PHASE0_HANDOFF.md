# Phase 0 Handoff

## Context

This branch implements the Phase 0 foundation plan for the Synaptica DeSci runtime.

The goal of this phase was to harden the existing hackathon codebase without introducing the future research-run/DAG model yet. The supported production path is now:

`problem-framer-001 -> literature-miner-001 -> knowledge-synthesizer-001 -> verification/payment`

The task-backed runtime remains the main entrypoint through `POST /execute`, the marketplace stays live, and agent-to-agent payment remains part of the product model.

Worktree used for this implementation:

- Path: `<local checkout path>`
- Branch: `feat/phase0-foundation`

## What Was Done

### 1. Replaced the fragile runtime handoff with typed contracts

Added shared typed runtime contracts in `shared/runtime/contracts.py`:

- `HandoffContext`
- `TelemetryEnvelope`
- `AgentSelectionResult`
- `ExecutionRequest`
- `ExecutionResult`
- `VerificationRequest`
- `VerificationResult`
- `PaymentActionContext`

These are now the supported machine-readable contracts between negotiation, execution, verification, and payment. The runtime no longer depends on scraping LLM prose for things like payment IDs, verification scores, or downstream state.

### 2. Locked Phase 0 to a deterministic supported workflow

The live `/execute` flow in `api/main.py` now runs a fixed literature-review sequence using the phase 0 agents only. The orchestrator tool layer in `agents/orchestrator/tools/agent_tools.py` was rewritten so the execution path is:

1. Select a supported agent for the current todo.
2. Create and authorize a payment.
3. Execute the selected agent over HTTP.
4. Verify the result through the verifier.
5. Release or refund payment based on the verification outcome.

This means the supported runtime is now explicit, auditable, and easier to reason about than the old free-form orchestration.

### 3. Persisted runtime and verification state into `Task.meta`

The runtime is no longer RAM-only for the important verification/handoff state. `shared/runtime/task_state.py` now persists:

- current handoff context
- verification pending flag
- verification decision
- current progress snapshot
- runtime telemetry

The in-memory task store still exists as a cache, but task recovery and status reads now hydrate from the database-backed task state when needed.

### 4. Added explicit payment modes and idempotent payment transitions

Payment behavior is now controlled by `PAYMENT_MODE`:

- `managed`
- `dev_env`
- `offline`

Shared payment logic lives in `shared/payments/service.py`. It validates configuration, normalizes action/mode enums, and enforces idempotency for:

- `proposal`
- `authorize`
- `release`
- `refund`

A new `payment_state_transitions` table was added in `shared/database/models.py` with a unique constraint across:

- `payment_id`
- `action`
- `idempotency_key`

This blocks duplicate terminal settlement and makes retries return the already-recorded successful result.

### 5. Tightened payment and secret-handling behavior

Sensitive payload rejection and redaction were added in `shared/runtime/security.py`.

Current protections include:

- private-key-like values are rejected from payment action metadata
- sensitive values are redacted before structured persistence/logging
- x402 signing no longer reads private keys from request/task metadata
- only configured signer env vars are used for signing in non-offline modes

### 6. Enforced support tiers

Research agents are now classified with a metadata-level `support_tier`:

- `supported`
- `experimental`
- `legacy`

This is surfaced in the marketplace/API and enforced in:

- agent serialization
- agent listing responses
- negotiator selection
- executor dispatch

The executor can also fall back to the local marketplace database to enforce support-tier checks even if the marketplace HTTP lookup is unavailable.

### 7. Quarantined legacy/demo code instead of deleting it

The old pipeline and stale routes were left in place but marked as non-primary/legacy, including:

- `agents/research/research_pipeline.py`
- `api/pipeline.py`
- `api/routes/tasks.py`
- `api/routes/payments.py`

This preserves reference material without leaving ambiguity about what the live runtime is.

### 8. Aligned the frontend to the supported backend contract

Frontend changes removed the dead browser-side payment path and aligned the UI to task-level verification review.

Key changes:

- removed the unused payment modal
- removed the dead x402 proxy route
- stopped calling unmounted `/api/payments/{id}/approve|reject` flows
- kept approve/reject review at the task level
- exposed `support_tier` in frontend agent types
- added a minimal Next ESLint config so lint can run non-interactively

## Validation Completed

Backend validation:

- `uv run pytest tests -q`
- Result: `25 passed`

Frontend validation:

- `npm run lint`
- Result: passed with no ESLint warnings or errors

Additional sanity checks completed during implementation:

- `python -m compileall api agents shared tests`

## Main Files Added

- `shared/runtime/contracts.py`
- `shared/runtime/security.py`
- `shared/runtime/task_state.py`
- `shared/payments/service.py`
- `shared/research/catalog.py`
- `tests/test_phase0_runtime.py`
- `frontend/.eslintrc.json`

## Main Files Changed

- `api/main.py`
- `agents/orchestrator/tools/agent_tools.py`
- `agents/negotiator/tools/payment_tools.py`
- `agents/verifier/tools/payment_tools.py`
- `agents/executor/tools/research_api_executor.py`
- `shared/database/models.py`
- `shared/protocols/a2a_transport.py`
- `shared/protocols/x402.py`
- `api/routes/agents.py`
- `shared/agent_utils.py`
- `frontend/lib/api.ts`
- `frontend/store/taskStore.ts`
- `frontend/app/page.tsx`
- `frontend/components/TaskStatusCard.tsx`
- `frontend/components/TaskResults.tsx`

## What Is Still Next

### 1. Add a real migration for production databases

The SQLAlchemy model for `payment_state_transitions` is in place, but production deployment should include an explicit schema migration plan so existing environments can upgrade safely.

### 2. Do a staging pass for `managed` payment mode

The automated tests validate the happy path in `offline` mode and fail-closed behavior in non-offline mode. Before production rollout, we should run an end-to-end staging test with real managed signer configuration.

Suggested staging checks:

- missing signer config fails closed
- a valid proposal/authorize/release flow works on the intended network
- no secret material leaks into task metadata, payment metadata, or A2A records

### 3. Decide how aggressively to isolate the legacy surfaces

Right now the old pipeline/routes are clearly marked as legacy. A future cleanup pass can decide whether to:

- leave them as documented legacy references
- move them into a `legacy/` area
- gate them behind explicit feature flags

### 4. Phase 1 design work

Phase 1 should begin the research-run/DAG model on top of the now-stabilized phase 0 runtime instead of trying to revive the old hackathon orchestration patterns.

Recommended Phase 1 preparation:

- define research-run/task graph entities explicitly
- design how marketplace discovery maps onto research-run planning
- define smart-contract touchpoints only after the off-chain runtime/state model is stable

### 5. Address pre-existing deprecation warnings

The current test suite is green, but there are pre-existing warnings in older Pydantic/SQLAlchemy codepaths. These are not phase 0 blockers, but they should be cleaned up before they become migration pressure later.

Examples:

- Pydantic v1-style validators in `shared/research/schemas.py`
- `datetime.utcnow()` deprecation warnings
- older SQLAlchemy declarative-base usage

## Notes For The Next Person

- Treat `api/main.py` plus `agents/orchestrator/tools/agent_tools.py` as the source of truth for the live phase 0 runtime.
- Do not reintroduce browser-side payment approval flows unless there is a deliberate product/API decision to do so.
- Do not let unsupported research agents back into the default runtime path.
- Keep `offline` mode clearly labeled as local-development-only behavior.
- If you touch payments, keep the idempotency-key shape aligned with `task_id:todo_id:attempt_id:action`.
- If you touch verification, preserve the task-level approve/reject endpoints because the frontend now depends on them.

## Recommended PR Summary

If this branch needs to be summarized quickly:

Phase 0 turns the previous hackathon runtime into a deterministic, typed, task-backed literature-review workflow with explicit payment modes, idempotent payment transitions, persisted verification state, support-tier enforcement, frontend contract cleanup, and tests covering the supported slice.
