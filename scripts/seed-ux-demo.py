"""Deterministic UX fixtures, explicitly limited to local development/test databases."""

from __future__ import annotations

import json
import math
import os
import secrets
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SEED_KEY = "thermopower_ux_demo_v1"
START = datetime(2026, 9, 1, 13, 0, tzinfo=UTC)
DEVICE_NAMES = ("ThermoPower Simulator — GPM", "ThermoPower Simulator — AT4532")
COLORS = (
    "#2563EB",
    "#059669",
    "#D97706",
    "#DC2626",
    "#7C3AED",
    "#0891B2",
    "#DB2777",
    "#475569",
)
CHANNEL_NAMES = (
    "Entrada de ar",
    "Saída de ar",
    "Carcaça superior",
    "Carcaça lateral",
    "Resistência",
    "Painel frontal",
    "Cabo de alimentação",
    "Ambiente",
)
SCENARIOS = (
    ("warmup", "Aquecimento e estabilização", 1200, 5, "finished", "both"),
    ("cycling", "Ciclos de termostato", 1800, 5, "finished", "both"),
    ("peak", "Pico térmico e alertas", 1200, 5, "finished", "both"),
    ("gap", "Lacuna térmica e sensor aberto", 1200, 5, "finished", "both"),
    ("thermal", "Somente temperatura", 900, 5, "finished", "temperature"),
    ("cancelled", "Ensaio cancelado pelo operador", 300, 5, "cancelled", "both"),
    ("long", "Ensaio longo de uma hora", 3600, 1, "finished", "both"),
)


def validate_target(environment: str, database_url: str) -> str:
    """Fail before connecting; a production URL cannot be selected accidentally."""
    from sqlalchemy.engine import make_url

    if getattr(sys, "frozen", False) or environment not in {"development", "test"}:
        raise ValueError(
            "Seed UX permitido exclusivamente em development/test; nada foi alterado."
        )
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite":
        if url.database in {None, "", ":memory:"}:
            if environment != "test":
                raise ValueError(
                    "Use um banco SQLite local persistente para a auditoria UX."
                )
            return database_url
        path = Path(url.database)
        path = (BACKEND / path).resolve() if not path.is_absolute() else path.resolve()
        if not any(path.is_relative_to(root) for root in (BACKEND, ROOT / "build")):
            raise ValueError(
                "O banco do seed deve ficar em backend/ ou build/ deste repositório."
            )
        return url.set(database=str(path)).render_as_string(hide_password=False)
    if url.get_backend_name() == "postgresql":
        if url.host not in {"localhost", "127.0.0.1", "::1"} or not (
            url.database or ""
        ).endswith(("_dev", "_test")):
            raise ValueError(
                "PostgreSQL: use localhost e banco terminado em _dev ou _test."
            )
        return database_url
    raise ValueError("Banco não suportado para demonstração UX.")


def thermal_value(
    scenario: str, seconds: int, channel: int
) -> tuple[float | None, str]:
    if channel <= 24 or (scenario == "gap" and channel == 27 and seconds >= 450):
        return None, "open_sensor"
    ambient = 23.5 + 0.12 * math.sin(seconds / 110)
    if channel == 32:
        return round(ambient, 2), "good"
    target = (43, 65, 52, 49, 78, 39, 35)[channel - 25]
    value = ambient + (target - 23.5) * (1 - math.exp(-seconds / 180))
    value += 0.15 * math.sin(seconds / 31 + channel)
    if scenario == "cycling":
        value += 1.2 * math.sin(seconds * math.tau / 180)
    if scenario == "peak" and channel == 29:
        value += 28 * math.exp(-(((seconds - 750) / 65) ** 2))
    return round(value, 2), "good"


