"""baseline_schema

Revision ID: 0bdf6fb7e49d
Revises:
Create Date: 2026-03-09 16:17:58.654460

"""

from typing import Sequence, Union

from alembic import op

from shared.database import Base


# revision identifiers, used by Alembic.
revision: str = '0bdf6fb7e49d'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BASELINE_TABLES = {
    "tasks",
    "agents",
    "payments",
    "payment_state_transitions",
    "dynamic_tools",
    "research_pipelines",
    "research_phases",
    "research_artifacts",
    "data_assets",
    "agent_reputations",
    "a2a_events",
    "agent_registry_sync_state",
    "agents_cache",
}


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    for table in Base.metadata.sorted_tables:
        if table.name in _BASELINE_TABLES:
            table.create(bind=bind, checkfirst=False)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    for table in reversed(Base.metadata.sorted_tables):
        if table.name in _BASELINE_TABLES:
            table.drop(bind=bind, checkfirst=True)
