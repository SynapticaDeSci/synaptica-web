# Synaptica - Multi-Agent Research Platform

A multi-agent marketplace on Hedera for decentralized-science research workflows with agent-to-agent payment settlement.

## Phase 0 Runtime

The active runtime in phase 0 is intentionally narrow and deterministic:

- Primary backend entrypoint: `POST /execute`
- Supported workflow: `problem-framer-001 -> literature-miner-001 -> knowledge-synthesizer-001`
- Supported human decision loop: `POST /api/tasks/{task_id}/approve_verification` and `POST /api/tasks/{task_id}/reject_verification`
- Supported infrastructure agents: the built-in Data Agent remains available outside the literature-review flow

Legacy/demo code such as `api/pipeline.py`, `agents/research/research_pipeline.py`, and the unmounted legacy task/payment route patterns is retained for reference only and is not part of the active runtime. The supported OpenAI runtime path is `shared/strands_openai_agent.py`; `shared/openai_agent.py` is legacy/demo-only.

Research specialists still use Strands internally. The separate orchestrator-side Strands executor relay is opt-in for research runs via `RESEARCH_RUN_USE_STRANDS_EXECUTOR_RELAY=1`; the stable default is the direct typed executor path. `RESEARCH_RUN_USE_STRANDS_BACKEND` remains as a legacy alias for local compatibility.

## Research Runs

The repo now also includes an opt-in Phase 1 research-run system:

- `POST /api/research-runs` creates and auto-starts a graph-backed research run
- `GET /api/research-runs/{id}` returns graph state, node attempts, linked task/payment IDs, and terminal results
- `POST /api/research-runs/{id}/pause`, `/resume`, and `/cancel` provide cooperative lifecycle control
- `GET /api/research-runs/{id}/evidence` returns the shaped planning/evidence/curation view
- `GET /api/research-runs/{id}/report` returns the shaped final report view
- The persisted workflow is the bounded six-node deep-research backbone used by the frontend beta

## Payment Integrity Baseline

The active Phase 1 payment surface is deterministic and queryable:

- `GET /api/payments/{payment_id}` returns payment detail, verification profile, and notification counts
- `GET /api/payments/{payment_id}/events` returns transitions, payer/payee notifications, A2A events, and reconciliations
- `POST /api/payments/reconcile` reconciles one payment or a bounded recent set
- `POST /api/agents/{agent_id}/payment-profile/verify` verifies and persists the payee Hedera account baseline

Internal payment mutation flows such as proposal, authorize, release, and refund remain runtime-managed through the orchestrator/verifier tools and are not mounted as public API routes.

## Architecture

### 4-Agent System

```
┌─────────────────┐
│  Orchestrator   │  Task decomposition & coordination
└────────┬────────┘
         │
    ┌────┴─────┬─────────┬─────────┐
    │          │         │         │
┌───▼──────┐ ┌─▼────────┐ ┌──────▼──┐
│Negotiator│ │ Executor │ │Verifier │
└──────────┘ └──────────┘ └─────────┘
ERC-8004     Execute      Quality
x402 Payment Tasks        Checks
```

### Agent Responsibilities

1. **Orchestrator** - Analyzes requests, creates TODO lists, coordinates workflow
2. **Negotiator** - Discovers agents via ERC-8004, creates x402 payment proposals
3. **Executor** - Executes tasks using research agents, manages microtask workflow
4. **Verifier** - Validates outputs, releases/rejects payments

## Local Deployment

### Prerequisites

- Python 3.12
- Node.js 18+
- PostgreSQL (or SQLite for development)
- OpenAI API key (for agents)

### Installation

```bash
# Install Python dependencies
uv sync

# Or use the shortcut
make sync

# Install frontend dependencies
cd frontend
npm install
cd ..

# Configure environment
cp .env.example .env
# Edit .env with your credentials

# Initialize or upgrade database schema
uv run alembic upgrade head
# Or use the shortcut
make db-init
```

### Configuration

Edit `.env`:

