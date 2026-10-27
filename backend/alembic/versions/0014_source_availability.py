"""Confirmed source unavailability; never backfill from missing samples."""

import sqlalchemy as sa

from alembic import op

revision = "0014_source_availability"
down_revision = "0013_company_identity"
branch_labels = None
depends_on = None


def upgrade():
    if "source_availability" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "source_availability",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "session_id",
                sa.Integer(),
                sa.ForeignKey("measurement_sessions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "device_id",
                sa.Integer(),
                sa.ForeignKey("devices.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("confirmed_until", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("end_reason", sa.String(24), nullable=True),
            sa.Column("cause", sa.String(40), nullable=False),
        )
        op.create_index(
            "ix_source_availability_session_start",
            "source_availability",
            ["session_id", "started_at"],
        )


def downgrade():
    op.drop_table("source_availability")
