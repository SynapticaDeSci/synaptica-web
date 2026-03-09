#!/usr/bin/env python
"""
Legacy demo-only research pipeline API.

This module is not mounted by ``api.main`` and is retained only as a reference
for the original hackathon prototype. The active phase 0 runtime uses
``POST /execute`` in ``api.main`` instead.
"""

import os
import uuid
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from shared.database import SessionLocal, Task, Agent, Payment
from agents.orchestrator.agent import create_orchestrator_agent
from agents.negotiator.agent import create_negotiator_agent
from agents.executor.agent import create_executor_agent
from agents.verifier.agent import create_verifier_agent

router = APIRouter(prefix="/api/research", tags=["research"])

class ResearchRequest(BaseModel):
    """Request model for research pipeline execution"""
    description: str = Field(..., description="Research task description")
    budget_limit: float = Field(100.0, description="Maximum budget in USD")
    capability_requirements: str = Field("research", description="Required agent capabilities")
    min_reputation_score: float = Field(0.7, description="Minimum agent reputation")
    verification_mode: str = Field("standard", description="Verification mode: standard or enhanced")

class ResearchResponse(BaseModel):
    """Response model for research pipeline"""
    task_id: str
    status: str
    message: str
    result: Dict[str, Any] = None
    error: str = None

# Research agent pool (simulated for now)
RESEARCH_AGENTS = {
    "problem-framer-001": {"name": "Problem Framer", "price": 5.0, "reputation": 4.8},
    "literature-miner-001": {"name": "Literature Miner", "price": 8.0, "reputation": 4.7},
    "feasibility-analyst-001": {"name": "Feasibility Analyst", "price": 6.0, "reputation": 4.9},
    "goal-planner-001": {"name": "Goal Planner", "price": 5.0, "reputation": 4.6},
    "knowledge-synthesizer-001": {"name": "Knowledge Synthesizer", "price": 7.0, "reputation": 4.8},
    "hypothesis-designer-001": {"name": "Hypothesis Designer", "price": 6.0, "reputation": 4.7},
    "experiment-runner-001": {"name": "Experiment Runner", "price": 10.0, "reputation": 4.5},
    "code-generator-001": {"name": "Code Generator", "price": 9.0, "reputation": 4.9},
    "insight-generator-001": {"name": "Insight Generator", "price": 7.0, "reputation": 4.8},
    "bias-detector-001": {"name": "Bias Detector", "price": 5.0, "reputation": 4.7},
    "compliance-checker-001": {"name": "Compliance Checker", "price": 4.0, "reputation": 4.6},
    "paper-writer-001": {"name": "Paper Writer", "price": 12.0, "reputation": 4.8},
    "peer-reviewer-001": {"name": "Peer Reviewer", "price": 6.0, "reputation": 4.9},
    "reputation-manager-001": {"name": "Reputation Manager", "price": 3.0, "reputation": 4.5},
    "archiver-001": {"name": "Archiver", "price": 2.0, "reputation": 4.7}
}

@router.post("/execute", response_model=ResearchResponse)
async def execute_research_pipeline(request: ResearchRequest):
    """
    Execute the full research pipeline with payment flow
    """
    db = SessionLocal()

    try:
        # Step 1: Create Task
        task_id = str(uuid.uuid4())
        task = Task(
            id=task_id,
            title=f"Research: {request.description[:50]}",
            description=request.description,
            status="pending",
            created_at=datetime.utcnow(),
            meta={
                "budget": request.budget_limit,
                "capability_requirements": request.capability_requirements,
                "min_reputation": request.min_reputation_score,
                "verification_mode": request.verification_mode
            }
        )
        db.add(task)
        db.commit()

        # Step 2: Select agents within budget
        selected_agents = select_agents_for_budget(
            budget=request.budget_limit,
            min_reputation=request.min_reputation_score
        )

        if not selected_agents:
            task.status = "failed"
            db.commit()
            return ResearchResponse(
                task_id=task_id,
                status="failed",
                message="No agents available within budget",
                error="Budget too low for any agent combination"
            )

        # Step 3: Create payment authorizations
        payments = []
        for agent_id, agent_data in selected_agents.items():
            payment_id = str(uuid.uuid4())
            payment = Payment(
                id=payment_id,
                task_id=task_id,
                agent_id=agent_id,
                amount=agent_data["price"],
                currency="USD",
                status="authorized",
                created_at=datetime.utcnow(),
                meta={
                    "agent_name": agent_data["name"],
                    "reputation": agent_data["reputation"]
                }
            )
            db.add(payment)
            payments.append(payment)

        db.commit()

        # Step 4: Update task status
        task.status = "in_progress"
        db.commit()

        # Step 5: Execute research (simulated for now)
        research_output = await execute_research_agents(
            task_id=task_id,
            agents=selected_agents,
            description=request.description
        )

        # Step 6: Verify results
        verification_results = await verify_research_output(
            task_id=task_id,
            output=research_output,
            verification_mode=request.verification_mode
        )

        # Step 7: Release or refund payments based on verification
        for payment in payments:
            agent_output = research_output.get(payment.agent_id, {})
            if agent_output.get("quality_score", 0) >= 50:
                payment.status = "completed"
            else:
                payment.status = "refunded"

        db.commit()

        # Step 8: Complete task
        task.status = "completed"
        task.result = {
            "research_output": research_output,
            "verification": verification_results,
            "agents_used": list(selected_agents.keys()),
            "total_cost": sum(a["price"] for a in selected_agents.values()
                            if research_output.get(a, {}).get("quality_score", 0) >= 50)
        }
        db.commit()

        return ResearchResponse(
            task_id=task_id,
            status="completed",
            message="Research pipeline executed successfully",
            result=task.result
        )

    except Exception as e:
        if task:
            task.status = "failed"
            db.commit()

        return ResearchResponse(
            task_id=task_id if task_id else "",
            status="failed",
            message="Pipeline execution failed",
            error=str(e)
        )

    finally:
        db.close()

