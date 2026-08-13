"""Normalize physical devices and record documented serial protocols.

Revision ID: 0006_documented_physical_protocols
Revises: 0005_nullable_physical_baud_rate
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from alembic import op

revision = "0006_documented_physical_protocols"
down_revision = "0005_nullable_physical_baud_rate"
branch_labels = None
depends_on = None

devices = sa.table(
    "devices",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("model", sa.String),
    sa.column("serial_number", sa.String),
    sa.column("port", sa.String),
    sa.column("baud_rate", sa.Integer),
    sa.column("protocol", sa.String),
    sa.column("active", sa.Boolean),
    sa.column("metadata", sa.JSON),
)


def _normalize(rows: list[Any], preferred_name: str, protocol: str, values: dict[str, Any]) -> None:
    if not rows:
        return
    target_serial = values.get("serial_number")
    preferred = next(
        (row for row in rows if target_serial and row["serial_number"] == target_serial), None
    ) or next((row for row in rows if row["name"] == preferred_name), None)
    canonical = preferred or next((row for row in rows if row["baud_rate"] == 19200), rows[0])
    duplicate_ids = [row["id"] for row in rows if row["id"] != canonical["id"]]
    connection = op.get_bind()
    if duplicate_ids:
        connection.execute(
            devices.update().where(devices.c.id.in_(duplicate_ids)).values(active=False)
        )
    metadata = dict(canonical["metadata"] or {})
    metadata.update(values.pop("metadata"))
    connection.execute(
        devices.update()
        .where(devices.c.id == canonical["id"])
        .values(active=True, protocol=protocol, metadata=metadata, **values)
    )


def upgrade() -> None:
    connection = op.get_bind()
    at_rows = list(
        connection.execute(
            sa.select(devices).where(
                sa.or_(devices.c.model == "AT4532", devices.c.protocol == "at4532_serial")
            )
        ).mappings()
    )
    _normalize(
        at_rows,
        "Applent AT4532 · LAB",
        "at4532_serial",
        {
            "name": "Applent AT4532 · LAB",
            "model": "AT4532",
            "port": "COM5",
            "baud_rate": 19200,
            "metadata": {
                "serial": {
                    "data_bits": 8,
                    "parity": "N",
                    "stop_bits": 1,
                    "timeout_s": 1,
                    "read_timeout_s": 2,
                    "line_terminator": "LF (0x0A)",
                    "framing": "SCPI ASCII",
                    "parameters_source": "vendor_documented",
                },
                "expected_interval_ms": 3000,
                "protocol_status": "vendor_documented_physical_validation_pending",
                "physical_validation": "pending",
            },
        },
    )
    gpm_rows = list(
        connection.execute(
            sa.select(devices).where(
                sa.or_(
                    devices.c.model == "GPM-8213",
                    devices.c.protocol == "gpm8213_serial",
                    devices.c.serial_number == "GES913349",
                )
            )
        ).mappings()
    )
    _normalize(
        gpm_rows,
        "GW Instek GPM-8213 · LAB",
        "gpm8213_serial",
        {
            "name": "GW Instek GPM-8213 · LAB",
            "model": "GPM-8213",
            "serial_number": "GES913349",
            "baud_rate": None,
            "metadata": {
                "serial": {
                    "data_bits": 8,
                    "parity": "N",
                    "stop_bits": 1,
                    "timeout_s": 1,
                    "read_timeout_s": 2,
                    "line_terminator": "CR+LF (0x0D 0x0A)",
                    "framing": "SCPI ASCII over USB CDC",
                    "parameters_source": "vendor_documented",
                    "baud_relevance": "not_specified_for_usb_cdc",
                },
                "expected_interval_ms": 1000,
                "protocol_status": "vendor_documented_physical_validation_pending",
                "physical_validation": "pending",
            },
        },
    )


def downgrade() -> None:
    # Archival is intentionally not reversed: historical device references are preserved.
    pass
