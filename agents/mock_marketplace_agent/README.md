# Marketplace Probe Agent

This FastAPI service mimics a simple ERC-8004 style agent so you can test the marketplace UI and orchestrator flows without having to wire up a real research agent.

## Default Endpoint

- Execute URL: `http://127.0.0.1:6123/execute`
- Health check: `GET http://127.0.0.1:6123/health`
- Agent card: `GET http://127.0.0.1:6123/.well-known/agent.json`

Set `MOCK_AGENT_PORT` (and optionally `MOCK_AGENT_HOST`) before launching if you need to run it on a different interface or port.

## Running the Agent

```bash
uv run python -m uvicorn agents.mock_marketplace_agent.server:app --host 0.0.0.0 --port 6123 --reload
```

You can also run `uv run python -m agents.mock_marketplace_agent.server` to use the bundled `A2AServer` runner.

## Smoke Tests

```bash
curl -s http://127.0.0.1:6123/.well-known/agent.json | jq '.name'
curl -s http://127.0.0.1:6123/health | jq
curl -s -X POST http://127.0.0.1:6123/execute \
  -H "Content-Type: application/json" \
  -d '{"request":"ping","metadata":{"task_id":"demo-task"}}' | jq
```

The `/execute` response includes timestamps and a call counter so you can confirm the orchestrator routed your request to the fake agent.
