"""Isolated, opt-in development DEMO. Never selects an existing application database."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "build" / "demo-r2"
MARKER = "thermopower-isolated-demo-r2"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["seed", "start", "test", "remove"])
    parser.add_argument(
        "--portal-from-environment",
        action="store_true",
        help="Enable manual publication using DEMO_PORTAL_* only",
    )
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    directory = DIRECTORY.resolve()
    if directory != ROOT.resolve() / "build" / "demo-r2" or DIRECTORY.is_symlink():
        raise ValueError("DEMO path must be the dedicated workspace directory")
    marker = directory / "demo-instance.json"
    if directory.exists() and not marker.is_file():
        raise ValueError("Unrecognized directory preserved")
    if marker.exists():
        config = json.loads(marker.read_text(encoding="utf-8"))
        if config.get("kind") != MARKER:
            raise ValueError("Invalid DEMO marker; directory preserved")
    else:
        if args.action != "seed":
            raise ValueError("Run seed first")
        directory.mkdir(parents=True)
        config = {
            "kind": MARKER,
            "jwt": secrets.token_urlsafe(48),
            "password": secrets.token_urlsafe(24),
        }
        marker.write_text(json.dumps(config, indent=2), encoding="utf-8")
    if args.action == "remove":
        # Windows refuses removal while SQLite is open. Never follow directory links.
        if any(
            path.is_symlink() or path.is_junction() for path in directory.rglob("*")
        ):
            raise ValueError("Linked content detected; directory preserved")
        shutil.rmtree(directory)
        return
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("THERMOPOWER_")
    }
    environment.update(
        {
            "THERMOPOWER_ENVIRONMENT": "development",
            "THERMOPOWER_APP_DATA_DIR": str(directory),
            "THERMOPOWER_DATABASE_URL": "sqlite:///"
            + (directory / "demo.db").as_posix(),
            "THERMOPOWER_JWT_SECRET": config["jwt"],
            "THERMOPOWER_DEMO_ADMIN_EMAIL": "admin@demo.thermopower.com",
            "THERMOPOWER_DEMO_ADMIN_PASSWORD": config["password"],
            "THERMOPOWER_INITIAL_ADMIN_NAME": "Administrador DEMO",
            "THERMOPOWER_UX_VIEWER_PASSWORD": config["password"],
            "THERMOPOWER_LOG_DIRECTORY": str(directory / "logs"),
            "THERMOPOWER_REPORT_OUTPUT_DIRECTORY": str(directory / "reports"),
            "THERMOPOWER_FRONTEND_DIST": str(ROOT / "frontend" / "dist"),
            "THERMOPOWER_MUTEX_NAME": "ThermoPowerIsolatedDemoR2",
            "THERMOPOWER_NO_BROWSER": "1" if args.no_browser else "0",
            # Select the whole environment tuple, with NO credentials or vault fallback.
            "THERMOPOWER_RESULTS_PORTAL_URL": "https://demo-not-configured.invalid",
            "THERMOPOWER_RESULTS_PORTAL_INSTALLATION_ID": "",
            "THERMOPOWER_RESULTS_PORTAL_PUBLISH_KEY": "",
        }
    )
    if args.portal_from_environment:
        if args.action != "start":
            raise ValueError(
                "Portal credentials are only accepted for interactive start"
            )
        for target, source in (
            ("URL", "URL"),
            ("INSTALLATION_ID", "INSTALLATION_ID"),
            ("PUBLISH_KEY", "PUBLISH_KEY"),
        ):
            value = os.environ.get("DEMO_PORTAL_" + source)
            if not value:
                raise ValueError("Configure all DEMO_PORTAL_* variables explicitly")
            environment["THERMOPOWER_RESULTS_PORTAL_" + target] = value
    if args.action == "start":
        subprocess.run(
            [sys.executable, "-c",
             "from pathlib import Path; from app import windows_launcher as launcher; "
             "launcher._runtime_root = lambda: Path.cwd(); launcher.main()"],
            cwd=ROOT / "backend",
            env=environment,
            check=True,
        )
        return
    os.environ.clear()
    os.environ.update(environment)
    sys.path.insert(0, str(ROOT / "backend"))
    if args.action == "test":
        verify_demo(directory)
        return
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT / "backend",
        env=environment,
        check=True,
    )
    spec = importlib.util.spec_from_file_location(
        "demo_seed", ROOT / "scripts/seed-ux-demo.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.SCENARIOS += module.DEMO_EXTRA_SCENARIOS
    module.main()
    print(f"DEMO database: {directory / 'demo.db'}")
    print(f"Local access credentials: {marker}")


def verify_demo(directory):
    from datetime import timedelta

    from sqlalchemy import func, select
    from app.core.database import SessionLocal
    from app.models.entities import ElectricalSample, MeasurementSession, SystemEvent
    from app.schemas.contracts import PeriodReportRequest
    from app.services.period_documents import render_period_pdf
    from app.services.period_reporting import PeriodReportDataService
    from app.services.period_workbook import render_period_csv, render_period_xlsx
    from app.services.portal_configuration import configuration_status

    assert configuration_status()["configured"] is False
    results = []
    output = directory / "exports"
    output.mkdir(exist_ok=True)
    with SessionLocal() as db:
        sessions = list(db.scalars(select(MeasurementSession)))
        assert len(sessions) == 10 and all(
            row.metadata_json.get("synthetic") for row in sessions
        )
        interrupted = next(
            row for row in sessions if row.metadata_json["scenario"] == "disconnect"
        )
        missing = db.scalar(
            select(func.count())
            .select_from(ElectricalSample)
            .where(
                ElectricalSample.session_id == interrupted.id,
                ElectricalSample.received_timestamp
                >= interrupted.started_at + timedelta(seconds=600),
                ElectricalSample.received_timestamp
                < interrupted.started_at + timedelta(seconds=660),
            )
        )
        assert missing == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(SystemEvent)
                .where(
                    SystemEvent.session_id == interrupted.id,
                    SystemEvent.category.in_(["disconnected", "reconnected"]),
                )
            )
            == 4
        )
        for scenario in ("power", "thermal", "disconnect"):
            row = next(
                item for item in sessions if item.metadata_json["scenario"] == scenario
            )
            request = PeriodReportRequest(
                start=row.started_at.replace(tzinfo=__import__("datetime").UTC),
                end=row.ended_at.replace(tzinfo=__import__("datetime").UTC),
                session_ids=[row.id],
            )
            data = PeriodReportDataService(db).collect(request)
            for kind, render in (
                ("pdf", render_period_pdf),
                ("xlsx", render_period_xlsx),
                ("csv", render_period_csv),
            ):
                content = render(data, request)
                (output / f"DEMO-{scenario}.{kind}").write_bytes(content)
                results.append(
                    {"scenario": scenario, "format": kind, "bytes": len(content)}
                )
    (directory / "verification.json").write_text(
        json.dumps(
            {
                "sessions": 10,
                "gap_has_no_samples": True,
                "external_publication_disabled": True,
                "exports": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"DEMO verification passed: {directory / 'verification.json'}")


if __name__ == "__main__":
    main()
