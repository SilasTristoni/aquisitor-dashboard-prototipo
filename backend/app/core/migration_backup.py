"""Fail closed before the Windows launcher upgrades an existing database."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory


def prepare_migration_backup(configuration, database_url: str) -> Path | None:
    scripts = ScriptDirectory.from_config(configuration)
    target = set(scripts.get_heads())
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        engine = create_engine(url)
        try:
            with engine.connect() as connection:
                current = set(MigrationContext.configure(connection).get_current_heads())
            if current != target:
                raise RuntimeError(
                    "Atualização PostgreSQL bloqueada no launcher: faça backup nativo verificado "
                    "e aplique as migrations pelo procedimento administrativo antes de iniciar."
                )
        finally:
            engine.dispose()
        return None
    if not url.database or url.database == ":memory:":
        return None
    source = Path(url.database).resolve()
    if not source.exists():
        return None
    # URI read-only: inspecting a path must never create or modify a historical database.
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original:
        tables = {
            row[0] for row in original.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        current = (
            {row[0] for row in original.execute("SELECT version_num FROM alembic_version")}
            if "alembic_version" in tables
            else set()
        )
        for revision in current:
            if scripts.get_revision(revision) is None:
                raise RuntimeError("Banco de versão desconhecida; restaure um backup compatível.")
        if current == target:
            return None
        if original.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise RuntimeError(
                "Banco não passou na verificação de integridade; atualização bloqueada."
            )
        required = source.stat().st_size + sum(
            path.stat().st_size for path in [Path(str(source) + "-wal")] if path.exists()
        )
        if shutil.disk_usage(source.parent).free < required * 2 + 64 * 1024 * 1024:
            raise RuntimeError(
                "Espaço insuficiente para backup e migration; atualização bloqueada."
            )
        directory = source.parent / "migration-backups"
        directory.mkdir(exist_ok=True)
        name = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex
        backup = directory / f"{source.stem}-{name}.sqlite"
        with sqlite3.connect(backup) as destination:
            original.backup(destination)
            if destination.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise RuntimeError("Backup inválido; atualização bloqueada.")
    with backup.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    backup.with_suffix(".json").write_text(
        json.dumps(
            {
                "source": str(source),
                "revisions": sorted(current),
                "target": sorted(target),
                "sha256": digest,
                "bytes": backup.stat().st_size,
                "method": "sqlite_online_backup",
                "integrity": "ok",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return backup
