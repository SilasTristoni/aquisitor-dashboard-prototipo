"""Reproducible r5 evidence: real observer persistence, synthetic sources only."""
# ruff: noqa: E402

import importlib.util
import json
import os
import secrets
import sys
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ["THERMOPOWER_DATABASE_URL"] = "sqlite:///:memory:"
os.environ["THERMOPOWER_JWT_SECRET"] = secrets.token_urlsafe(48)

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from app.core.database import Base  # noqa: E402
from app.models.entities import (
    Device,
    MeasurementSession,
    SessionDevice,
    SourceAvailability,
    User,
)  # noqa: E402
from app.services.source_availability import AvailabilityObserver, interval_dict  # noqa: E402
from app.services.period_reporting import PeriodReportDataService, period_statistics  # noqa: E402
from app.services.period_documents import (
    render_period_chart,
    render_period_pdf,
    render_executive_summary,
)  # noqa: E402
from app.services.period_workbook import render_period_csv, render_period_xlsx  # noqa: E402


def main():
    output = ROOT / "build/integrated-r5/fixtures"
    output.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location(
        "synthetic_base", ROOT / "scripts/generate-client-preview-fixtures.py"
    )
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    data, request = fixture.fixture_data(300)
    readings = []
    with TemporaryDirectory(dir=output) as temporary:
        engine = create_engine(
            f"sqlite:///{Path(temporary).as_posix()}/synthetic.sqlite"
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(engine, expire_on_commit=False)
        with factory() as db:
            db.add(
                User(
                    id=1,
                    name="Synthetic",
                    email="synthetic@example.test",
                    password_hash="not-a-credential",
                    role="admin",
                )
            )
            db.add(
                Device(
                    id=2,
                    name="GPM synthetic",
                    protocol="gpm8213_serial",
                    connection_type="serial",
                )
            )
            db.flush()
            db.add(
                MeasurementSession(
                    id=1,
                    device_id=2,
                    user_id=1,
                    name="Synthetic availability",
                    started_at=request.start,
                    status="running",
                )
            )
            db.flush()
            db.add(SessionDevice(session_id=1, device_id=2, role="electrical"))
            db.commit()
        observer = AvailabilityObserver(factory)
        for second in range(300):
            lost = 60 <= second < 100 or 180 <= second < 220
            paused = 260 <= second < 270
            if not lost and not paused:
                readings.append(
                    (
                        request.start + timedelta(seconds=second),
                        data["electrical"][second]["active_power_w"],
                    )
                )
            observer.tick(
                {
                    2: {
                        "session_id": 1,
                        "state": "recovering" if lost else "connected",
                        "cause": "port_not_found" if lost else None,
                        "paused": paused,
                        "readings": readings,
                    }
                },
                request.start + timedelta(seconds=second),
            )
        with factory() as db:
            data["availability"] = [
                {"session_id": 1, **interval_dict(row)}
                for row in db.scalars(
                    select(SourceAvailability).order_by(SourceAvailability.started_at)
                )
            ]
        assert len(data["availability"]) == 2
        engine.dispose()
    data["electrical"] = [
        point
        for index, point in enumerate(data["electrical"])
        if not (60 <= index < 100 or 180 <= index < 220 or 260 <= index < 270)
    ]
    data["temperatures"] = [
        point
        for index, point in enumerate(data["temperatures"])
        if not 260 <= index < 270
    ]
    data["statistics"] = period_statistics(data)
    service = PeriodReportDataService(None)
    preview = service.preview_data(data, request)
    (output / "preview.json").write_text(
        json.dumps(preview, ensure_ascii=False), encoding="utf-8"
    )
    (output / "availability.json").write_text(
        json.dumps(data["availability"], indent=2), encoding="utf-8"
    )
    for name, content in {
        "historical.png": render_period_chart(data, request, "png"),
        "historical.pdf": render_period_pdf(data, request),
        "executive.png": render_executive_summary(data, request),
        "executive.pdf": render_executive_summary(data, request, "pdf"),
        "measurements.csv": render_period_csv(data, request),
        "measurements.xlsx": render_period_xlsx(data, request),
    }.items():
        (output / name).write_bytes(content)
    print("Two confirmed intervals persisted and exported; no synthetic zero samples.")


if __name__ == "__main__":
    main()
