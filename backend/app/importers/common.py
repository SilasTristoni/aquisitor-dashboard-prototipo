from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class ImportIssue:
    row: int
    field: str
    message: str
    value: str | None = None


@dataclass
class ImportResult(Generic[T]):
    readings: list[T] = field(default_factory=list)
    errors: list[ImportIssue] = field(default_factory=list)
    warnings: list[ImportIssue] = field(default_factory=list)
    mapping: dict[str, str] = field(default_factory=dict)

    def preview(self, limit: int = 10) -> dict:
        timestamps = [item.received_timestamp for item in self.readings]
        return {
            "valid_rows": len(self.readings),
            "invalid_rows": len({issue.row for issue in self.errors}),
            "start": min(timestamps).isoformat() if timestamps else None,
            "end": max(timestamps).isoformat() if timestamps else None,
            "mapping": self.mapping,
            "errors": [issue.__dict__ for issue in self.errors[:50]],
            "warnings": [issue.__dict__ for issue in self.warnings[:50]],
            "rows": [item.model_dump(mode="json") for item in self.readings[:limit]],
        }


def ensure_aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value
