# Research Agents Server

This directory contains the built-in research specialists and the FastAPI server on port `5001`.

## Supported Public Agents

These are the only built-in research agents mounted on the active server and exposed through the default product surface:

- **problem-framer-001** - Frames research questions into a scoped research-run brief
- **literature-miner-001** - Gathers and curates source-grounded evidence
- **knowledge-synthesizer-001** - Drafts, critiques, and revises the final synthesis

## Quarantined Legacy Specialists

The rest of the built-in specialist roster remains in the repo as legacy code only. These agents are not mounted by the active server and are hidden from the default marketplace directory until they are migrated to typed research-run contracts:

- `goal-planner-001`
- `feasibility-analyst-001`
- `hypothesis-designer-001`
- `code-generator-001`
- `experiment-runner-001`
- `insight-generator-001`
- `bias-detector-001`
- `compliance-checker-001`
- `paper-writer-001`
- `peer-reviewer-001`
- `reputation-manager-001`
- `archiver-001`

## Running the Server

```bash
# From the project root
uv run python -m uvicorn agents.research.main:app --port 5001 --reload
```
