# Research Agents Server

This directory contains all research agents and a FastAPI server to host them on port 5001.

## Available Agents

### Phase 1: Ideation
- **problem-framer-001** - Frames research questions from unstructured ideas
- **goal-planner-001** - Creates structured research goals and milestones
- **feasibility-analyst-001** - Evaluates research feasibility

### Phase 2: Knowledge
- **literature-miner-001** - Searches and extracts relevant research literature
- **knowledge-synthesizer-001** - Synthesizes knowledge from multiple sources

### Phase 3: Experimentation
- **hypothesis-designer-001** - Designs testable hypotheses
- **code-generator-001** - Generates experimental code
- **experiment-runner-001** - Executes experiments and collects results

### Phase 4: Interpretation
- **insight-generator-001** - Generates insights from experimental data
- **bias-detector-001** - Detects biases in research methodology
- **compliance-checker-001** - Checks research compliance with standards

### Phase 5: Publication
- **paper-writer-001** - Writes research papers
- **peer-reviewer-001** - Reviews research papers
- **reputation-manager-001** - Manages agent reputation
- **archiver-001** - Archives research artifacts

## Running the Server

```bash
# From the project root
uv run python -m uvicorn agents.research.main:app --port 5001 --reload
```
