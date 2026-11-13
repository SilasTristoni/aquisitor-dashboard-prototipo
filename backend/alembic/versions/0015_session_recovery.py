"""Persistent process identity and interrupted session decisions."""

import sqlalchemy as sa

from alembic import op

revision = "0015_session_recovery"
down_revision = "0014_source_availability"
branch_labels = None
depends_on = None


def upgrade():
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "application_instances" not in tables:
        op.create_table(
            "application_instances",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("stopped_at", sa.DateTime(timezone=True)),
            sa.Column("state", sa.String(24), nullable=False),
        )
    if "session_recovery" not in tables:
        op.create_table(
            "session_recovery",
            sa.Column(
                "session_id",
                sa.Integer(),
                sa.ForeignKey("measurement_sessions.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("instance_id", sa.String(36), sa.ForeignKey("application_instances.id")),
            sa.Column("state", sa.String(24), nullable=False),
            sa.Column("reason", sa.String(40)),
            sa.Column("detected_at", sa.DateTime(timezone=True)),
            sa.Column("checkpoint_at", sa.DateTime(timezone=True)),
            sa.Column("last_sample_at", sa.DateTime(timezone=True)),
            sa.Column("decision_at", sa.DateTime(timezone=True)),
        )
        op.create_index("ix_session_recovery_state", "session_recovery", ["state"])


def downgrade():
    op.drop_table("session_recovery")
    op.drop_table("application_instances")
