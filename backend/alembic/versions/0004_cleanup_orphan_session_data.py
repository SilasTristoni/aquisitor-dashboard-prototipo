"""Remove orphan session data left by SQLite with foreign keys disabled."""

import sqlalchemy as sa

from alembic import op

revision = "0004_cleanup_orphan_session_data"
down_revision = "0003_period_reports"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _delete_missing_parent(
    child_table: str, foreign_key: str, parent_table: str
) -> None:
    if not _has_table(child_table) or not _has_table(parent_table):
        return
    op.execute(
        sa.text(
            f"DELETE FROM {child_table} "
            f"WHERE NOT EXISTS (SELECT 1 FROM {parent_table} "
            f"WHERE {parent_table}.id = {child_table}.{foreign_key})"
        )
    )


def _clear_missing_session_reference(table: str) -> None:
    if not _has_table(table) or not _has_table("measurement_sessions"):
        return
    op.execute(
        sa.text(
            f"UPDATE {table} SET session_id = NULL "
            "WHERE session_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM measurement_sessions "
            f"WHERE measurement_sessions.id = {table}.session_id)"
        )
    )


def upgrade() -> None:
    session_children = [
        "measurements",
        "temperature_samples",
        "electrical_samples",
        "alert_events",
        "session_channel_configurations",
        "session_devices",
    ]
    for table in session_children:
        _delete_missing_parent(table, "session_id", "measurement_sessions")

    _delete_missing_parent("temperature_measurements", "measurement_id", "measurements")
    _delete_missing_parent(
        "temperature_channel_values", "sample_id", "temperature_samples"
    )
    _clear_missing_session_reference("system_events")
    _clear_missing_session_reference("reports")


def downgrade() -> None:
    # Orphan rows cannot be restored safely.
    pass
