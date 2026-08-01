import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api.routes import router
from app.core.config import get_settings
from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.models.entities import AlertRule, ChannelConfiguration, Device, User
from app.services.acquisition import acquisition_service

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def seed_database() -> None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == settings.demo_admin_email))
        if not user:
            user = User(
                name="Administrador Demo",
                email=settings.demo_admin_email,
                password_hash=hash_password(settings.demo_admin_password),
                role="admin",
            )
            db.add(user)
        device = db.scalar(select(Device).where(Device.name == "Aquisitor simulado"))
        if not device:
            device = Device(
                name="Aquisitor simulado",
                manufacturer="ThermoPower Labs",
                model="Virtual DAQ 16",
                serial_number="SIM-0001",
                connection_type="simulator",
                protocol="simulator",
            )
            db.add(device)
            db.flush()
            names = ["Entrada", "Saída", "Carcaça", "Ambiente", "Resistência", "Dissipador"]
            colors = ["#3B82F6", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6", "#06B6D4"]
            for channel in range(1, 17):
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
        db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    seed_database()
    yield
    for device_id in list(acquisition_service.runtimes):
        await acquisition_service.disconnect(device_id)


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
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "status": 422,
                "message": "Dados de entrada inválidos",
                "details": exc.errors(),
            }
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logging.getLogger(__name__).exception("Unhandled application error", exc_info=exc)
    return JSONResponse(
        status_code=500, content={"error": {"status": 500, "message": "Erro interno inesperado"}}
    )
