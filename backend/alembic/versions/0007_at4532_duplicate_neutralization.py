"""Neutralize conflicting historical AT4532 registrations without deleting them.

Revision ID: 0007_at4532_duplicate_neutralization
Revises: 0006_documented_physical_protocols
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from alembic import op

revision = "0007_at4532_duplicate_neutralization"
down_revision = "0006_documented_physical_protocols"
branch_labels = None
depends_on = None

devices = sa.table(
    "devices",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("model", sa.String),
    sa.column("port", sa.String),
    sa.column("baud_rate", sa.Integer),
    sa.column("protocol", sa.String),
    sa.column("active", sa.Boolean),
    sa.column("metadata", sa.JSON),
)


def _preference(row: Any) -> tuple[int, int, int, int]:
    metadata = dict(row["metadata"] or {})
    usb = metadata.get("usb") if isinstance(metadata.get("usb"), dict) else {}
    return (
        int(bool(row["active"])),
        int(row["baud_rate"] == 19200),
        int(bool(usb.get("manual_confirmed"))),
        -int(row["id"]),
    )


def upgrade() -> None:
    connection = op.get_bind()
    rows = list(
        connection.execute(
            sa.select(devices).where(
                sa.or_(devices.c.model == "AT4532", devices.c.protocol == "at4532_serial")
            )
        ).mappings()
    )
    groups: dict[str, list[Any]] = {}
    for row in rows:
        if row["port"]:
            groups.setdefault(str(row["port"]).casefold(), []).append(row)

    for port_rows in groups.values():
        if len(port_rows) < 2:
            continue
        canonical = max(port_rows, key=_preference)
        duplicate_ids = [row["id"] for row in port_rows if row["id"] != canonical["id"]]
        for row in port_rows:
            metadata = dict(row["metadata"] or {})
            if row["id"] == canonical["id"]:
                metadata["configuration_status"] = "canonical"
                metadata["neutralized_duplicate_ids"] = duplicate_ids
                values = {"active": True, "metadata": metadata}
            else:
                metadata.update(
                    {
                        "configuration_status": "archived_duplicate",
                        "superseded_by_device_id": canonical["id"],
                        "neutralization_reason": "duplicate_at4532_port_claim",
                    }
                )
                values = {"active": False, "metadata": metadata}
            connection.execute(
                devices.update().where(devices.c.id == row["id"]).values(**values)
            )


def downgrade() -> None:
    # Archival is intentionally not reversed: historical records and references are preserved.
    pass
