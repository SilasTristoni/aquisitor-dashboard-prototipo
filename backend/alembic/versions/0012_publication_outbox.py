"""Durable authorized snapshot and unique local publication request."""

import sqlalchemy as sa

from alembic import op

revision = "0012_publication_outbox"
down_revision = "0011_share_result_options"
branch_labels = None
depends_on = None


def upgrade():
    # Initial legacy migrations may create the current metadata on a fresh install.
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("session_shares")}
    if "mutation_version" not in columns:
        op.add_column(
            "session_shares",
            sa.Column("mutation_version", sa.Integer(), nullable=False, server_default="0"),
        )
    if "publication_id" not in columns:
        op.add_column("session_shares", sa.Column("publication_id", sa.String(36), nullable=True))
        op.create_index(
            "uq_session_share_publication", "session_shares", ["publication_id"], unique=True
        )
    for name, kind in [
        ("publication_payload", sa.LargeBinary()),
        ("publication_input_hash", sa.String(64)),
    ]:
        if name not in columns:
            op.add_column("session_shares", sa.Column(name, kind, nullable=True))


def downgrade():
    op.drop_column("session_shares", "mutation_version")
    op.drop_column("session_shares", "publication_input_hash")
    op.drop_column("session_shares", "publication_payload")
    op.drop_index("uq_session_share_publication", table_name="session_shares")
    op.drop_column("session_shares", "publication_id")
