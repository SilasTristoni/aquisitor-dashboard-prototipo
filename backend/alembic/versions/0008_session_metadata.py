"""Add optional client-facing metadata to measurement sessions.

Revision ID: 0008_session_metadata
Revises: 0007_at4532_duplicate_neutralization
"""

import sqlalchemy as sa

from alembic import op

revision = "0008_session_metadata"
down_revision = "0007_at4532_duplicate_neutralization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("measurement_sessions")}
    if "metadata" not in columns:
        op.add_column(
            "measurement_sessions",
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )
    op.execute(sa.text("UPDATE measurement_sessions SET metadata = '{}' WHERE metadata IS NULL"))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("measurement_sessions")}
    if "metadata" in columns:
        op.drop_column("measurement_sessions", "metadata")
