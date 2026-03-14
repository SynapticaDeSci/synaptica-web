"""add_phase2_evidence_graph_tables

Revision ID: 4b1e7d5a6c2f
Revises: 0d4a7b9c3f11
Create Date: 2026-03-10 13:05:00.000000

"""

from typing import Sequence, Union

from alembic import op

from shared.database import Base


# revision identifiers, used by Alembic.
revision: str = "4b1e7d5a6c2f"
down_revision: Union[str, Sequence[str], None] = "0d4a7b9c3f11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PHASE2_GRAPH_TABLES = {
    "evidence_artifacts",
    "claims",
    "claim_links",
}


def upgrade() -> None:
    """Upgrade schema."""

    bind = op.get_bind()
    for table in Base.metadata.sorted_tables:
        if table.name in _PHASE2_GRAPH_TABLES:
            table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    """Downgrade schema."""

    bind = op.get_bind()
    for table in reversed(Base.metadata.sorted_tables):
        if table.name in _PHASE2_GRAPH_TABLES:
            table.drop(bind=bind, checkfirst=True)
