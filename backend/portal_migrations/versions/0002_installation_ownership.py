"""Bind each publication to its tenant and installation, and version access policy."""

import sqlalchemy as sa

from alembic import op

revision = "0002_installation_ownership"
down_revision = "0001_result_portal"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("tenant_id", "installation_id", "policy_signature"):
        op.add_column("published_results", sa.Column(name, sa.String(64), nullable=True))
    op.add_column(
        "published_results",
        sa.Column("policy_revision", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    for name in ("policy_revision", "policy_signature", "installation_id", "tenant_id"):
        op.drop_column("published_results", name)
