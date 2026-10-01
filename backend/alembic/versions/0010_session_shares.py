"""Read-only session sharing with hashed credentials."""

import sqlalchemy as sa

from alembic import op

revision = "0010_session_shares"
down_revision = "0009_session_analysis"
branch_labels = None
depends_on = None


def upgrade():
    if "session_shares" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "session_shares",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("measurement_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("token_nonce", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(255)),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("access_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_session_shares_session_id", "session_shares", ["session_id"])


def downgrade():
    op.drop_table("session_shares")
