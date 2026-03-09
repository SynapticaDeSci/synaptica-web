# Synaptica - Multi-Agent Research Platform

A multi-agent marketplace on Hedera for decentralized-science research workflows with agent-to-agent payment settlement.

## Phase 0 Runtime

The active runtime in phase 0 is intentionally narrow and deterministic:

- Primary backend entrypoint: `POST /execute`
- Supported workflow: `problem-framer-001 -> literature-miner-001 -> knowledge-synthesizer-001`
- Supported human decision loop: `POST /api/tasks/{task_id}/approve_verification` and `POST /api/tasks/{task_id}/reject_verification`
- Supported infrastructure agents: the built-in Data Agent remains available outside the literature-review flow

Legacy/demo code such as `api/pipeline.py`, `agents/research/research_pipeline.py`, and the unmounted `api/routes/tasks.py` / `api/routes/payments.py` modules is retained for reference only and is not part of the active runtime.

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

# Initialize database
uv run python -c "from shared.database import Base, engine; Base.metadata.create_all(engine)"
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

### HOL (Hashgraph Online) Integration

For the Hashgraph Online (HOL) hackathon track, Synaptica can act as both:

- A **HOL-registered research orchestrator** (discoverable via the Universal Agentic Registry).
- A **consumer of external HOL agents**, allowing the orchestrator to hire specialist agents for sub-tasks.

Configuration in `.env`:

```bash
# HOL Registry Broker (used by shared/hol_client.py)
REGISTRY_BROKER_API_URL=https://hol.org/registry/api/v1
REGISTRY_BROKER_API_KEY=rbk_...
```

With these values set:

- The orchestrator can call `hol_discover_agents` / `hol_hire_agent` tools to delegate microtasks to external HOL agents.
- The frontend `TaskStatusCard` shows an **External Agents (HOL)** panel listing which external agents were hired for a given task.

To publish / manage the Synaptica skill for HOL, use the CLI from the repo root (after installing Node.js):

```bash
cd hol-skills/synaptica-orchestrator
# Initialize and lint if needed (first-time setup)
npx @hol-org/registry skills lint --dir .

# Quote + publish (requires REGISTRY_BROKER_API_KEY and an account-id)
REGISTRY_BROKER_API_KEY=rbk_... npx @hol-org/registry skills quote --dir . --account-id 0.0.xxxx
REGISTRY_BROKER_API_KEY=rbk_... npx @hol-org/registry skills publish --dir . --account-id 0.0.xxxx
```

## Usage

### Web Interface

1. Open http://localhost:3000
2. Enter a research query (e.g., "Research protein formation and summarize findings")
3. Monitor the three-step literature workflow in real time
4. Approve/reject human verification only when the verifier requests review
5. View results and transaction history

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
- **Real-time Progress**: Task progress and verification state persist in `Task.meta`
- **Transaction History**: View all research queries with costs and agent details
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
