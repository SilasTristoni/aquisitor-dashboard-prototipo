"""Recovery orchestration around existing acquisition methods; no instrument commands."""

import asyncio
import logging
import shutil
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.database import SessionLocal, engine
from app.models.entities import (
    ApplicationInstance,
    Device,
    ElectricalSample,
    MeasurementSession,
    SessionDevice,
    SessionRecovery,
    SystemEvent,
    TemperatureSample,
)
from app.services.instance_guard import InstanceGuard
from app.services.pending_persistence import bounded_pending_writes, sample_write_session
from app.services.session_clock import utc

logger = logging.getLogger(__name__)


def persisted_summary(db, session_id):
    counts, timestamps = {}, []
    for label, model in (("electrical", ElectricalSample), ("thermal", TemperatureSample)):
        count, latest = db.execute(
            select(func.count(), func.max(model.received_timestamp)).where(
                model.session_id == session_id,
            )
        ).one()
        counts[label] = count
        if latest:
            timestamps.append(utc(latest))
    return {"counts": counts, "last_sample_at": max(timestamps) if timestamps else None}


def device_ids(db, session):
    return list(
        dict.fromkeys(
            db.scalars(
                select(SessionDevice.device_id).where(
                    SessionDevice.session_id == session.id,
                )
            )
        )
    ) or [session.device_id]


