"""Accelerated 20/24 h volumes through the real writer, exclusively in a fresh synthetic DB.

This measures software load, not 24 hours of wall-clock or physical power-loss durability.
psutil is a validation-only dependency already used by the build environment.
"""

import argparse
import asyncio
import json
import math
import os
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


async def validate(hours, output):
    import psutil
    from sqlalchemy import func, select, text

    from app.adapters.base import DeviceReading
    from app.core.database import Base, SessionLocal, engine
    from app.models.entities import (
        Device,
        ElectricalSample,
        MeasurementSession,
        SessionDevice,
        TemperatureSample,
        User,
    )
    from app.schemas.contracts import PeriodReportRequest
    from app.services.acquisition import AcquisitionService, DeviceRuntime
    from app.services import company_identity  # noqa: F401 - register the existing model
    from app.services.period_documents import render_period_chart, render_period_pdf
    from app.services.period_reporting import PeriodReportDataService
    from app.services.session_recovery import RecoveryService

    class NoInstrumentAccess:
        def __getattr__(self, name):
            raise AssertionError(f"Validation must not access instruments: {name}")

    process = psutil.Process()
    metrics = {"hours_simulated": hours, "physical_validation": False, "stages": []}
    rss, delays = [], []
    running = True

    async def monitor():
        previous = time.monotonic()
        while running:
            rss.append(process.memory_info().rss)
            await asyncio.sleep(0.02)
            current = time.monotonic()
            delays.append(current - previous)
            previous = current

    task = asyncio.create_task(monitor())
    wall_start, cpu_start = time.monotonic(), time.process_time()

    def stage(name, started):
        metrics["stages"].append(
            {
                "name": name,
                "seconds": time.monotonic() - started,
                "rss_bytes": process.memory_info().rss,
            }
        )
        print(json.dumps(metrics["stages"][-1]), flush=True)

    Base.metadata.create_all(engine)
    origin = datetime(2026, 11, 1, tzinfo=UTC)
    with SessionLocal() as db:
        user = User(
            name="Synthetic", email="extended@example.invalid", password_hash="unused"
        )
        devices = [
            Device(name=f"Synthetic {role}", protocol="simulator")
            for role in ("electrical", "temperature")
        ]
        db.add_all([user, *devices])
        db.flush()
        session = MeasurementSession(
            name=f"Synthetic {hours} h",
            device_id=devices[0].id,
            user_id=user.id,
            started_at=origin,
            status="running",
        )
        db.add(session)
        db.flush()
        session_id, ids = session.id, [d.id for d in devices]
        for device_id, role in zip(ids, ("electrical", "temperature"), strict=True):
            db.add(SessionDevice(session_id=session_id, device_id=device_id, role=role))
        db.commit()
    service = AcquisitionService()
    for device_id, role in zip(ids, ("electrical", "temperature"), strict=True):
        service.runtimes[device_id] = DeviceRuntime(
            adapter=NoInstrumentAccess(), source_role=role, session_id=session_id
        )
    started = time.monotonic()
    max_buffer = 0
    for second in range(hours * 3600):
        stamp = origin + timedelta(seconds=second)
        power = 150 + 50 * math.sin(second / 15)
        service.runtimes[ids[0]].buffer.append(
            DeviceReading(
                timestamp=stamp,
                received_timestamp=stamp,
                power_w=power,
                raw_power=power,
                raw_power_unit="W",
                temperatures_c=[],
            )
        )
        if second % 5 == 0:
            service.runtimes[ids[1]].buffer.append(
                DeviceReading(
                    timestamp=stamp,
                    received_timestamp=stamp,
                    power_w=None,
                    raw_power=None,
                    raw_power_unit="W",
                    temperatures_c=[
                        None
                        if channel == 31
                        else 25 + channel + 8 * math.sin(second / 23)
                        for channel in range(32)
                    ],
                )
            )
        # Accelerated time: bounded bursts through the unmodified commit method.
        if second % 100 == 99:
            max_buffer = max(
                max_buffer, sum(len(r.buffer) for r in service.runtimes.values())
            )
            for device_id, runtime in service.runtimes.items():
                await service._flush(device_id, runtime)
            await asyncio.sleep(0.001)
    stage("persist_actual_writer", started)
    assert all(not r.buffer for r in service.runtimes.values())
    metrics["max_buffered_samples"] = max_buffer
    engine.dispose()
    started = time.monotonic()
    recovery = RecoveryService()
    recovery.guard.acquire()
    try:
        recovery.start()
        with SessionLocal() as db:
            page = recovery.listing(db, 1, 10)
            assert page["total"] == 1
            assert page["items"][0]["counts"] == {
                "electrical": hours * 3600,
                "thermal": hours * 720,
            }
            assert db.scalar(text("PRAGMA integrity_check")) == "ok"
            assert not db.execute(text("PRAGMA foreign_key_check")).all()
            for model in (ElectricalSample, TemperatureSample):
                assert db.scalar(
                    select(func.count(func.distinct(model.sequence)))
                ) == db.scalar(select(func.count()).select_from(model))
            metrics["counts"] = page["items"][0]["counts"]
        stage("restart_integrity_and_recovery", started)
    finally:
        recovery.shutdown()
        recovery.guard.release()

    request = PeriodReportRequest(
        start=origin,
        end=origin + timedelta(hours=hours),
        session_ids=[session_id],
        channels=list(range(1, 33)),
        title=f"Synthetic {hours} h",
        table_max_rows=100,
    )

    def report():
        started = time.monotonic()
        with SessionLocal() as db:
            data = PeriodReportDataService(db).collect(request)
            stage("collect_report", started)
            started = time.monotonic()
            preview = PeriodReportDataService(db).preview_data(data, request)
            count = sum(
                len(s["electrical"]) + len(s["temperatures"]) for s in preview["series"]
            )
            assert count <= 10000
            metrics["preview_points"] = count
            (output / "preview.json").write_text(
                json.dumps(preview, default=str), encoding="utf-8"
            )
            stage("preview", started)
            from app.services.synchronization import synchronized_series

            started = time.monotonic()
            synchronized = synchronized_series(db, session_id, max_points=600)
            assert len(synchronized["points"]) <= 600
            assert synchronized["source_counts"] == {
                "electrical": hours * 3600,
                "temperature": hours * 720,
            }
            stage("bounded_synchronized_chart", started)
            started = time.monotonic()
            (output / "report.png").write_bytes(
                render_period_chart(data, request, "png")
            )
            (output / "report.pdf").write_bytes(render_period_pdf(data, request))
            stage("pdf_png_export", started)

    try:
        await asyncio.to_thread(
            report
        )  # Synchronous API report handlers already use a worker.
    finally:
        running = False
        await task
        metrics.update(
            elapsed_seconds=time.monotonic() - wall_start,
            cpu_seconds=time.process_time() - cpu_start,
            peak_sampled_rss_bytes=max(rss),
            max_event_loop_interval_seconds=max(delays),
            database_bytes=Path(engine.url.database).stat().st_size,
        )
        (output / "metrics.json").write_text(
            json.dumps(metrics, indent=2), encoding="utf-8"
        )
    print(json.dumps(metrics), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, choices=(20, 24), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    synthetic = Path(
        tempfile.mkdtemp(prefix="synthetic-extended-", dir=args.output)
    ).resolve()
    os.environ["THERMOPOWER_DATABASE_URL"] = (
        f"sqlite:///{synthetic.as_posix()}/measurements.sqlite"
    )
    os.environ["THERMOPOWER_JWT_SECRET"] = uuid4().hex + uuid4().hex
    os.environ["THERMOPOWER_LOG_DIRECTORY"] = str(synthetic / "logs")
    sys.path.insert(0, str(ROOT / "backend"))
    asyncio.run(validate(args.hours, args.output))


if __name__ == "__main__":
    main()
