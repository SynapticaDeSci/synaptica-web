"""add_research_run_trace_tables

Revision ID: 6f3debf3d3c1
Revises: 4b1e7d5a6c2f
Create Date: 2026-03-15 20:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

from shared.database import Base


# revision identifiers, used by Alembic.
revision: str = "6f3debf3d3c1"
down_revision: Union[str, Sequence[str], None] = "4b1e7d5a6c2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RESEARCH_RUN_TRACE_TABLES = {
    "verification_decisions",
    "swarm_handoffs",
    "policy_evaluations",
}


def upgrade() -> None:
    """Upgrade schema."""

    bind = op.get_bind()
    for table in Base.metadata.sorted_tables:
        if table.name in _RESEARCH_RUN_TRACE_TABLES:
            table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    """Downgrade schema."""

    bind = op.get_bind()
    for table in reversed(Base.metadata.sorted_tables):
        if table.name in _RESEARCH_RUN_TRACE_TABLES:
            table.drop(bind=bind, checkfirst=True)