class RecoveryService:
    def __init__(self, factory=SessionLocal, bind=engine):
        self.factory, self.engine = factory, bind
        self.guard = InstanceGuard(bind)
        self.instance_id = str(uuid4())
        self.ready = False
        self.task = None
        self.storage = {"state": "unknown"}
        self.storage_checked_at = None

    def require_ready(self):
        if not self.ready:
            raise HTTPException(503, "Supervisão da aquisição indisponível. Reinicie a aplicação.")

    def start(self):
        # The caller holds the guard before creating schema/seeding. No stale-heartbeat takeover.
        self.instance_id = str(uuid4())
        self.storage_checked_at = None
        now = datetime.now(UTC)
        with self.factory() as db:
            for previous in db.scalars(
                select(ApplicationInstance).where(
                    ApplicationInstance.state == "active",
                )
            ):
                previous.state = "interrupted"
            db.add(
                ApplicationInstance(
                    id=self.instance_id, started_at=now, heartbeat_at=now, state="active"
                )
            )
            db.flush()
            for session in db.scalars(
                select(MeasurementSession).where(
                    MeasurementSession.status.in_(["running", "paused"]),
                    MeasurementSession.acquisition_mode != "import",
                )
            ):
                self._pending(db, session, "unexpected_shutdown", now)
            # A process may die after the operator confirms but before attachment finishes.
            for row in db.scalars(
                select(SessionRecovery).where(SessionRecovery.state == "resuming")
            ):
                session = db.get(MeasurementSession, row.session_id)
                if session.status not in {"running", "paused"}:
                    self._pending(db, session, "unexpected_shutdown", now)
            db.commit()
        self.ready = True

    def _pending(self, db, session, reason, now):
        recovery = db.get(SessionRecovery, session.id)
        if not recovery:
            recovery = SessionRecovery(session_id=session.id, state="pending")
            db.add(recovery)
        summary = persisted_summary(db, session.id)
        recovery.state, recovery.reason, recovery.detected_at = "pending", reason, now
        recovery.checkpoint_at, recovery.last_sample_at = now, summary["last_sample_at"]
        session.status = "suspended" if reason == "controlled_shutdown" else "interrupted"
        db.add(
            SystemEvent(
                session_id=session.id,
                category="session_interrupted",
                level="warning",
                message="Ensaio aguarda decisão de recuperação",
                details={
                    "reason": reason,
                    "instance_id": recovery.instance_id,
                    "last_sample_at": summary["last_sample_at"].isoformat()
                    if summary["last_sample_at"]
                    else None,
                    "counts": summary["counts"],
                },
            )
        )

    def register(self, db, session_id):
        self.require_ready()
        row = db.get(SessionRecovery, session_id)
        if not row:
            row = SessionRecovery(session_id=session_id, state="active")
            db.add(row)
        row.instance_id, row.state = self.instance_id, "active"
        row.checkpoint_at = datetime.now(UTC)

    def validate_transition(self, db, session_id):
        self.require_ready()
        row = db.get(SessionRecovery, session_id)
        if row and row.state == "pending":
            raise HTTPException(409, "Use as ações de recuperação para este ensaio.")

    def heartbeat(self):
        now = datetime.now(UTC)
        with bounded_pending_writes(), sample_write_session(self.factory) as db:
            instance = db.get(ApplicationInstance, self.instance_id)
            if instance:
                instance.heartbeat_at = now
            # Indexed MAX queries, never load measurement history into the supervisor.
            for row in db.scalars(
                select(SessionRecovery).where(
                    SessionRecovery.instance_id == self.instance_id,
                    SessionRecovery.state == "active",
                )
            ):
                session = db.get(MeasurementSession, row.session_id)
                if session.status not in {"running", "paused"}:
                    row.state = "resolved"
                    continue
                latest = [
                    db.scalar(
                        select(func.max(model.received_timestamp)).where(
                            model.session_id == row.session_id,
                        )
                    )
                    for model in (ElectricalSample, TemperatureSample)
                ]
                row.last_sample_at = max((utc(t) for t in latest if t), default=None)
                row.checkpoint_at = now
            db.commit()

    def check_storage(self):
        now = datetime.now(UTC)
        if self.storage_checked_at and (now - self.storage_checked_at).total_seconds() < 30:
            return
        self.storage_checked_at = now
        result = {"state": "ok", "checked_at": now.isoformat(), "dialect": self.engine.dialect.name}
        if self.engine.dialect.name == "sqlite" and self.engine.url.database != ":memory:":
            path = Path(self.engine.url.database).resolve()
            free = shutil.disk_usage(path.parent).free
            result.update(
                free_bytes=free,
                database_bytes=sum(
                    p.stat().st_size
                    for suffix in ("", "-wal", "-journal")
                    if (p := Path(str(path) + suffix)).exists()
                ),
            )
            result["state"] = (
                "critical"
                if free < 100 * 1024**2
                else ("warning" if free < 512 * 1024**2 else "ok")
            )
        elif self.engine.dialect.name != "sqlite":
            result["capacity"] = "server_monitoring_required"
        if result["state"] != self.storage.get("state") and result["state"] != "ok":
            logger.warning(
                "Storage capacity state=%s free_bytes=%s", result["state"], result.get("free_bytes")
            )
            with bounded_pending_writes(), sample_write_session(self.factory) as db:
                db.add(
                    SystemEvent(
                        category="storage_capacity",
                        level="warning",
                        message="Espaço disponível para medições está baixo",
                        details=result,
                    )
                )
                db.commit()
        self.storage = result

    async def monitor(self, acquisition):
        while True:
            await asyncio.sleep(5)
            try:
                self.guard.check()
            except Exception:
                self.ready = False
                logger.error("Acquisition ownership lost; pausing local sources")
                for device_id in list(acquisition.runtimes):
                    try:
                        with bounded_pending_writes():
                            await acquisition.pause_session(device_id)
                    except Exception:
                        # Pause rolls back its flag on write failure. The existing disconnect
                        # stops the producer first and retains uncommitted buffers on failure.
                        with suppress(Exception), bounded_pending_writes():
                            await acquisition.disconnect(device_id)
                return
            try:
                # An idle supervisor must not compete with report/maintenance transactions
                # or borrow extra SQLite connections. Ownership is the OS/advisory lock,
                # never a heartbeat timeout. Checkpoint only attached acquisitions.
                if any(runtime.session_id is not None for runtime in acquisition.runtimes.values()):
                    self.heartbeat()
                self.check_storage()
            except Exception as exc:
                logger.warning("Recovery checkpoint unavailable error=%s", type(exc).__name__)
                self.storage = {
                    "state": "unavailable",
                    "message": "Não foi possível confirmar o armazenamento.",
                }

    def shutdown(self):
        if not self.ready:
            return
        now = datetime.now(UTC)
        try:
            with bounded_pending_writes(), sample_write_session(self.factory) as db:
                for session in db.scalars(
                    select(MeasurementSession).where(
                        MeasurementSession.status.in_(["running", "paused"]),
                        MeasurementSession.acquisition_mode != "import",
                    )
                ):
                    self._pending(db, session, "controlled_shutdown", now)
                instance = db.get(ApplicationInstance, self.instance_id)
                instance.state, instance.stopped_at, instance.heartbeat_at = "stopped", now, now
                db.commit()
        except Exception as exc:
            logger.error("Could not persist controlled shutdown error=%s", type(exc).__name__)
        finally:
            self.ready = False

    def listing(self, db, page, page_size):
        query = select(SessionRecovery).where(SessionRecovery.state == "pending")
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        items = []
        for row in db.scalars(
            query.order_by(SessionRecovery.session_id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ):
            session = db.get(MeasurementSession, row.session_id)
            summary = persisted_summary(db, session.id)
            items.append(
                {
                    "id": session.id,
                    "name": session.name,
                    "status": session.status,
                    "started_at": utc(session.started_at),
                    "reason": row.reason,
                    "detected_at": utc(row.detected_at),
                    "checkpoint_at": utc(row.checkpoint_at) if row.checkpoint_at else None,
                    **summary,
                    "devices": [
                        {"id": d.id, "name": d.name}
                        for d in db.scalars(
                            select(Device).where(Device.id.in_(device_ids(db, session)))
                        )
                    ],
                }
            )
        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": max(1, (total + page_size - 1) // page_size),
        }

    async def decide(self, db, acquisition, session_id, action, actor_id):
        self.require_ready()
        # Shares the existing start lock; a new session cannot claim a source mid-recovery.
        async with acquisition.session_start_lock:
            db.expire_all()
            row, session = (
                db.get(SessionRecovery, session_id),
                db.get(MeasurementSession, session_id),
            )
            if not row or not session:
                raise HTTPException(404, "Ensaio recuperável não encontrado.")
            if row.state != "pending" or session.status not in {"interrupted", "suspended"}:
                raise HTTPException(409, "Este ensaio já recebeu uma decisão.")
            ids = device_ids(db, session)
            for other in db.scalars(
                select(MeasurementSession).where(
                    MeasurementSession.id != session_id,
                    MeasurementSession.status.in_(["running", "paused"]),
                )
            ):
                if action == "resume" and set(ids).intersection(device_ids(db, other)):
                    raise HTTPException(
                        409, "Uma fonte está em uso por outro ensaio. Finalize-o antes de retomar."
                    )
            if any(r.session_id == session_id for r in acquisition.runtimes.values()):
                raise HTTPException(409, "Há aquisição local vinculada a este ensaio.")
            now = datetime.now(UTC)
            successes, failures = [], []
            if action == "resume":
                # Confirm intent before any device operation. This boundary survives a
                # process death in the middle of connecting independent sources.
                row.state = "resuming"
                row.instance_id = self.instance_id
                db.add(
                    SystemEvent(
                        session_id=session_id,
                        category="session_recovery_intent",
                        message="Operador confirmou a retomada",
                        details={"actor_id": actor_id, "resumed_at": now.isoformat()},
                    )
                )
                db.commit()
                for device_id in ids:
                    runtime = acquisition.runtimes.get(device_id)
                    if runtime and runtime.session_id is not None:
                        failures.append({"device_id": device_id, "error": "Fonte ocupada"})
                        continue
                    try:
                        await acquisition.resume_session(device_id, session_id)
                        successes.append(device_id)
                    except Exception as exc:
                        failures.append({"device_id": device_id, "error": type(exc).__name__})
                if not successes:
                    row.state = "pending"
                    db.add(
                        SystemEvent(
                            session_id=session_id,
                            category="session_recovery_failed",
                            level="warning",
                            message="Nenhuma fonte disponível para retomar",
                            details={"actor_id": actor_id, "sources": failures},
                        )
                    )
                    db.commit()
                    raise HTTPException(
                        422,
                        "Nenhuma fonte disponível. Verifique os equipamentos e tente novamente.",
                    )
                session.status = "running"
                row.instance_id, row.state = self.instance_id, "active"
            else:
                session.status, session.ended_at, row.state = "interrupted_closed", now, "resolved"
            row.decision_at = now
            db.add(
                SystemEvent(
                    session_id=session_id,
                    category=f"session_recovery_{action}",
                    message="Ensaio retomado"
                    if action == "resume"
                    else "Encerrado como interrompido",
                    details={
                        "actor_id": actor_id,
                        "instance_id": self.instance_id,
                        "last_sample_at": utc(row.last_sample_at).isoformat()
                        if row.last_sample_at
                        else None,
                        "resumed_at": now.isoformat() if action == "resume" else None,
                        "sources": successes,
                        "unavailable_sources": failures,
                    },
                )
            )
            try:
                db.commit()
            except Exception:
                db.rollback()
                # Existing detach flushes accepted data; never drop a buffered reading on error.
                for device_id in successes:
                    with suppress(Exception):
                        await acquisition.pause_session(device_id)
                    with suppress(Exception):
                        await acquisition.detach_session(device_id)
                with suppress(Exception):
                    db.get(SessionRecovery, session_id).state = "pending"
                    db.commit()
                raise HTTPException(
                    503,
                    "Decisão não confirmada no banco. Aquisição pausada; "
                    "verifique o armazenamento.",
                ) from None
            return {
                "id": session_id,
                "status": session.status,
                "sources": successes,
                "unavailable_sources": failures,
            }


recovery_service = RecoveryService()
