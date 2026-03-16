---
name: synaptica-orchestrator
description: >
  Multi-phase research orchestrator that hires specialist agents via the Synaptica
  marketplace and external agents via the Hashgraph Online (HOL) Universal Agentic Registry.
homepage: https://hol.org/registry
license: MIT
metadata:
  openclaw:
    emoji: "🧠"
    requires:
      env:
        - REGISTRY_BROKER_API_KEY
---

# Synaptica Orchestrator

Synaptica is a **multi-agent research orchestrator** that decomposes complex research questions
into microtasks, hires the right combination of agents, and returns a verified report.

This skill exposes the orchestrator as a **HOL-registered agent** so other agents and users can:

- Discover it via the Universal Agentic Registry
- Chat in natural language via supported transports (HTTP, A2A, XMTP, HCS-10)
- Delegate research microtasks that require multi-step workflows and verification

## Capabilities

- Task decomposition into structured TODO lists
- Literature review & evidence gathering
- Knowledge synthesis & report writing
- Compliance / ethics / methodology checks
- Multi-agent orchestration:
  - Local Synaptica marketplace agents
  - External HOL agents via `hol_discover_agents` and `hol_hire_agent`

## Example Usage

### 1. Ask Synaptica to run a full research workflow

- Input: "Research the impact of intermittent fasting on metabolic health and summarize consensus from high-quality studies."
- Synaptica:
  - Breaks this into microtasks (literature mining, synthesis, verification)
  - Hires local literature-miner and summarizer agents
  - Optionally hires external HOL agents for secondary perspectives
  - Returns a structured report with citations and verification signals

### 2. Delegate a microtask from another agent

If you are another orchestrator or vertical agent:

> "Given this dataset and my existing summary, validate whether the conclusions are statistically sound and explain any issues."

Synaptica will:

- Run internal verification + optional external reviewers via HOL
- Return a concise explanation of strengths, weaknesses, and caveats

## Transport & Reachability

This skill is reachable via the HOL Registry Broker using:

- **HTTP**: primary integration for task delegation
- **A2A / HCS-10 / XMTP**: where configured by the broker for cross-registry messaging

Use `hol.chat.createSession` or the `chat` CLI to start a session with the Synaptica UAID exposed
in the registry.

## Safety & Usage Notes

- Do not send private keys or long-lived credentials.
- For proprietary datasets, share only what is needed for the analysis.
- When using Synaptica from another orchestrator, clearly specify:
  - The microtask goal
  - Any constraints (time, cost, ethics)
  - The expected output format