def electrical_values(scenario: str, seconds: int) -> dict:
    voltage = 220 + 1.2 * math.sin(seconds / 47)
    on = (seconds // 90) % 2 == 0
    power = 1180 if seconds < 360 or on else 320
    power += 7 * math.sin(seconds / 19)
    if scenario == "peak":
        power += 380 * math.exp(-(((seconds - 690) / 30) ** 2))
    factor = 0.97 + 0.005 * math.sin(seconds / 53)
    apparent = power / factor
    return {
        "voltage_v": round(voltage, 3),
        "current_a": round(apparent / voltage, 5),
        "active_power_w": round(power, 3),
        "apparent_power_va": round(apparent, 3),
        "reactive_power_var": round(math.sqrt(apparent**2 - power**2), 3),
        "power_factor": round(factor, 5),
        "voltage_frequency_hz": 60.0,
        "current_frequency_hz": 60.0,
    }


def seed_demo(db, user, *, environment: str) -> dict:
    """Insert only owned synthetic records; commit is the caller's responsibility."""
    from sqlalchemy import func, insert, or_, select

    from app.models.entities import (
        AlertEvent,
        AlertRule,
        ChannelConfiguration,
        ChannelProfile,
        ChannelProfileValue,
        Device,
        ElectricalSample,
        MeasurementSession,
        SessionChannelConfiguration,
        SessionDevice,
        SystemEvent,
        TemperatureChannelValue,
        TemperatureSample,
    )

    if environment not in {"development", "test"}:
        raise ValueError("Seed UX permitido exclusivamente em development/test.")
    devices = []
    for name, role in zip(DEVICE_NAMES, ("electrical", "temperature"), strict=True):
        serial_number = f"UX-DEMO-V1-{role.upper()}"
        matches = list(
            db.scalars(
                select(Device).where(
                    or_(
                        Device.serial_number == serial_number,
                        Device.name == name,
                    )
                )
            )
        )
        if matches:
            if len(matches) != 1 or any(
                item.metadata_json.get("seed") != SEED_KEY
                or item.protocol != "simulator"
                or item.connection_type != "simulator"
                or item.port is not None
                or item.baud_rate is not None
                for item in matches
            ):
                raise ValueError(f"Cadastro conflitante preservado: {name}.")
            device = matches[0]
        else:
            device = Device(
                name=name,
                manufacturer="ThermoPower Simulator",
                model=f"UX {role}",
                serial_number=serial_number,
                protocol="simulator",
                connection_type="simulator",
                port=None,
                baud_rate=None,
                active=True,
                created_at=START,
                updated_at=START,
                metadata_json={
                    "seed": SEED_KEY,
                    "synthetic": True,
                    "source_role": role,
                    "expected_interval_ms": 1000,
                },
            )
            db.add(device)
            db.flush()
        devices.append(device)
    electrical, thermal = devices
    channel_settings = []
    for channel in range(1, 33):
        settings = {
            "channel": channel,
            "name": CHANNEL_NAMES[channel - 25]
            if channel >= 25
            else f"Termopar {channel:02d}",
            "enabled": channel >= 25,
            "sensor_type": "K",
            "unit": "°C",
            "correction_offset": 0,
            "warning_limit": 85,
            "critical_limit": 100,
            "color": COLORS[(channel - 1) % len(COLORS)],
            "display_order": channel,
            "description": "Canal sintético para auditoria UX/UI.",
            "physical_location": "Bancada virtual",
        }
        channel_settings.append(settings)
        if (
            db.scalar(
                select(ChannelConfiguration.id).where(
                    ChannelConfiguration.device_id == thermal.id,
                    ChannelConfiguration.channel == channel,
                )
            )
            is None
        ):
            db.add(ChannelConfiguration(device_id=thermal.id, **settings))
    profile_name = "DEMO UX — Oito termopares ativos"
    if (
        db.scalar(select(ChannelProfile.id).where(ChannelProfile.name == profile_name))
        is None
    ):
        profile = ChannelProfile(
            name=profile_name,
            description="Perfil sintético UX/UI.",
            created_by=user.id,
            created_at=START,
        )
        profile.channels = [
            ChannelProfileValue(channel=s["channel"], settings=s)
            for s in channel_settings
        ]
        db.add(profile)
    rules = {}
    for severity, threshold in (("warning", 85), ("critical", 100)):
        rule = db.scalar(
            select(AlertRule).where(
                AlertRule.device_id == thermal.id,
                AlertRule.metric == "temperature",
                AlertRule.channel == 29,
                AlertRule.severity == severity,
                AlertRule.threshold == threshold,
            )
        )
        if rule is None:
            rule = AlertRule(
                device_id=thermal.id,
                metric="temperature",
                channel=29,
                severity=severity,
                threshold=threshold,
                cooldown_seconds=60,
            )
            db.add(rule)
            db.flush()
        rules[severity] = rule

    created = 0
    sessions = []
    for day, (scenario, title, duration, interval, status, role) in enumerate(
        SCENARIOS
    ):
        source_cadence = {str(thermal.id): interval * 1000}
        if role == "both":
            source_cadence[str(electrical.id)] = interval * 1000
        name = f"DEMO UX — {title}"
        existing = list(
            db.scalars(
                select(MeasurementSession).where(
                    MeasurementSession.device_id == thermal.id,
                    MeasurementSession.name == name,
                )
            )
        )
        if existing:
            if len(existing) != 1 or existing[0].metadata_json.get("seed") != SEED_KEY:
                raise ValueError(f"Sessão conflitante preservada: {name}.")
            if "source_cadence_ms" not in existing[0].metadata_json:
                existing[0].metadata_json = {
                    **existing[0].metadata_json,
                    "source_cadence_ms": source_cadence,
                }
            sessions.append(existing[0])
            continue
        start = START + timedelta(days=day)
        session = MeasurementSession(
            device_id=thermal.id,
            user_id=user.id,
            name=name,
            status=status,
            started_at=start,
            ended_at=start + timedelta(seconds=duration, milliseconds=150),
            created_at=start,
            sample_interval_ms=interval * 1000,
            acquisition_mode="live",
            sync_grid_ms=interval * 1000,
            sync_tolerance_ms=1500,
            description="Dados sintéticos determinísticos; nenhum equipamento físico utilizado.",
            notes="Demonstração UX/UI. Não representa medição ou validação física.",
            metadata_json={
                "seed": SEED_KEY,
                "synthetic": True,
                "scenario": scenario,
                "source_cadence_ms": source_cadence,
                "product": "Forno elétrico de bancada",
                "model": "Virtual 1200 W",
                "sample": f"UX-{day + 1:02d}",
                "code": f"UX-2026-{day + 1:03d}",
            },
        )
        db.add(session)
        db.flush()
        db.add(
            SessionDevice(
                session_id=session.id, device_id=thermal.id, role="temperature", created_at=start
            )
        )
        if role == "both":
            db.add(
                SessionDevice(
                    session_id=session.id, device_id=electrical.id, role="electrical", created_at=start
                )
            )
        db.add_all(
            SessionChannelConfiguration(session_id=session.id, **s)
            for s in channel_settings
        )
        thermal_rows, electric_rows, channel_rows = [], [], []
        for index, seconds in enumerate(range(0, duration + 1, interval), 1):
            timestamp = start + timedelta(seconds=seconds)
            if role == "both":
                values = electrical_values(scenario, seconds)
                original_unit = ("mW", "W", "kW")[(index // 60) % 3]
                factor = {"mW": 0.001, "W": 1, "kW": 1000}[original_unit]
                electric_rows.append(
                    {
                        "session_id": session.id,
                        "device_id": electrical.id,
                        "device_timestamp": timestamp,
                        "received_timestamp": timestamp,
                        "created_at": timestamp,
                        "sequence": index,
                        "source": "ux_demo",
                        "quality": "good",
                        **values,
                        "original_values": {
                            "active_power": values["active_power_w"] / factor
                        },
                        "original_units": {"active_power": original_unit},
                        "raw_payload": {"seed": SEED_KEY, "synthetic": True},
                    }
                )
            # Only the thermal source has a gap; no old values are copied into missing samples.
            if scenario == "gap" and 600 <= seconds < 630:
                continue
            received = timestamp + timedelta(milliseconds=150)
            sample = TemperatureSample(
                session_id=session.id,
                device_id=thermal.id,
                device_timestamp=timestamp,
                received_timestamp=received,
                created_at=received,
                sequence=index,
                source="ux_demo",
                quality="good",
                ambient_temperature_c=23.5,
                raw_payload={"seed": SEED_KEY, "synthetic": True},
            )
            thermal_rows.append((sample, seconds))
        if electric_rows:
            db.execute(insert(ElectricalSample), electric_rows)
        db.add_all(sample for sample, _ in thermal_rows)
        db.flush()
        for sample, seconds in thermal_rows:
            for channel in range(1, 33):
                value, quality = thermal_value(scenario, seconds, channel)
                channel_rows.append(
                    {
                        "sample_id": sample.id,
                        "channel": channel,
                        "temperature_c": value,
                        "original_value": value,
                        "original_unit": "°C",
                        "quality": quality,
                    }
                )
        for offset in range(0, len(channel_rows), 4000):
            db.execute(
                insert(TemperatureChannelValue), channel_rows[offset : offset + 4000]
            )
        db.add(
            SystemEvent(
                device_id=thermal.id,
                session_id=session.id,
                timestamp=start,
                category="session",
                level="info",
                message=f"Demonstração sintética: {title}.",
                details={"seed": SEED_KEY, "synthetic": True},
            )
        )
        if scenario == "gap":
            db.add(
                SystemEvent(
                    device_id=thermal.id,
                    session_id=session.id,
                    timestamp=start + timedelta(seconds=600),
                    category="read_error",
                    level="warning",
                    message="Lacuna térmica sintética de 30 segundos; fonte elétrica preservada.",
                    details={"seed": SEED_KEY, "synthetic": True, "gap_seconds": 30},
                )
            )
        if scenario == "peak":
            for severity, seconds in (("warning", 690), ("critical", 750)):
                acknowledged = severity == "warning"
                db.add(
                    AlertEvent(
                        session_id=session.id,
                        rule_id=rules[severity].id,
                        timestamp=start + timedelta(seconds=seconds),
                        metric="temperature",
                        channel=29,
                        measured_value=thermal_value(scenario, seconds, 29)[0],
                        threshold=rules[severity].threshold,
                        severity=severity,
                        acknowledged=acknowledged,
                        acknowledged_by=user.id if acknowledged else None,
                        acknowledged_at=start + timedelta(seconds=seconds + 10)
                        if acknowledged
                        else None,
                        notes="Alerta sintético para auditoria UX/UI.",
                    )
                )
        sessions.append(session)
        created += 1
    db.flush()
    ids = [session.id for session in sessions]
    counts = {
        label: db.scalar(
            select(func.count()).select_from(model).where(model.session_id.in_(ids))
        )
        for label, model in (
            ("electrical_samples", ElectricalSample),
            ("temperature_samples", TemperatureSample),
            ("alerts", AlertEvent),
        )
    }
    return {
        "seed": SEED_KEY,
        "created_sessions": created,
        "devices": [{"id": d.id, "name": d.name, "port": d.port} for d in devices],
        "sessions": [{"id": s.id, "name": s.name} for s in sessions],
        **counts,
        "period_utc": [START.isoformat(), (START + timedelta(days=7)).isoformat()],
    }


def main() -> int:
    sys.path.insert(0, str(BACKEND))
    os.chdir(BACKEND)  # Same .env and relative SQLite path as the development API.
    from sqlalchemy import create_engine, event, inspect
    from sqlalchemy.orm import Session

    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from app.core.config import Settings

    settings = Settings()
    database_url = validate_target(settings.environment, settings.database_url)
    engine = create_engine(database_url)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    try:
        # Migrate only an empty database. Existing physical registrations are never migrated here.
        if not inspect(engine).get_table_names():
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=BACKEND,
                check=True,
                env={**os.environ, "THERMOPOWER_DATABASE_URL": database_url},
            )
        config = Config(str(BACKEND / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND / "alembic"))
        with engine.connect() as connection:
            if set(MigrationContext.configure(connection).get_current_heads()) != set(
                ScriptDirectory.from_config(config).get_heads()
            ):
                raise ValueError(
                    "Banco existente desatualizado; aplique as migrations antes do seed."
                )
        from sqlalchemy import select

        from app.core.security import hash_password
        from app.models.entities import User

        generated_password = None
        with Session(engine) as db, db.begin():
            user = db.scalar(
                select(User).where(User.email == settings.demo_admin_email)
            )
            if user is None:
                password = settings.demo_admin_password
                if not password:
                    generated_password = password = secrets.token_urlsafe(24)
                user = User(
                    name="Administrador de auditoria UX",
                    email=settings.demo_admin_email,
                    password_hash=hash_password(password),
                    role="admin",
                    active=True,
                    created_at=START,
                    updated_at=START,
                )
                db.add(user)
                db.flush()
            elif not user.active:
                raise ValueError(
                    "Administrador local inativo; nenhum usuário foi alterado."
                )
            result = seed_demo(db, user, environment=settings.environment)
        if generated_password:
            access_file = ROOT / "build" / "ux-demo-access.txt"
            access_file.parent.mkdir(parents=True, exist_ok=True)
            access_file.write_text(
                f"Email: {settings.demo_admin_email}\nSenha: {generated_password}\n",
                encoding="utf-8",
            )
            print(f"Credenciais locais geradas: {access_file}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print(
            "Seed concluído. Abra Sessões e procure DEMO UX; período: 01 a 07/09/2026."
        )
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, subprocess.CalledProcessError) as exc:
        print(f"Seed não executado: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