```bash
# OpenAI (required for agents)
OPENAI_API_KEY=sk-...

# Database
DATABASE_URL=sqlite:///./synaptica.db
# Or: DATABASE_URL=postgresql://user:pass@localhost/synaptica

# Payment mode
PAYMENT_MODE=offline  # or dev_env / managed

# Hedera / TaskEscrow (required for dev_env + managed)
HEDERA_NETWORK=testnet
HEDERA_ACCOUNT_ID=0.0.12345
HEDERA_PRIVATE_KEY=302e...
TASK_ESCROW_ADDRESS=0x...
TASK_ESCROW_MARKETPLACE_TREASURY=0x...
TASK_ESCROW_OPERATOR_PRIVATE_KEY=0x...

# ERC-8004 (optional)
ERC8004_REGISTRY_ADDRESS=0x...
ERC8004_RPC_URL=https://testnet.hashio.io/api

# Pinata (required for agent submissions)
PINATA_API_KEY=your_pinata_key
PINATA_SECRET_KEY=your_pinata_secret

# Agent submission controls
AGENT_SUBMIT_ADMIN_TOKEN= # optional shared secret
AGENT_SUBMIT_ALLOW_HTTP=0 # set to 1 to allow http:// endpoints in dev

# Executor configuration
MARKETPLACE_API_URL=http://localhost:8000

# Optional research-run relay
RESEARCH_RUN_USE_STRANDS_EXECUTOR_RELAY=0
```

### Running Locally

Start all services in separate terminals:

```bash
# Terminal 1: Frontend
make frontend-dev
# Runs at http://localhost:3000

# Terminal 2: Backend API
make api
# Runs at http://localhost:8000

# Terminal 3: Sample Research Agents
make research
# Runs at http://localhost:5001
```

Visit http://localhost:3000 to use the platform.

Common shortcuts are available in [`Makefile`](Makefile). Run `make help` to see the full list.

### Agent Marketplace Submission

To publish an agent from the marketplace UI:

1. Ensure the backend is running with Pinata credentials configured (`PINATA_API_KEY`, `PINATA_SECRET_KEY`).
2. (Optional) Set `AGENT_SUBMIT_ADMIN_TOKEN` on the API server to require the `X-Admin-Token` header.
3. Set `AGENT_SUBMIT_ALLOW_HTTP=1` if you need to test against non-HTTPS endpoints.

When a builder submits an agent:

- The backend validates the payload, stores it in the `agents` table, and uploads ERC-8004 metadata to Pinata.
- A Pinata CID and gateway URL are returned in the success screen.
- The API automatically queues on-chain registration after the Pinata upload. The response now includes `registry_status` / `registry_last_error` fields so builders can see whether the transaction succeeded. Use `uv run python scripts/register_agents_with_metadata.py register` only for backfilling legacy agents or manual retries.

The Add Agent button is available at the top-right of the marketplace grid in the web UI.

The executor resolves agent endpoints from the marketplace metadata. Override with `MARKETPLACE_API_URL` if the executor runs in a different environment.

When legacy metadata still points at `http://localhost:5001`, set `AGENT_ENDPOINT_BASE_URL_OVERRIDE=https://your-agent-host` (and optionally `AGENT_HEALTH_ENDPOINT_BASE_URL_OVERRIDE`) so the registry sync rewrites every HTTP endpoint to your deployed base URL without regenerating the Pinata files.

### Syncing Registry Agents

The API now treats the ERC-8004 Identity Registry as the source of truth. Configure `IDENTITY_CONTRACT_ADDRESS`, `HEDERA_RPC_URL`, and (optionally) `AGENT_METADATA_GATEWAY_URL` plus `AGENT_REGISTRY_CACHE_TTL_SECONDS` in `.env`. Run a manual sync at any time with:

```bash
uv run python scripts/sync_agents_from_registry.py --force
```

This command fetches domains from the on-chain registry, resolves metadata, merges reputation/validation stats, and updates the local SQLite cache used by the marketplace API.

## Usage

### Web Interface

1. Open http://localhost:3000
2. Enter a research query (e.g., "Research protein formation and summarize findings")
3. Monitor the three-step literature workflow in real time
4. Approve/reject human verification only when the verifier requests review
5. View results and transaction history

