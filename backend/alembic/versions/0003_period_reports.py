"""Add auditable reports spanning multiple sessions and timestamps."""

import sqlalchemy as sa

from alembic import op

revision = "0003_period_reports"
down_revision = "0002_dual_device_integration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("reports")}
    additions = [
        (
            "scope_type",
            sa.Column(
                "scope_type", sa.String(16), nullable=False, server_default="session"
            ),
        ),
        ("period_start", sa.Column("period_start", sa.DateTime(timezone=True))),
        ("period_end", sa.Column("period_end", sa.DateTime(timezone=True))),
        ("timezone", sa.Column("timezone", sa.String(64))),
        ("title", sa.Column("title", sa.String(180))),
        ("filters_json", sa.Column("filters_json", sa.JSON(), nullable=False, server_default="{}")),
        ("status", sa.Column("status", sa.String(20), nullable=False, server_default="completed")),
        ("error_message", sa.Column("error_message", sa.Text())),
    ]
    for name, column in additions:
        if name not in columns:
            op.add_column("reports", column)

    op.execute(sa.text("UPDATE reports SET scope_type = 'session' WHERE scope_type IS NULL"))
    op.execute(sa.text("UPDATE reports SET status = 'completed' WHERE status IS NULL"))
    op.execute(sa.text("UPDATE reports SET filters_json = '{}' WHERE filters_json IS NULL"))
    with op.batch_alter_table("reports") as batch_op:
        batch_op.alter_column("session_id", existing_type=sa.Integer(), nullable=True)

    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("reports")}
    if "ix_reports_scope_type" not in indexes:
        op.create_index("ix_reports_scope_type", "reports", ["scope_type"])
    if "ix_reports_status" not in indexes:
        op.create_index("ix_reports_status", "reports", ["status"])


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM reports WHERE session_id IS NULL"))
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("reports")}
    if "ix_reports_status" in indexes:
        op.drop_index("ix_reports_status", table_name="reports")
    if "ix_reports_scope_type" in indexes:
        op.drop_index("ix_reports_scope_type", table_name="reports")
    with op.batch_alter_table("reports") as batch_op:
        batch_op.alter_column("session_id", existing_type=sa.Integer(), nullable=False)
    for name in [
        "error_message",
        "status",
        "filters_json",
        "title",
        "timezone",
        "period_end",
        "period_start",
        "scope_type",
    ]:
        op.drop_column("reports", name)
