"""Allow unknown physical serial parameters without inventing a baud rate.

Revision ID: 0005_nullable_physical_baud_rate
Revises: 0004_cleanup_orphan_session_data
"""

import sqlalchemy as sa

from alembic import op

revision = "0005_nullable_physical_baud_rate"
down_revision = "0004_cleanup_orphan_session_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("devices") as batch:
        batch.alter_column(
            "baud_rate", existing_type=sa.Integer(), nullable=True, existing_nullable=False
        )


def downgrade() -> None:
    op.execute("UPDATE devices SET baud_rate = 115200 WHERE baud_rate IS NULL")
    with op.batch_alter_table("devices") as batch:
        batch.alter_column(
            "baud_rate", existing_type=sa.Integer(), nullable=False, existing_nullable=True
        )