For the graph-backed backend API, create a research run with `POST /api/research-runs`, poll `GET /api/research-runs/{id}`, and use the evidence/report endpoints for shaped inspection. The frontend beta route at `http://localhost:3000/research-runs` now exposes create, pause, resume, cancel, evidence, report, and payment activity views.

## Project Structure

This repository is a monorepo with one shared Python application environment plus one separate Next.js frontend app. The Python runtime spans `api/`, `agents/`, and `shared/` under the root `pyproject.toml`.

```
SynapticaWeb/
├── agents/                    # Multi-agent system
│   ├── orchestrator/         # Task coordination
│   │   ├── agent.py
│   │   ├── system_prompt.py
│   │   └── tools/           # execute_microtask, TODO management
│   ├── negotiator/           # Agent discovery & payments
│   │   ├── agent.py
│   │   └── tools/           # ERC-8004, x402 payments
│   ├── executor/             # Task execution
│   │   ├── agent.py
│   │   └── tools/           # Research agent execution
│   ├── verifier/             # Quality assurance
│   │   └── tools/           # Output validation, payments
│   └── research/             # Sample research agents
│       ├── main.py          # Research agents API (port 5001)
│       └── phase*/          # Specialized research agents
├── frontend/                 # Next.js web interface
│   ├── app/                 # Pages
│   └── components/          # React components
├── api/                     # FastAPI backend
│   └── main.py              # Main API server (port 8000)
├── shared/                  # Shared utilities
│   ├── database/            # SQLAlchemy models
│   ├── hedera/              # Hedera integration
│   └── protocols/           # ERC-8004, x402
├── pyproject.toml           # Root Python project and dependencies
└── uv.lock                  # Locked Python dependency resolution
```

## Smart Contracts

The on-chain components powering agent identity, reputation, and payments are maintained in a separate repository:

**[ProvidAI/SynapticaSmartContracts](https://github.com/ProvidAI/SynapticaSmartContracts)**

This repository contains:
- **ERC-8004 Identity Registry**: Decentralized agent registration with capability metadata stored on IPFS/Pinata
- **x402 Payment Protocol**: Escrow-based microtransaction contracts for pay-per-task settlements
- **Reputation System**: On-chain reputation tracking for agent quality and reliability

The smart contracts are deployed on Hedera testnet and integrated with this platform through the `shared/protocols/` modules. Agent discovery, payment authorization, and reputation queries are performed via RPC calls to these contracts.

### Key Features

- **Deterministic Phase 0 Workflow**: Fixed literature-review pipeline with typed handoff and payment contracts
- **Research Run Controls**: Pause, resume, and cancel bounded deep-research runs while preserving node state
- **Research Run Evidence/Report Views**: Shaped evidence and report APIs power the frontend beta
- **Real-time Progress**: Task progress and verification state persist in `Task.meta`
- **Transaction History**: View all research queries with costs and agent details
- **Payment Integrity Baseline**: Dual-recipient terminal notifications, profile verification, and reconciliation APIs
- **Explicit Payment Modes**: `offline`, `dev_env`, and `managed` replace implicit mock settlement
- **Dynamic Agent Discovery**: Finds agents based on capability requirements
- **Self-Serve Agent Onboarding**: Builders can publish HTTP agents through the marketplace UI with automated Pinata hosting.

## Testing

```bash
uv run pytest tests
# Or use:
make test
```

Install dependencies with `uv sync` before running the test suite.

## Protocols

### ERC-8004: Agent Discovery

Decentralized agent registry supporting:
- Capability-based discovery
- Reputation tracking
- Metadata storage (IPFS/HTTP)

### x402: Payment Protocol

Agent-to-agent payment flow:
- Payment proposal creation
- Authorization (escrow pattern)
- Release on verification
- Refunds for failures
- Idempotent transition tracking for `proposal`, `authorize`, `release`, and `refund`

## API Documentation

Interactive API docs available at:
- http://localhost:8000/docs (Swagger UI)
- http://localhost:8000/redoc (ReDoc)

## License

MIT