def select_agents_for_budget(budget: float, min_reputation: float) -> Dict[str, Any]:
    """
    Select optimal agents within budget constraints
    """
    # Filter agents by reputation
    eligible_agents = {
        agent_id: agent_data
        for agent_id, agent_data in RESEARCH_AGENTS.items()
        if agent_data["reputation"] >= min_reputation
    }

    # Sort by price-performance ratio
    sorted_agents = sorted(
        eligible_agents.items(),
        key=lambda x: x[1]["price"] / x[1]["reputation"],
        reverse=False
    )

    # Select agents within budget
    selected = {}
    remaining_budget = budget

    # Always try to include essential agents first
    essential = ["problem-framer-001", "knowledge-synthesizer-001", "insight-generator-001"]

    for agent_id in essential:
        if agent_id in eligible_agents:
            agent_data = eligible_agents[agent_id]
            if agent_data["price"] <= remaining_budget:
                selected[agent_id] = agent_data
                remaining_budget -= agent_data["price"]

    # Add more agents if budget allows
    for agent_id, agent_data in sorted_agents:
        if agent_id not in selected and agent_data["price"] <= remaining_budget:
            selected[agent_id] = agent_data
            remaining_budget -= agent_data["price"]

            if remaining_budget < 2.0:  # Min price is around 2.0
                break

    return selected

async def execute_research_agents(task_id: str, agents: Dict[str, Any], description: str) -> Dict[str, Any]:
    """
    Execute selected research agents
    """
    research_output = {}

    for agent_id, agent_data in agents.items():
        # Simulate agent execution
        await asyncio.sleep(0.5)  # Simulate processing time

        # Generate output based on agent type
        if "framer" in agent_id:
            output = {
                "problem_statement": f"Research question: {description}",
                "objectives": ["Objective 1", "Objective 2", "Objective 3"],
                "constraints": ["Time", "Budget", "Resources"]
            }
        elif "synthesizer" in agent_id:
            output = {
                "synthesis": "Knowledge synthesis of the research topic",
                "key_findings": ["Finding 1", "Finding 2"],
                "gaps": ["Gap 1", "Gap 2"]
            }
        elif "insight" in agent_id:
            output = {
                "insights": ["Key insight 1", "Key insight 2"],
                "recommendations": ["Recommendation 1", "Recommendation 2"],
                "impact": "High"
            }
        else:
            output = {
                "result": f"Output from {agent_data['name']}",
                "status": "completed"
            }

        # Simulate quality score (normally from verifier)
        import random
        quality_score = random.randint(70, 95)

        research_output[agent_id] = {
            "agent_name": agent_data["name"],
            "output": output,
            "quality_score": quality_score,
            "timestamp": datetime.utcnow().isoformat()
        }

    return research_output

async def verify_research_output(task_id: str, output: Dict[str, Any], verification_mode: str) -> Dict[str, Any]:
    """
    Verify research output quality
    """
    # Simulate verification
    await asyncio.sleep(1.0)

    verification_results = {
        "overall_quality": sum(
            agent_output.get("quality_score", 0)
            for agent_output in output.values()
        ) / len(output) if output else 0,
        "verified_at": datetime.utcnow().isoformat(),
        "mode": verification_mode,
        "agent_scores": {
            agent_id: agent_output.get("quality_score", 0)
            for agent_id, agent_output in output.items()
        }
    }

    return verification_results

@router.get("/task/{task_id}")
async def get_task_status(task_id: str):
    """
    Get task status and results
    """
    db = SessionLocal()

    try:
        task = db.query(Task).filter(Task.id == task_id).first()

        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        payments = db.query(Payment).filter(Payment.task_id == task_id).all()

        return {
            "id": task.id,
            "status": task.status,
            "description": task.description,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "result": task.result,
            "payments": [
                {
                    "agent_id": p.agent_id,
                    "amount": p.amount,
                    "status": p.status
                } for p in payments
            ]
        }

    finally:
        db.close()

@router.get("/agents")
async def list_available_agents():
    """
    List all available research agents
    """
    return {
        "agents": [
            {
                "id": agent_id,
                "name": agent_data["name"],
                "price": agent_data["price"],
                "reputation": agent_data["reputation"]
            }
            for agent_id, agent_data in RESEARCH_AGENTS.items()
        ],
        "total": len(RESEARCH_AGENTS)
    }
