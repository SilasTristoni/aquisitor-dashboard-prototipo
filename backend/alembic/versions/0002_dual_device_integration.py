"""Add independent AT4532 and GPM-8213 streams without removing legacy data."""

from collections import defaultdict
from typing import Any

import sqlalchemy as sa

from alembic import op

revision = "0002_dual_device_integration"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _create_table_if_missing(name: str, *columns: Any) -> None:
    """Support databases previously initialized by ``Base.metadata.create_all``."""
    if name not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(name, *columns)


def _create_index_if_missing(name: str, table: str, columns: list[str]) -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {index["name"] for index in inspector.get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns)


def _row_exists(bind: sa.Connection, table: sa.Table, *conditions: Any) -> bool:
    return bool(bind.scalar(sa.select(sa.func.count()).select_from(table).where(*conditions)))


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    session_columns = {column["name"] for column in inspector.get_columns("measurement_sessions")}
    channel_columns = {column["name"] for column in inspector.get_columns("channel_configurations")}
    if "acquisition_mode" not in session_columns:
        op.add_column(
            "measurement_sessions",
            sa.Column("acquisition_mode", sa.String(24), nullable=False, server_default="live"),
        )
    if "sync_grid_ms" not in session_columns:
        op.add_column(
            "measurement_sessions",
            sa.Column("sync_grid_ms", sa.Integer(), nullable=False, server_default="1000"),
        )
    if "sync_tolerance_ms" not in session_columns:
        op.add_column(
            "measurement_sessions",
            sa.Column("sync_tolerance_ms", sa.Integer(), nullable=False, server_default="1500"),
        )
    if "display_order" not in channel_columns:
        op.add_column(
            "channel_configurations",
            sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        )

    _create_table_if_missing(
        "session_devices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("measurement_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "role", name="uq_session_devices_session_role"),
        sa.UniqueConstraint("session_id", "device_id", "role", name="uq_session_devices_mapping"),
    )
    _create_index_if_missing("ix_session_devices_session_id", "session_devices", ["session_id"])
    _create_index_if_missing("ix_session_devices_device_id", "session_devices", ["device_id"])

    _create_table_if_missing(
        "temperature_samples",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("measurement_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("device_timestamp", sa.DateTime(timezone=True)),
        sa.Column("received_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ambient_temperature_c", sa.Float()),
        sa.Column("quality", sa.String(24), nullable=False, server_default="good"),
        sa.Column("source", sa.String(24), nullable=False, server_default="live"),
        sa.Column("source_row", sa.Integer()),
        sa.Column("sequence", sa.Integer()),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_index_if_missing(
        "ix_temperature_samples_session_id", "temperature_samples", ["session_id"]
    )
    _create_index_if_missing(
        "ix_temperature_samples_device_id", "temperature_samples", ["device_id"]
    )
    _create_index_if_missing(
        "ix_temperature_samples_received_timestamp", "temperature_samples", ["received_timestamp"]
    )
    _create_index_if_missing(
        "ix_temperature_samples_session_time",
        "temperature_samples",
        ["session_id", "received_timestamp"],
    )

    _create_table_if_missing(
        "temperature_channel_values",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "sample_id",
            sa.Integer(),
            sa.ForeignKey("temperature_samples.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.Integer(), nullable=False),
        sa.Column("temperature_c", sa.Float()),
        sa.Column("original_value", sa.Float()),
        sa.Column("original_unit", sa.String(12), nullable=False, server_default="°C"),
        sa.Column("quality", sa.String(24), nullable=False, server_default="good"),
        sa.UniqueConstraint("sample_id", "channel", name="uq_temperature_sample_channel"),
    )
    _create_index_if_missing(
        "ix_temperature_channel_values_sample_id", "temperature_channel_values", ["sample_id"]
    )
    _create_index_if_missing(
        "ix_temperature_channel_values_channel", "temperature_channel_values", ["channel"]
    )

    _create_table_if_missing(
        "electrical_samples",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("measurement_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("device_timestamp", sa.DateTime(timezone=True)),
        sa.Column("received_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("voltage_v", sa.Float()),
        sa.Column("current_a", sa.Float()),
        sa.Column("active_power_w", sa.Float()),
        sa.Column("apparent_power_va", sa.Float()),
        sa.Column("reactive_power_var", sa.Float()),
        sa.Column("power_factor", sa.Float()),
        sa.Column("voltage_frequency_hz", sa.Float()),
        sa.Column("current_frequency_hz", sa.Float()),
        sa.Column("original_values", sa.JSON(), nullable=False),
        sa.Column("original_units", sa.JSON(), nullable=False),
        sa.Column("quality", sa.String(24), nullable=False, server_default="good"),
        sa.Column("source", sa.String(24), nullable=False, server_default="live"),
        sa.Column("source_row", sa.Integer()),
        sa.Column("sequence", sa.Integer()),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_index_if_missing(
        "ix_electrical_samples_session_id", "electrical_samples", ["session_id"]
    )
    _create_index_if_missing("ix_electrical_samples_device_id", "electrical_samples", ["device_id"])
    _create_index_if_missing(
        "ix_electrical_samples_received_timestamp", "electrical_samples", ["received_timestamp"]
    )
    _create_index_if_missing(
        "ix_electrical_samples_session_time",
        "electrical_samples",
        ["session_id", "received_timestamp"],
    )

    _create_table_if_missing(
        "session_channel_configurations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("measurement_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_configuration_id",
            sa.Integer(),
            sa.ForeignKey("channel_configurations.id", ondelete="SET NULL"),
        ),
        sa.Column("channel", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("sensor_type", sa.String(20), nullable=False),
        sa.Column("unit", sa.String(12), nullable=False),
        sa.Column("correction_offset", sa.Float(), nullable=False),
        sa.Column("warning_limit", sa.Float()),
        sa.Column("critical_limit", sa.Float()),
        sa.Column("color", sa.String(10), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("physical_location", sa.String(160)),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.UniqueConstraint("session_id", "channel", name="uq_session_channel_snapshot"),
    )
    _create_index_if_missing(
        "ix_session_channel_configurations_session_id",
        "session_channel_configurations",
        ["session_id"],
    )

    _create_table_if_missing(
        "channel_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("description", sa.Text()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_table_if_missing(
        "channel_profile_values",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("channel_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.Integer(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.UniqueConstraint("profile_id", "channel", name="uq_profile_channel"),
    )
    _create_index_if_missing(
        "ix_channel_profile_values_profile_id", "channel_profile_values", ["profile_id"]
    )

    _backfill_existing_data()


def _backfill_existing_data() -> None:
    """Copy legacy readings; originals remain untouched for safe rollback/audit."""
    bind = op.get_bind()
    metadata = sa.MetaData()
    metadata.reflect(bind=bind)
    tables = metadata.tables
    sessions = tables["measurement_sessions"]
    session_devices = tables["session_devices"]
    measurements = tables["measurements"]
    legacy_temperatures = tables["temperature_measurements"]
    temperature_samples = tables["temperature_samples"]
    temperature_values = tables["temperature_channel_values"]
    electrical_samples = tables["electrical_samples"]
    channel_configs = tables["channel_configurations"]
    snapshots = tables["session_channel_configurations"]

    now = sa.func.now()
    session_rows = bind.execute(sa.select(sessions.c.id, sessions.c.device_id)).mappings()
    for row in session_rows:
        if not _row_exists(
            bind,
            session_devices,
            session_devices.c.session_id == row["id"],
            session_devices.c.role == "combined",
        ):
            bind.execute(
                session_devices.insert().values(
                    session_id=row["id"],
                    device_id=row["device_id"],
                    role="combined",
                    created_at=now,
                )
            )
        configs = bind.execute(
            sa.select(channel_configs).where(channel_configs.c.device_id == row["device_id"])
        ).mappings()
        for config in configs:
            if _row_exists(
                bind,
                snapshots,
                snapshots.c.session_id == row["id"],
                snapshots.c.channel == config["channel"],
            ):
                continue
            bind.execute(
                snapshots.insert().values(
                    session_id=row["id"],
                    source_configuration_id=config["id"],
                    channel=config["channel"],
                    name=config["name"],
                    enabled=config["enabled"],
                    sensor_type=config["sensor_type"],
                    unit=config["unit"],
                    correction_offset=config["correction_offset"],
                    warning_limit=config["warning_limit"],
                    critical_limit=config["critical_limit"],
                    color=config["color"],
                    description=config["description"],
                    physical_location=config["physical_location"],
                    display_order=config["display_order"] or config["channel"],
                )
            )

    device_by_session = dict(bind.execute(sa.select(sessions.c.id, sessions.c.device_id)).all())
    temperatures_by_measurement = defaultdict(list)
    for value in bind.execute(sa.select(legacy_temperatures)).mappings():
        temperatures_by_measurement[value["measurement_id"]].append(value)
    for row in bind.execute(sa.select(measurements)).mappings():
        device_id = device_by_session[row["session_id"]]
        if not _row_exists(
            bind,
            electrical_samples,
            electrical_samples.c.session_id == row["session_id"],
            electrical_samples.c.received_timestamp == row["timestamp"],
            electrical_samples.c.source == "legacy",
        ):
            bind.execute(
                electrical_samples.insert().values(
                    session_id=row["session_id"],
                    device_id=device_id,
                    device_timestamp=row["timestamp"],
                    received_timestamp=row["timestamp"],
                    active_power_w=row["power_w"],
                    original_values={"active_power": row["raw_power"]},
                    original_units={"active_power": row["raw_power_unit"]},
                    quality=row["quality"],
                    source="legacy",
                    raw_payload={},
                    created_at=row["created_at"],
                )
            )
        temp_rows = temperatures_by_measurement.get(row["id"], [])
        if temp_rows:
            sample_id = bind.scalar(
                sa.select(temperature_samples.c.id).where(
                    temperature_samples.c.session_id == row["session_id"],
                    temperature_samples.c.received_timestamp == row["timestamp"],
                    temperature_samples.c.source == "legacy",
                )
            )
            if sample_id is None:
                result = bind.execute(
                    temperature_samples.insert().values(
                        session_id=row["session_id"],
                        device_id=device_id,
                        device_timestamp=row["timestamp"],
                        received_timestamp=row["timestamp"],
                        quality=row["quality"],
                        source="legacy",
                        raw_payload={},
                        created_at=row["created_at"],
                    )
                )
                sample_id = result.inserted_primary_key[0]
            existing_channels = set(
                bind.execute(
                    sa.select(temperature_values.c.channel).where(
                        temperature_values.c.sample_id == sample_id
                    )
                ).scalars()
            )
            missing_values = [
                {
                    "sample_id": sample_id,
                    "channel": value["channel"],
                    "temperature_c": value["temperature_c"],
                    "original_value": value["temperature_c"],
                    "original_unit": "°C",
                    "quality": value["quality"],
                }
                for value in temp_rows
                if value["channel"] not in existing_channels
            ]
            if missing_values:
                bind.execute(temperature_values.insert(), missing_values)

    # AT4532 supports 32 channels. Existing channels stay unchanged; extra channels start disabled.
    devices = tables["devices"]
    for device_id in bind.execute(sa.select(devices.c.id)).scalars():
        existing = set(
            bind.execute(
                sa.select(channel_configs.c.channel).where(channel_configs.c.device_id == device_id)
            ).scalars()
        )
        additions = [
            {
                "device_id": device_id,
                "channel": channel,
                "name": f"Termopar {channel}",
                "enabled": False,
                "sensor_type": "K",
                "unit": "°C",
                "correction_offset": 0.0,
                "color": "#3667E9",
                "display_order": channel,
            }
            for channel in range(1, 33)
            if channel not in existing
        ]
        if additions:
            bind.execute(channel_configs.insert(), additions)


def downgrade() -> None:
    op.drop_table("channel_profile_values")
    op.drop_table("channel_profiles")
    op.drop_table("session_channel_configurations")
    op.drop_table("temperature_channel_values")
    op.drop_table("temperature_samples")
    op.drop_table("electrical_samples")
    op.drop_table("session_devices")
    op.drop_column("channel_configurations", "display_order")
    op.drop_column("measurement_sessions", "sync_tolerance_ms")
    op.drop_column("measurement_sessions", "sync_grid_ms")
    op.drop_column("measurement_sessions", "acquisition_mode")
