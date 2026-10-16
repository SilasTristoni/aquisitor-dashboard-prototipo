"""Read-only storage evidence, collected inside the bounded diagnostic process."""

import shutil
from pathlib import Path

from sqlalchemy import text


def storage_snapshot(db):
    result = {"quota": "not measured; free volume space does not prove write capacity"}
    try:
        bind = db.get_bind()
        result["dialect"] = bind.dialect.name
        if bind.dialect.name != "sqlite":
            return result
        path = Path(db.info.get("diagnostic_database_path") or bind.engine.url.database).resolve()
        # Include volume + basename, not the user's home directory or a database URL.
        result.update(database_filename=path.name, volume=path.anchor)
        result["volume_free_bytes"] = shutil.disk_usage(path.parent).free
        result["files"] = {
            suffix or "database": (candidate.stat().st_size if candidate.exists() else None)
            for suffix in ("", "-wal", "-shm")
            for candidate in [Path(str(path) + suffix)]
        }
        for pragma in (
            "page_count", "page_size", "freelist_count", "max_page_count", "journal_mode",
        ):
            result[pragma] = db.scalar(text(f"PRAGMA {pragma}"))
    except Exception as exc:
        result["unavailable"] = type(exc).__name__
    return result
