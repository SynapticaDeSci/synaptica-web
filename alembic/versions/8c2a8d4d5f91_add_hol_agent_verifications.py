"""add_hol_agent_verifications

Revision ID: 8c2a8d4d5f91
Revises: 6f3debf3d3c1
Create Date: 2026-03-23 23:10:00.000000

"""

from typing import Sequence, Union

from alembic import op

from shared.database import Base


# revision identifiers, used by Alembic.
revision: str = "8c2a8d4d5f91"
down_revision: Union[str, Sequence[str], None] = "6f3debf3d3c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_HOL_AGENT_VERIFICATION_TABLES = {
    "hol_agent_verifications",
}


def upgrade() -> None:
    """Upgrade schema."""

    bind = op.get_bind()
    for table in Base.metadata.sorted_tables:
        if table.name in _HOL_AGENT_VERIFICATION_TABLES:
            table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    """Downgrade schema."""

    bind = op.get_bind()
    for table in reversed(Base.metadata.sorted_tables):
        if table.name in _HOL_AGENT_VERIFICATION_TABLES:
            table.drop(bind=bind, checkfirst=True)
