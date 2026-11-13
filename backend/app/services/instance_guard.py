"""One acquisition process per database, released by the OS/server on process death."""

import os
from pathlib import Path

from sqlalchemy import text


class InstanceGuard:
    def __init__(self, engine):
        self.engine = engine
        self.file = None
        self.connection = None

    def acquire(self):
        try:
            if self.engine.dialect.name == "postgresql":
                self.connection = self.engine.connect()
                if not self.connection.scalar(text("SELECT pg_try_advisory_lock(1414548813, 1)")):
                    raise RuntimeError("Outro processo ThermoPower já utiliza este banco.")
                self.connection.commit()
            elif self.engine.dialect.name == "sqlite":
                database = self.engine.url.database
                if not database or database == ":memory:":
                    return
                path = Path(database).resolve()
                self.file = open(str(path) + ".acquisition.lock", "a+b")
                if os.name == "nt":
                    import msvcrt

                    self.file.seek(0)
                    msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                raise RuntimeError("Banco não suportado para recuperação de aquisição.")
        except Exception as exc:
            self.release()
            raise RuntimeError(
                "Não foi possível obter uso exclusivo do banco para aquisição. "
                "Verifique se outra instância está aberta."
            ) from exc

    def check(self):
        if self.connection is not None:
            self.connection.scalar(text("SELECT 1"))
            self.connection.commit()

    def release(self):
        if self.connection is not None:
            # Invalidate, rather than return a session-level advisory lock to the pool.
            self.connection.invalidate()
            self.connection.close()
            self.connection = None
        if self.file is not None:
            self.file.close()
            self.file = None
