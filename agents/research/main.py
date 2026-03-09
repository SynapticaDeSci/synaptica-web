"""
FastAPI server for hosting all research agents.

This server runs on port 5001 and provides A2A endpoints for all research agents.
Each agent is accessible at /agents/{agent-id}

Usage:
    uv run python -m uvicorn agents.research.main:app --port 5001 --reload
"""

import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from shared.database import Base, engine
# Import all models to ensure they're registered with Base before create_all()
from shared.database.models import (
    Agent,
    Task,
    Payment,
    AgentReputation,
    ResearchPipeline,
    ResearchPhase,
    ResearchArtifact,
    A2AEvent,
)

# Load environment variables
load_dotenv()

from agents.research.phase1_ideation.feasibility_analyst.agent import (
    feasibility_analyst_agent,
)
from agents.research.phase1_ideation.goal_planner.agent import goal_planner_agent

# Import all research agents
from agents.research.phase1_ideation.problem_framer.agent import problem_framer_agent
from agents.research.phase2_knowledge.knowledge_synthesizer.agent import (
    knowledge_synthesizer_agent,
)
from agents.research.phase2_knowledge.literature_miner.agent import (
    literature_miner_agent,
)
from agents.research.phase3_experimentation.code_generator.agent import (
    code_generator_001_agent,
)
from agents.research.phase3_experimentation.experiment_runner.agent import (
    experiment_runner_001_agent,
)
from agents.research.phase3_experimentation.hypothesis_designer.agent import (
    hypothesis_designer_001_agent,
)
from agents.research.phase4_interpretation.bias_detector.agent import (
    bias_detector_001_agent,
)
from agents.research.phase4_interpretation.compliance_checker.agent import (
    compliance_checker_001_agent,
)
from agents.research.phase4_interpretation.insight_generator.agent import (
    insight_generator_001_agent,
)
from agents.research.phase5_publication.archiver.agent import archiver_001_agent
from agents.research.phase5_publication.paper_writer.agent import paper_writer_001_agent
from agents.research.phase5_publication.peer_reviewer.agent import (
    peer_reviewer_001_agent,
)
from agents.research.phase5_publication.reputation_manager.agent import (
    reputation_manager_001_agent,
)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    # Startup: Create database tables
    logger.info("Initializing database...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized")

    # Register all agents in database now that tables exist
    logger.info("Registering agents in database...")
    for agent_id, agent in AGENT_REGISTRY.items():
        try:
            agent._register_in_database()
        except Exception as e:
            logger.warning(f"Failed to register agent {agent_id}: {e}")

    logger.info("Research agents ready")
    yield
    # Shutdown
    logger.info("Shutting down research agents...")


# Create FastAPI app
app = FastAPI(
    title="Research Agents API",
    description="A2A endpoints for all research agents",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Agent registry - maps agent_id to agent instance
AGENT_REGISTRY = {
    # Phase 1: Ideation
    "problem-framer-001": problem_framer_agent,
    "goal-planner-001": goal_planner_agent,
    "feasibility-analyst-001": feasibility_analyst_agent,

    # Phase 2: Knowledge
    "literature-miner-001": literature_miner_agent,
    "knowledge-synthesizer-001": knowledge_synthesizer_agent,

    # Phase 3: Experimentation
    "hypothesis-designer-001": hypothesis_designer_001_agent,
    "code-generator-001": code_generator_001_agent,
    "experiment-runner-001": experiment_runner_001_agent,

    # Phase 4: Interpretation
    "insight-generator-001": insight_generator_001_agent,
    "bias-detector-001": bias_detector_001_agent,
    "compliance-checker-001": compliance_checker_001_agent,

    # Phase 5: Publication
    "paper-writer-001": paper_writer_001_agent,
    "peer-reviewer-001": peer_reviewer_001_agent,
    "reputation-manager-001": reputation_manager_001_agent,
    "archiver-001": archiver_001_agent,
}


class AgentRequest(BaseModel):
    """Request model for agent execution."""
    request: str
    context: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


class AgentResponse(BaseModel):
    """Response model for agent execution."""
    success: bool
    agent_id: str
    result: Optional[Any] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "online",
        "service": "Research Agents API",
        "version": "1.0.0",
        "total_agents": len(AGENT_REGISTRY)
    }


@app.get("/agents")
async def list_agents():
    """List all available agents with their metadata."""
    agents_info = []

    for agent_id, agent in AGENT_REGISTRY.items():
        agents_info.append({
            "agent_id": agent_id,
            "name": agent.name,
            "description": agent.description,
            "capabilities": agent.capabilities,
            "pricing": agent.pricing,
            "endpoint": f"/agents/{agent_id}",
            "reputation_score": agent.get_reputation_score()
        })

    return {
        "total_agents": len(agents_info),
        "agents": agents_info
    }


@app.get("/agents/{agent_id}")
async def get_agent_metadata(agent_id: str):
    """Get metadata for a specific agent."""
    agent = AGENT_REGISTRY.get(agent_id)

    if not agent:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_id}' not found. Available agents: {list(AGENT_REGISTRY.keys())}"
        )

    return agent.get_metadata()


@app.post("/agents/{agent_id}", response_model=AgentResponse)
async def execute_agent(agent_id: str, request_data: AgentRequest):
    """
    Execute a research agent with the provided request.

    Args:
        agent_id: The ID of the agent to execute (e.g., "feasibility-analyst-001")
        request_data: The agent request containing:
            - request: The task/query for the agent
            - context: Optional additional context
            - metadata: Optional metadata

    Returns:
        AgentResponse with execution results
    """
    logger.info(f"Received request for agent: {agent_id}")
    logger.info(f"Request: {request_data.request[:100]}...")

    # Get agent from registry
    agent = AGENT_REGISTRY.get(agent_id)

    if not agent:
        logger.error(f"Agent not found: {agent_id}")
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_id}' not found. Available agents: {list(AGENT_REGISTRY.keys())}"
        )

    try:
        # Execute the agent
        logger.info(f"Executing agent: {agent_id}")
        result = await agent.execute(request_data.request, context=request_data.context)

        logger.info(f"Agent {agent_id} execution {'succeeded' if result['success'] else 'failed'}")

        return AgentResponse(
            success=result["success"],
            agent_id=agent_id,
            result=result.get("result"),
            error=result.get("error"),
            metadata={
                **(result.get("metadata", {})),
                **(request_data.metadata or {})
            }
        )

    except Exception as e:
        logger.error(f"Error executing agent {agent_id}: {str(e)}", exc_info=True)
        return AgentResponse(
            success=False,
            agent_id=agent_id,
            error=f"Internal server error: {str(e)}",
            metadata=request_data.metadata
        )


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "agents_loaded": len(AGENT_REGISTRY),
        "agent_ids": list(AGENT_REGISTRY.keys())
    }


if __name__ == "__main__":
    logger.info("Starting Research Agents API server on port 5001...")
    logger.info(f"Loaded {len(AGENT_REGISTRY)} research agents")

    uvicorn.run(
        "agents.research.main:app",
        host="0.0.0.0",
        port=5001,
        reload=True,
        log_level="info"
    )
