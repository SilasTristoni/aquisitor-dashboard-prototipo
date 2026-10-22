"""Installation identity; measurement tables remain unchanged."""

import sqlalchemy as sa

from alembic import op

revision = "0013_company_identity"
down_revision = "0012_publication_outbox"
branch_labels = None
depends_on = None


def upgrade():
    if "company_identity" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "company_identity",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("identity_id", sa.String(36), nullable=False),
            sa.Column("company_name", sa.String(120), nullable=False),
            sa.Column("laboratory", sa.String(120), nullable=False),
            sa.Column("logo", sa.LargeBinary(), nullable=True),
        )


def downgrade():
    op.drop_table("company_identity")
