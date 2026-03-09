"""add_payment_integrity_tables

Revision ID: 0d4a7b9c3f11
Revises: 0c151e1c22d0
Create Date: 2026-03-09 22:05:00.000000

"""

from typing import Sequence, Union

from alembic import op

from shared.database import Base


# revision identifiers, used by Alembic.
revision: str = "0d4a7b9c3f11"
down_revision: Union[str, Sequence[str], None] = "0c151e1c22d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PAYMENT_INTEGRITY_TABLES = {
    "agent_payment_profiles",
    "payment_notifications",
    "payment_reconciliations",
}


def upgrade() -> None:
    """Upgrade schema."""

    bind = op.get_bind()
    for table in Base.metadata.sorted_tables:
        if table.name in _PAYMENT_INTEGRITY_TABLES:
            table.create(bind=bind, checkfirst=False)


def downgrade() -> None:
    """Downgrade schema."""

    bind = op.get_bind()
    for table in reversed(Base.metadata.sorted_tables):
        if table.name in _PAYMENT_INTEGRITY_TABLES:
            table.drop(bind=bind, checkfirst=True)
