from datetime import UTC, datetime


def utc(value: datetime) -> datetime:
    """SQLite's naive timestamps have the same UTC semantics as PostgreSQL."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
