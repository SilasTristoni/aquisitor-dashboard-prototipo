"""Independent result store and persistent rate limiting."""

import sqlalchemy as sa

from alembic import op

revision = "0001_result_portal"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "published_results",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("password_hash", sa.String(255)),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("signature", sa.String(64), nullable=False),
        sa.Column("access_count", sa.Integer(), nullable=False),
    )
    op.create_table(
        "portal_rate_buckets",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("window", sa.Integer(), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_table("portal_rate_buckets")
    op.drop_table("published_results")
