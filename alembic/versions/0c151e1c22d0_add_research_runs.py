"""add_research_runs

Revision ID: 0c151e1c22d0
Revises: 0bdf6fb7e49d
Create Date: 2026-03-09 16:17:58.842958

"""

from typing import Sequence, Union

from alembic import op

from shared.database import Base


# revision identifiers, used by Alembic.
revision: str = '0c151e1c22d0'
down_revision: Union[str, Sequence[str], None] = '0bdf6fb7e49d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RESEARCH_RUN_TABLES = {
    "research_runs",
    "research_run_nodes",
    "research_run_edges",
    "execution_attempts",
}


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    for table in Base.metadata.sorted_tables:
        if table.name in _RESEARCH_RUN_TABLES:
            table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    for table in reversed(Base.metadata.sorted_tables):
        if table.name in _RESEARCH_RUN_TABLES:
            table.drop(bind=bind, checkfirst=True)
