import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from app.api.routes import router
from app.core.config import get_settings
from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.models.entities import AlertRule, ChannelConfiguration, Device, User
from app.services.acquisition import acquisition_service
from app.services.device_policy import invalidate_stale_at4532_verification
from app.services.protocol_probe import protocol_probe_service
from app.services.serial_diagnostic import real_serial_diagnostic_service
from app.services.usb_discovery import usb_discovery_service

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def seed_database() -> None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == settings.demo_admin_email))
        if not user:
            if not settings.demo_admin_password:
                raise RuntimeError(
                    "Configure THERMOPOWER_DEMO_ADMIN_PASSWORD para criar o administrador inicial"
                )
            user = User(
                name=settings.initial_admin_name,
                email=settings.demo_admin_email,
                password_hash=hash_password(settings.demo_admin_password),
                role="admin",
            )
            db.add(user)
        elif settings.environment == "client-preview" and user.name == "Administrador Demo":
            user.name = settings.initial_admin_name
        simulator_enabled = settings.environment in {"development", "test"}
        device = db.scalar(select(Device).where(Device.name == "Aquisitor simulado"))
        if simulator_enabled and not device:
            device = Device(
                name="Aquisitor simulado",
                manufacturer="ThermoPower Labs",
                model="Virtual DAQ 32",
                serial_number="SIM-0001",
                connection_type="simulator",
                protocol="simulator",
            )
            db.add(device)
            db.flush()
            names = ["Entrada", "Saída", "Carcaça", "Ambiente", "Resistência", "Dissipador"]
            colors = ["#3B82F6", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6", "#06B6D4"]
            for channel in range(1, 33):
                db.add(
                    ChannelConfiguration(
                        device_id=device.id,
                        channel=channel,
                        name=names[channel - 1] if channel <= len(names) else f"Termopar {channel}",
                        enabled=channel <= 8,
                        warning_limit=70,
                        critical_limit=80,
                        color=colors[(channel - 1) % len(colors)],
                    )
                )
            db.add_all(
                [
                    AlertRule(
                        device_id=device.id,
                        metric="power",
                        operator=">",
                        threshold=2000,
                        severity="critical",
                        cooldown_seconds=10,
                    ),
                    AlertRule(
                        device_id=device.id,
                        metric="temperature",
                        operator=">",
                        threshold=80,
                        severity="critical",
                        cooldown_seconds=10,
                    ),
                ]
            )
        at4532 = db.scalar(select(Device).where(Device.name == "Applent AT4532 · LAB"))
        if not at4532:
            at4532 = Device(
                name="Applent AT4532 · LAB",
                manufacturer="Applent Instruments",
                model="AT4532",
                connection_type="serial",
                port="COM5",
                baud_rate=19200,
                protocol="at4532_serial",
                metadata_json={
                    "usb": {
                        "vid": 0x1A86,
                        "pid": 0x7523,
                        "manual_confirmed": True,
                        "confirmed_port": "COM5",
                        "confirmed_at": "2026-08-10",
                        "driver": "CH341/CH340",
                    },
                    "serial": {
                        "data_bits": 8,
                        "parity": "N",
                        "stop_bits": 1,
                        "timeout_s": 1,
                        "read_timeout_s": 2,
                        "line_terminator": "LF (0x0A)",
                        "framing": "SCPI ASCII TX; ASCII simple or TCP-32 CP936 RX",
                        "parameters_source": "vendor_documented",
                    },
                    "expected_interval_ms": 3000,
                    "channel_count": 32,
                    "protocol_status": "vendor_documented_physical_validation_pending",
                    "physical_validation": "pending",
                },
            )
            db.add(at4532)
            db.flush()
            colors = ["#3B82F6", "#10B981", "#F59E0B", "#EF4444"]
            for channel in range(1, 33):
                db.add(
                    ChannelConfiguration(
                        device_id=at4532.id,
                        channel=channel,
                        name=f"Canal {channel}",
                        enabled=True,
                        color=colors[(channel - 1) % len(colors)],
                    )
                )
        at_metadata = dict(at4532.metadata_json or {})
        at_protocol_status = (
            "verified_by_measurement"
            if at_metadata.get("protocol_status") == "verified_by_measurement"
            else "vendor_documented_physical_validation_pending"
        )
        at_metadata.update(
            {
                "serial": {
                    "data_bits": 8,
                    "parity": "N",
                    "stop_bits": 1,
                    "timeout_s": 1,
                    "read_timeout_s": 2,
                    "line_terminator": "LF (0x0A)",
                    "framing": "SCPI ASCII TX; ASCII simple or TCP-32 CP936 RX",
                    "parameters_source": "vendor_documented",
                },
                "expected_interval_ms": 3000,
                "channel_count": 32,
                "protocol_status": at_protocol_status,
                "physical_validation": "pending",
            }
        )
        at4532.metadata_json = at_metadata
        at4532.baud_rate = 19200
        invalidate_stale_at4532_verification(at4532)
        gpm8213 = db.scalar(select(Device).where(Device.serial_number == "GES913349"))
        if not gpm8213:
            gpm8213 = Device(
                name="GW Instek GPM-8213 · LAB",
                manufacturer="GW Instek",
                model="GPM-8213",
                serial_number="GES913349",
                connection_type="serial",
                port=None,
                baud_rate=None,
                protocol="gpm8213_serial",
                metadata_json={
                    "usb": {
                        "vid": 0x2184,
                        "pid": 0x0052,
                        "serial_number": "GES913349",
                        "driver": "usbser",
                    },
                    "serial": {
                        "data_bits": 8,
                        "parity": "N",
                        "stop_bits": 1,
                        "timeout_s": 1,
                        "read_timeout_s": 2,
                        "line_terminator": "CR+LF (0x0D 0x0A)",
                        "framing": "SCPI ASCII over USB CDC",
                        "parameters_source": "vendor_documented",
                    },
                    "expected_interval_ms": 1000,
                    "protocol_status": "vendor_documented_physical_validation_pending",
                    "physical_validation": "pending",
                },
            )
            db.add(gpm8213)
        gpm_metadata = dict(gpm8213.metadata_json or {})
        gpm_metadata.update(
            {
                "serial": {
                    "data_bits": 8,
                    "parity": "N",
                    "stop_bits": 1,
                    "timeout_s": 1,
                    "read_timeout_s": 2,
                    "line_terminator": "CR+LF (0x0D 0x0A)",
                    "framing": "SCPI ASCII over USB CDC",
                    "parameters_source": "vendor_documented",
                    "baud_relevance": "not_specified_for_usb_cdc",
                },
                "expected_interval_ms": 1000,
                "protocol_status": "vendor_documented_physical_validation_pending",
                "physical_validation": "pending",
            }
        )
        gpm8213.metadata_json = gpm_metadata
        db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    logging.getLogger(__name__).info(
        "startup version=%s environment=%s", settings.app_version, settings.environment
    )
    Base.metadata.create_all(engine)
    seed_database()
    yield
    usb_discovery_service.shutdown()
    await protocol_probe_service.shutdown()
    await real_serial_diagnostic_service.shutdown()
    for device_id in list(acquisition_service.runtimes):
        try:
            await acquisition_service.disconnect(device_id)
        except Exception:
            logging.getLogger(__name__).exception(
                "shutdown failed for acquisition device_id=%s", device_id
            )
    acquisition_service.last_connection_results.clear()
    logging.getLogger(__name__).info("shutdown complete")
    for handler in logging.getLogger().handlers:
        handler.flush()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="API de aquisição, monitoramento e rastreabilidade do ThermoPower Monitor.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


def _frontend_directory() -> Path | None:
    candidates = []
    if settings.frontend_dist:
        candidates.append(Path(settings.frontend_dist))
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys._MEIPASS) / "frontend")
    candidates.append(Path(__file__).resolve().parents[2] / "frontend" / "dist")
    return next((path for path in candidates if (path / "index.html").is_file()), None)


frontend_directory = _frontend_directory()
if frontend_directory and (frontend_directory / "assets").is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=frontend_directory / "assets"),
        name="frontend-assets",
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": settings.app_version}


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"status": exc.status_code, "message": exc.detail}},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = exc.errors()
    for detail in details:
        if "ctx" in detail:
            detail["ctx"] = {key: str(value) for key, value in detail["ctx"].items()}
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "status": 422,
                "message": "Dados de entrada inválidos",
                "details": details,
            }
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logging.getLogger(__name__).exception("Unhandled application error", exc_info=exc)
    return JSONResponse(
        status_code=500, content={"error": {"status": 500, "message": "Erro interno inesperado"}}
    )


if frontend_directory:

    @app.get("/{spa_path:path}", include_in_schema=False)
    def serve_frontend(spa_path: str) -> FileResponse:
        candidate = (frontend_directory / spa_path).resolve()
        if candidate.is_file() and frontend_directory.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(frontend_directory / "index.html")
