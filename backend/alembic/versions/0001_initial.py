"""Initial production schema."""

from alembic import op
from app.core.database import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    legacy_names = {
        "users",
        "devices",
        "measurement_sessions",
        "measurements",
        "temperature_measurements",
        "channel_configurations",
        "alert_rules",
        "alert_events",
        "system_events",
        "reports",
    }
    Base.metadata.create_all(
        bind=bind,
        tables=[table for name, table in Base.metadata.tables.items() if name in legacy_names],
    )


def downgrade() -> None:
    bind = op.get_bind()
    legacy_names = {
        "users",
        "devices",
        "measurement_sessions",
        "measurements",
        "temperature_measurements",
        "channel_configurations",
        "alert_rules",
        "alert_events",
        "system_events",
        "reports",
    }
    Base.metadata.drop_all(
        bind=bind,
        tables=[table for name, table in Base.metadata.tables.items() if name in legacy_names],
    )
