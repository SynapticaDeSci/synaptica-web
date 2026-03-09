"""Base class for all research agents."""

import os
import re
from typing import Dict, Any, List, Optional
from abc import ABC, abstractmethod
from shared.strands_openai_agent import AsyncStrandsAgent, create_strands_openai_agent
from shared.database import SessionLocal, Agent as AgentModel, AgentReputation
from datetime import datetime
from shared.research.catalog import default_research_endpoint, infer_support_tier


class BaseResearchAgent(ABC):
    """
    Base class for all research agents in the pipeline.

    This class provides common functionality for:
    - Agent registration in ERC-8004
    - Strands SDK agent creation
    - Reputation tracking
    - Payment handling
    - Output validation
    """

    def __init__(
        self,
        agent_id: str,
        name: str,
        description: str,
        capabilities: List[str],
        pricing: Dict[str, Any],
        model: str = "gpt-5.4",
    ):
        """
        Initialize base research agent.

        Args:
            agent_id: Unique agent identifier
            name: Human-readable agent name
            description: Agent description
            capabilities: List of capabilities for ERC-8004 discovery
            pricing: Pricing model (e.g., {"model": "pay-per-use", "rate": "0.1 HBAR"})
            model: OpenAI model to use
        """
        self.agent_id = agent_id
        self.name = name
        self.description = description
        self.capabilities = capabilities
        self.pricing = pricing
        self.model = model

        # Check for OpenAI API key
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set in environment")

        # No need to create client here, will be created in create_agent()

        # Initialize agent (will be created in create_agent)
        self.agent: Optional[AsyncStrandsAgent] = None

        # Register agent in database
        self._register_in_database()

    def _register_in_database(self):
        """Register agent in database if not already registered."""
        # Skip registration if tables don't exist yet (will be called later)
        from sqlalchemy import inspect
        db = SessionLocal()
        try:
            # Check if tables exist
            inspector = inspect(db.bind)
            if 'agents' not in inspector.get_table_names():
                print(f"Skipping registration for {self.agent_id} - database not initialized yet")
                return

            default_endpoint = default_research_endpoint(self.agent_id)
            normalized_pricing = self._normalize_pricing()
            support_tier = infer_support_tier(self.agent_id, "research").value
            # Check if agent exists
            existing = db.query(AgentModel).filter(AgentModel.agent_id == self.agent_id).first()

            if not existing:
                # Create new agent record
                agent_record = AgentModel(
                    agent_id=self.agent_id,
                    name=self.name,
                    agent_type="research",
                    description=self.description,
                    capabilities=self.capabilities,
                    status="active",
                    meta={
                        "pricing": normalized_pricing,
                        "model": self.model,
                        "created_at": datetime.utcnow().isoformat(),
                        "endpoint_url": default_endpoint,
                        "support_tier": support_tier,
                    }
                )
                db.add(agent_record)

                # Create reputation record
                reputation = AgentReputation(
                    agent_id=self.agent_id,
                    reputation_score=0.5,  # Start at neutral
                    payment_multiplier=1.0,
                )
                db.add(reputation)

                db.commit()
                print(f"Registered agent {self.agent_id} in database")
            else:
                meta = existing.meta or {}
                updated = False
                if meta.get("endpoint_url") != default_endpoint:
                    meta["endpoint_url"] = default_endpoint
                    updated = True

                current_pricing = meta.get("pricing")
                if meta.get("support_tier") != support_tier:
                    meta["support_tier"] = support_tier
                    updated = True
                if not isinstance(current_pricing, dict):
                    meta["pricing"] = normalized_pricing
                    updated = True
                else:
                    reconciled = self._merge_pricing(current_pricing, normalized_pricing)
                    if reconciled != current_pricing:
                        meta["pricing"] = reconciled
                        updated = True

                if updated:
                    existing.meta = meta
                    db.commit()

                print(f"Agent {self.agent_id} already registered")

        finally:
            db.close()

    def _normalize_pricing(self) -> Dict[str, Any]:
        """Convert the agent's pricing definition into a normalized structure."""
        pricing = self.pricing or {}
        rate_raw = pricing.get("rate")
        currency = pricing.get("currency")

        if isinstance(rate_raw, str):
            match = re.search(r"([0-9]*\.?[0-9]+)", rate_raw)
            if match:
                rate_value = float(match.group(1))
            else:
                rate_value = 0.0
            if not currency:
                parts = rate_raw.replace(match.group(1), "").strip().split() if match else rate_raw.split()
                if parts:
                    currency = parts[0]
        elif isinstance(rate_raw, (int, float)):
            rate_value = float(rate_raw)
        else:
            rate_value = 0.0

        currency = currency or "HBAR"
        rate_type = (
            pricing.get("rate_type")
            or pricing.get("rateType")
            or pricing.get("unit")
            or "per_task"
        )

        return {
            "rate": rate_value,
            "currency": currency,
            "rate_type": rate_type,
        }

    @staticmethod
    def _merge_pricing(existing: Dict[str, Any], normalized: Dict[str, Any]) -> Dict[str, Any]:
        """Merge existing pricing metadata with normalized values, preferring numeric fields."""
        merged = dict(existing or {})
        for key, value in normalized.items():
            current = merged.get(key)
            if key == "rate":
                if not isinstance(current, (int, float)) or current != value:
                    merged[key] = value
            elif not current:
                merged[key] = value
        return merged

    @abstractmethod
    def get_system_prompt(self) -> str:
        """
        Get the system prompt for this agent.

        Returns:
            System prompt string
        """
        pass

    @abstractmethod
    def get_tools(self) -> List:
        """
        Get the tools for this agent.

        Returns:
            List of tool functions
        """
        pass

    def create_agent(self) -> AsyncStrandsAgent:
        """
        Create OpenAI agent instance.

        Returns:
            Configured Agent instance
        """
        self.agent = create_strands_openai_agent(
            system_prompt=self.get_system_prompt(),
            tools=self.get_tools(),
            model=self.model,
            agent_id=self.agent_id,
            name=self.name,
            description=self.description,
        )
        return self.agent

    async def execute(self, request: str, **kwargs) -> Dict[str, Any]:
        """
        Execute agent with request.

        Args:
            request: Request string for the agent
            **kwargs: Additional parameters (json_mode, max_tokens, etc.)

        Returns:
            Agent response as dictionary
        """
        agent = self.agent
        if self.agent is None:
            agent = self.create_agent()

        try:
            result = await agent.run(request)

            # Update success metrics
            self._update_reputation(success=True, quality_score=0.8)

            return {
                "success": True,
                "agent_id": self.agent_id,
                "result": result,
                "metadata": {
                    "timestamp": datetime.utcnow().isoformat(),
                    "model": self.model,
                }
            }

        except Exception as e:
            # Update failure metrics
            self._update_reputation(success=False, quality_score=0.0)

            return {
                "success": False,
                "agent_id": self.agent_id,
                "error": str(e),
                "metadata": {
                    "timestamp": datetime.utcnow().isoformat(),
                    "model": self.model,
                }
            }

    def _update_reputation(self, success: bool, quality_score: float):
        """
        Update agent reputation based on task outcome.

        Args:
            success: Whether task was successful
            quality_score: Quality score (0-1)
        """
        db = SessionLocal()
        try:
            reputation = db.query(AgentReputation).filter(
                AgentReputation.agent_id == self.agent_id
            ).first()

            if reputation:
                reputation.total_tasks += 1
                if success:
                    reputation.successful_tasks += 1
                else:
                    reputation.failed_tasks += 1

                # Update average quality score
                reputation.average_quality_score = (
                    (reputation.average_quality_score * (reputation.total_tasks - 1) + quality_score)
                    / reputation.total_tasks
                )

                # Calculate new reputation score (simple formula)
                if reputation.total_tasks > 0:
                    success_rate = reputation.successful_tasks / reputation.total_tasks
                    reputation.reputation_score = (
                        0.6 * success_rate + 0.4 * reputation.average_quality_score
                    )

                    # Update payment multiplier based on reputation
                    if reputation.reputation_score >= 0.8:
                        reputation.payment_multiplier = 1.2  # 20% bonus
                    elif reputation.reputation_score >= 0.6:
                        reputation.payment_multiplier = 1.0  # Normal rate
                    elif reputation.reputation_score >= 0.4:
                        reputation.payment_multiplier = 0.9  # 10% penalty
                    else:
                        reputation.payment_multiplier = 0.8  # 20% penalty

                db.commit()

        finally:
            db.close()

    def get_metadata(self) -> Dict[str, Any]:
        """
        Get agent metadata for ERC-8004 registration.

        Returns:
            Agent metadata dictionary
        """
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "description": self.description,
            "capabilities": self.capabilities,
            "pricing": self.pricing,
            "api_spec": self.get_api_spec(),
            "owner": os.getenv("HEDERA_ACCOUNT_ID", "0.0.0"),
            "verified": False,  # Will be verified after testing
            "reputation_score": self.get_reputation_score(),
        }

    def get_api_spec(self) -> Dict[str, Any]:
        """
        Get API specification for this agent.

        This is used by the Executor to create dynamic tools.

        Returns:
            API specification dictionary
        """
        # Default spec - override in subclasses for custom endpoints
        return {
            "endpoint": f"https://research-agents.hedera.ai/api/{self.agent_id}",
            "method": "POST",
            "parameters": [
                {"name": "request", "type": "str", "description": "Request for the agent"},
                {"name": "context", "type": "dict", "description": "Additional context"},
            ],
            "response_schema": {
                "success": "bool",
                "result": "any",
                "error": "str",
            },
            "auth_type": "bearer",
            "description": self.description,
        }

    def get_reputation_score(self) -> float:
        """
        Get current reputation score from database.

        Returns:
            Reputation score (0-1)
        """
        db = SessionLocal()
        try:
            reputation = db.query(AgentReputation).filter(
                AgentReputation.agent_id == self.agent_id
            ).first()

            if reputation:
                return reputation.reputation_score
            return 0.5  # Default neutral score

        finally:
            db.close()

    def get_payment_rate(self) -> float:
        """
        Get current payment rate including reputation multiplier.

        Returns:
            Adjusted payment rate in HBAR
        """
        base_rate = float(self.pricing.get("rate", "0.1").replace(" HBAR", ""))

        db = SessionLocal()
        try:
            reputation = db.query(AgentReputation).filter(
                AgentReputation.agent_id == self.agent_id
            ).first()

            if reputation:
                return base_rate * reputation.payment_multiplier
            return base_rate

        finally:
            db.close()

    def validate_output(self, output: Any) -> tuple[bool, Optional[str]]:
        """
        Validate agent output.

        Override this in subclasses to provide specific validation.

        Args:
            output: Agent output to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Default validation - just check output exists
        if not output:
            return False, "Empty output"
        return True, None

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.agent_id}: {self.name}>"
