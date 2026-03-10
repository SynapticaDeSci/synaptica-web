"""SQLAlchemy models for Hedera marketplace."""

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    DateTime,
    Text,
    JSON,
    ForeignKey,
    Enum,
    Boolean,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from .database import Base


class TaskStatus(str, enum.Enum):
    """Task status enum."""

    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class PaymentStatus(str, enum.Enum):
    """Payment status enum."""

    PENDING = "pending"
    AUTHORIZED = "authorized"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


class ResearchPhaseStatus(str, enum.Enum):
    """Research phase status enum."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ResearchPhaseType(str, enum.Enum):
    """Research phase type enum."""

    IDEATION = "ideation"
    KNOWLEDGE_RETRIEVAL = "knowledge_retrieval"
    EXPERIMENTATION = "experimentation"
    INTERPRETATION = "interpretation"
    PUBLICATION = "publication"


class Task(Base):
    """Task model."""

    __tablename__ = "tasks"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    status = Column(Enum(TaskStatus), default=TaskStatus.PENDING)
    created_by = Column(String)  # Agent ID
    assigned_to = Column(String, ForeignKey("agents.agent_id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    result = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)  # Renamed from metadata to avoid SQLAlchemy conflict

    # Relationships
    agent = relationship("Agent", back_populates="tasks")
    payments = relationship("Payment", back_populates="task")
    dynamic_tools = relationship("DynamicTool", back_populates="task")


class Agent(Base):
    """Agent model."""

    __tablename__ = "agents"

    agent_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    agent_type = Column(String)  # orchestrator, negotiator, executor, verifier
    description = Column(Text)
    capabilities = Column(JSON)  # List of capabilities
    hedera_account_id = Column(String, nullable=True)
    erc8004_metadata_uri = Column(String, nullable=True)
    status = Column(String, default="active")
    created_at = Column(DateTime, default=datetime.utcnow)
    meta = Column(JSON, nullable=True)  # Renamed from metadata to avoid SQLAlchemy conflict

    # Relationships
    tasks = relationship("Task", back_populates="agent")
    payments_sent = relationship(
        "Payment", foreign_keys="Payment.from_agent_id", back_populates="from_agent"
    )
    payments_received = relationship(
        "Payment", foreign_keys="Payment.to_agent_id", back_populates="to_agent"
    )


class Payment(Base):
    """Payment model."""

    __tablename__ = "payments"

    id = Column(String, primary_key=True)
    task_id = Column(String, ForeignKey("tasks.id"))
    from_agent_id = Column(String, ForeignKey("agents.agent_id"))
    to_agent_id = Column(String, ForeignKey("agents.agent_id"))
    amount = Column(Float, nullable=False)
    currency = Column(String, default="HBAR")
    status = Column(Enum(PaymentStatus), default=PaymentStatus.PENDING)
    transaction_id = Column(String, nullable=True)  # Hedera transaction ID
    authorization_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    meta = Column(JSON, nullable=True)  # Renamed from metadata to avoid SQLAlchemy conflict

    # Relationships
    task = relationship("Task", back_populates="payments")
    from_agent = relationship("Agent", foreign_keys=[from_agent_id], back_populates="payments_sent")
    to_agent = relationship(
        "Agent", foreign_keys=[to_agent_id], back_populates="payments_received"
    )


class DynamicTool(Base):
    """Dynamic tool created by executor agent."""

    __tablename__ = "dynamic_tools"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String, ForeignKey("tasks.id"))
    tool_name = Column(String, nullable=False)
    tool_description = Column(Text)
    tool_code = Column(Text, nullable=False)  # Python code
    file_path = Column(String)  # Path to generated file
    created_at = Column(DateTime, default=datetime.utcnow)
    used_count = Column(Integer, default=0)
    meta = Column(JSON, nullable=True)  # Renamed from metadata to avoid SQLAlchemy conflict

    # Relationships
    task = relationship("Task", back_populates="dynamic_tools")


class ResearchPipeline(Base):
    """Research pipeline model."""

    __tablename__ = "research_pipelines"

    id = Column(String, primary_key=True)
    query = Column(Text, nullable=False)  # Original research query
    research_topic = Column(String, nullable=False)  # Extracted topic
    budget = Column(Float, default=5.0)  # Total budget in HBAR
    spent = Column(Float, default=0.0)  # Amount spent so far
    status = Column(Enum(ResearchPhaseStatus), default=ResearchPhaseStatus.PENDING)
    current_phase = Column(Enum(ResearchPhaseType), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    meta = Column(JSON, nullable=True)  # Additional pipeline metadata (renamed to avoid conflict)

    # Relationships
    phases = relationship("ResearchPhase", back_populates="pipeline", cascade="all, delete-orphan")
    artifacts = relationship("ResearchArtifact", back_populates="pipeline", cascade="all, delete-orphan")


class ResearchPhase(Base):
    """Research phase model."""

    __tablename__ = "research_phases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pipeline_id = Column(String, ForeignKey("research_pipelines.id"))
    phase_type = Column(Enum(ResearchPhaseType), nullable=False)
    status = Column(Enum(ResearchPhaseStatus), default=ResearchPhaseStatus.PENDING)
    agents_used = Column(JSON)  # List of agent IDs used in this phase
    total_cost = Column(Float, default=0.0)  # Total cost for this phase
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    outputs = Column(JSON, nullable=True)  # Phase outputs/results
    meta = Column(JSON, nullable=True)  # Renamed from metadata to avoid SQLAlchemy conflict

    # Relationships
    pipeline = relationship("ResearchPipeline", back_populates="phases")


class ResearchArtifact(Base):
    """Research artifact model (papers, experiments, reports)."""

    __tablename__ = "research_artifacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pipeline_id = Column(String, ForeignKey("research_pipelines.id"))
    artifact_type = Column(String, nullable=False)  # paper, experiment, report, hypothesis
    name = Column(String, nullable=False)
    description = Column(Text)
    content = Column(JSON)  # Structured content
    file_path = Column(String, nullable=True)  # Path to file if stored locally
    ipfs_hash = Column(String, nullable=True)  # IPFS hash if stored on IPFS
    created_by = Column(String, ForeignKey("agents.agent_id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    meta = Column(JSON, nullable=True)  # Renamed from metadata to avoid SQLAlchemy conflict

    # Relationships
    pipeline = relationship("ResearchPipeline", back_populates="artifacts")
    creator_agent = relationship("Agent", foreign_keys=[created_by])


class DataAsset(Base):
    """Uploaded dataset managed by the built-in Data Agent."""

    __tablename__ = "data_assets"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    lab_name = Column(String, nullable=False)
    uploader_name = Column(String, nullable=True)
    data_classification = Column(String, nullable=False)  # failed, underused
    tags = Column(JSON, nullable=False)
    intended_visibility = Column(String, default="private")
    filename = Column(String, nullable=False)
    stored_path = Column(String, nullable=False)
    content_type = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    meta = Column(JSON, nullable=True)


class AgentReputation(Base):
    """Agent reputation tracking model."""

    __tablename__ = "agent_reputations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String, ForeignKey("agents.agent_id"))
    total_tasks = Column(Integer, default=0)
    successful_tasks = Column(Integer, default=0)
    failed_tasks = Column(Integer, default=0)
    average_quality_score = Column(Float, default=0.0)  # 0-1 scale
    reputation_score = Column(Float, default=0.5)  # 0-1 scale, starts at 0.5
    payment_multiplier = Column(Float, default=1.0)  # Based on reputation
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    meta = Column(JSON, nullable=True)  # Historical scores, feedback, etc. (renamed to avoid conflict)

    # Relationships
    agent = relationship("Agent", foreign_keys=[agent_id])


class A2AEvent(Base):
    """Persisted A2A messages for auditing and dashboards."""

    __tablename__ = "a2a_events"
    __table_args__ = (UniqueConstraint("message_id", name="uq_a2a_events_message_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(String, nullable=False)
    protocol = Column(String, nullable=False)
    message_type = Column(String, nullable=False)
    from_agent = Column(String, nullable=False)
    to_agent = Column(String, nullable=False)
    thread_id = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    tags = Column(JSON, nullable=True)
    body = Column(JSON, nullable=False)


class AgentRegistrySyncState(Base):
    """Track the most recent registry sync attempt."""

    __tablename__ = "agent_registry_sync_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    status = Column(String, default="never")
    last_attempted_at = Column(DateTime, nullable=True)
    last_successful_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)


class AgentsCacheEntry(Base):
    """Persisted cache of serialized agents listing."""

    __tablename__ = "agents_cache"

    key = Column(String, primary_key=True)
    payload = Column(JSON, nullable=False)
    synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserCredits(Base):
    """Fiat-purchased credits balance per user."""

    __tablename__ = "user_credits"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False, unique=True, index=True)
    credits = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StripeTransaction(Base):
    """Record of each Stripe checkout session for credits."""

    __tablename__ = "stripe_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False)
    stripe_session_id = Column(String, nullable=False, unique=True)
    credits_purchased = Column(Integer, nullable=False)
    amount_usd_cents = Column(Integer, nullable=False)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
