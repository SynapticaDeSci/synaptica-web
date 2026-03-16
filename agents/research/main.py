"""
FastAPI server for hosting the supported built-in research agents.

This server runs on port 5001 and provides A2A endpoints only for the
currently supported research-run specialists.

Usage:
    uv run python -m uvicorn agents.research.main:app --port 5001 --reload
"""

import logging
from contextlib import asynccontextmanager
from functools import lru_cache
from importlib import import_module
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
from shared.research.agent_inventory import iter_supported_builtin_research_agents

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_agent_registry() -> Dict[str, Any]:
    """Load only the supported built-in research agents."""

    registry: Dict[str, Any] = {}
    for record in iter_supported_builtin_research_agents():
        if not record.module_path or not record.instance_name:
            raise RuntimeError(f"Missing import target for supported research agent '{record.agent_id}'")
        module = import_module(record.module_path)
        registry[record.agent_id] = getattr(module, record.instance_name)
    return registry


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    # Startup: Create database tables
    logger.info("Initializing database...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized")

    # Register all agents in database now that tables exist
    logger.info("Registering agents in database...")
    for agent_id, agent in get_agent_registry().items():
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
    description="A2A endpoints for the supported built-in research agents",
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
    registry = get_agent_registry()
    return {
        "status": "online",
        "service": "Research Agents API",
        "version": "1.0.0",
        "total_agents": len(registry),
    }


@app.get("/agents")
async def list_agents():
    """List all available agents with their metadata."""
    registry = get_agent_registry()
    agents_info = []

    for agent_id, agent in registry.items():
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
    registry = get_agent_registry()
    agent = registry.get(agent_id)

    if not agent:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_id}' not found. Available agents: {list(registry.keys())}"
        )

    return agent.get_metadata()


@app.post("/agents/{agent_id}", response_model=AgentResponse)
async def execute_agent(agent_id: str, request_data: AgentRequest):
    """
    Execute a research agent with the provided request.

    Args:
        agent_id: The ID of the agent to execute (e.g., "problem-framer-001")
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
    registry = get_agent_registry()
    agent = registry.get(agent_id)

    if not agent:
        logger.error(f"Agent not found: {agent_id}")
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_id}' not found. Available agents: {list(registry.keys())}"
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
    registry = get_agent_registry()
    return {
        "status": "healthy",
        "agents_loaded": len(registry),
        "agent_ids": list(registry.keys()),
    }


if __name__ == "__main__":
    logger.info("Starting Research Agents API server on port 5001...")
    logger.info(f"Loaded {len(get_agent_registry())} research agents")

    uvicorn.run(
        "agents.research.main:app",
        host="0.0.0.0",
        port=5001,
        reload=True,
        log_level="info"
    )
