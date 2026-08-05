import asyncio
import io
import shutil
import time
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import Float, Integer, cast, delete, func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from app.adapters.simulator import SCENARIOS
from app.api.deps import get_current_user, require_roles
from app.core.config import get_settings
from app.core.database import engine, get_db
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    login_rate_limiter,
    verify_password,
)
from app.importers import At4532XlsxImporter, Gpm8213TxtImporter
from app.models.entities import (
    AlertEvent,
    AlertRule,
    ChannelConfiguration,
    ChannelProfile,
    ChannelProfileValue,
    Device,
    ElectricalSample,
    Measurement,
    MeasurementSession,
    Report,
    SessionChannelConfiguration,
    SessionDevice,
    SystemEvent,
    TemperatureChannelValue,
    TemperatureMeasurement,
    TemperatureSample,
    User,
)
from app.schemas.contracts import (
    AlertRuleInput,
    ChannelInput,
    ChannelProfileCreate,
    DeviceInput,
    LoginRequest,
    PeriodReportRequest,
    SessionCreate,
    SimulatorConfigInput,
    TokenResponse,
    UsbAssociationRequest,
    UserCreate,
    UserRead,
)
from app.services.acquisition import acquisition_service
from app.services.imports import create_import_session
from app.services.period_documents import (
    render_period_chart,
    render_period_pdf,
    safe_report_filename,
)
from app.services.period_reporting import PeriodReportDataService
from app.services.reporting import create_chart_image, create_csv, create_pdf, create_xlsx
from app.services.statistics import executive_statistics, session_statistics
from app.services.synchronization import synchronized_series
from app.services.usb_discovery import usb_discovery_service
from app.services.websocket import websocket_hub

router = APIRouter(prefix="/api/v1")
settings = get_settings()
Db = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


async def _safe_upload(upload: UploadFile, extension: str) -> bytes:
    filename = (upload.filename or "").replace("\\", "/").split("/")[-1]
    if not filename.lower().endswith(extension):
        raise HTTPException(status_code=415, detail=f"Envie um arquivo {extension.upper()}")
    payload = await upload.read(settings.max_upload_bytes + 1)
    if len(payload) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="Arquivo excede o limite permitido")
    if not payload:
        raise HTTPException(status_code=422, detail="Arquivo vazio")
    return payload


def _session_device_ids(db: Session, session: MeasurementSession) -> list[int]:
    ids = list(
        db.scalars(select(SessionDevice.device_id).where(SessionDevice.session_id == session.id))
    )
    return ids or [session.device_id]


def _page(items: list, total: int, page: int, page_size: int) -> dict:
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": (total + page_size - 1) // page_size,
    }


def _orm_dict(item: object) -> dict:
    return {column.key: getattr(item, column.key) for column in item.__table__.columns}


def _duration_seconds(start: datetime, end: datetime | None) -> float:
    actual_end = end or datetime.now(UTC)
    normalized_start = start if start.tzinfo else start.replace(tzinfo=UTC)
    normalized_end = actual_end if actual_end.tzinfo else actual_end.replace(tzinfo=UTC)
    return max(0, (normalized_end - normalized_start).total_seconds())


def _device_dict(device: Device) -> dict:
    return {
        "id": device.id,
        "name": device.name,
        "manufacturer": device.manufacturer,
        "model": device.model,
        "serial_number": device.serial_number,
        "connection_type": device.connection_type,
        "port": device.port,
        "baud_rate": device.baud_rate,
        "protocol": device.protocol,
        "active": device.active,
        "metadata": device.metadata_json,
        "last_connected_at": device.last_connected_at,
        "created_at": device.created_at,
    }


@router.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Db) -> TokenResponse:
    key = f"{request.client.host if request.client else 'unknown'}:{payload.email.lower()}"
    login_rate_limiter.check(key, time.monotonic())
    user = db.scalar(select(User).where(func.lower(User.email) == payload.email.lower()))
    if not user or not user.active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="E-mail ou senha inválidos")
    login_rate_limiter.clear(key)
    db.add(SystemEvent(level="info", category="login", message=f"Login de {user.email}"))
    db.commit()
    return TokenResponse(
        access_token=create_access_token(str(user.id), user.role),
        expires_in=settings.access_token_minutes * 60,
        user={"id": user.id, "name": user.name, "email": user.email, "role": user.role},
    )


@router.get("/auth/me", response_model=UserRead)
def me(user: CurrentUser) -> User:
    return user


@router.get("/users", response_model=list[UserRead])
def list_users(db: Db, _: User = Depends(require_roles("admin"))) -> list[User]:
    return list(db.scalars(select(User).order_by(User.name)))


@router.post("/users", response_model=UserRead, status_code=201)
def create_user(payload: UserCreate, db: Db, _: User = Depends(require_roles("admin"))) -> User:
    if db.scalar(select(User).where(func.lower(User.email) == payload.email.lower())):
        raise HTTPException(status_code=409, detail="E-mail já cadastrado")
    user = User(
        name=payload.name,
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/devices")
def list_devices(db: Db, _: CurrentUser) -> list[dict]:
    return [
        _device_dict(device)
        for device in db.scalars(
            select(Device).where(Device.active.is_(True)).order_by(Device.name)
        )
    ]


@router.post("/devices", status_code=201)
def create_device(payload: DeviceInput, db: Db, _: User = Depends(require_roles("admin"))) -> dict:
    device = Device(
        name=payload.name,
        manufacturer=payload.manufacturer,
        model=payload.model,
        serial_number=payload.serial_number,
        connection_type=payload.connection_type,
        port=payload.port,
        baud_rate=payload.baud_rate,
        protocol=payload.protocol,
        active=payload.active,
        metadata_json=payload.metadata,
    )
    db.add(device)
    db.flush()
    colors = ["#3667E9", "#16A66A", "#F39B22", "#DF5668", "#7857D8", "#1FA7BD"]
    for channel in range(1, 33):
        db.add(
            ChannelConfiguration(
                device_id=device.id,
                channel=channel,
                name=f"Termopar {channel}",
                enabled=channel <= 8,
                color=colors[(channel - 1) % len(colors)],
            )
        )
    db.commit()
    db.refresh(device)
    return _device_dict(device)


@router.get("/device-ports")
def list_device_ports(db: Db, _: CurrentUser) -> list[dict]:
    return usb_discovery_service.discover(db, _active_device_ports(db))


def _active_device_ports(db: Session) -> set[str]:
    device_ids = list(acquisition_service.runtimes)
    if not device_ids:
        return set()
    return {
        port for port in db.scalars(select(Device.port).where(Device.id.in_(device_ids))) if port
    }


@router.get("/hardware/discovery")
def discover_hardware(db: Db, _: CurrentUser) -> list[dict]:
    return usb_discovery_service.discover(db, _active_device_ports(db))


@router.post("/hardware/discovery/associate")
def associate_discovered_hardware(
    payload: UsbAssociationRequest,
    db: Db,
    _: User = Depends(require_roles("admin", "operator")),
) -> dict:
    try:
        return usb_discovery_service.associate(db, payload.port, payload.device_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/devices/{device_id}")
def update_device(
    device_id: int, payload: DeviceInput, db: Db, _: User = Depends(require_roles("admin"))
) -> dict:
    device = db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Equipamento não encontrado")
    for field, value in payload.model_dump(exclude={"metadata"}).items():
        setattr(device, field, value)
    device.metadata_json = payload.metadata
    db.commit()
    db.refresh(device)
    return _device_dict(device)


@router.delete("/devices/{device_id}", status_code=204)
def delete_device(device_id: int, db: Db, user: User = Depends(require_roles("admin"))) -> Response:
    device = db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Equipamento não encontrado")
    if device_id in acquisition_service.runtimes:
        raise HTTPException(status_code=409, detail="Desconecte o equipamento antes de remover")
    device.active = False
    db.add(
        SystemEvent(
            device_id=device.id,
            category="configuration",
            message=f"Equipamento arquivado por {user.email}",
        )
    )
    db.commit()
    return Response(status_code=204)


@router.post("/devices/{device_id}/connect")
async def connect_device(
    device_id: int, _: User = Depends(require_roles("admin", "operator"))
) -> dict:
    try:
        return await acquisition_service.connect(device_id)
    except (ValueError, RuntimeError, ConnectionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/devices/{device_id}/disconnect", status_code=204)
async def disconnect_device(
    device_id: int, _: User = Depends(require_roles("admin", "operator"))
) -> Response:
    await acquisition_service.disconnect(device_id)
    return Response(status_code=204)


@router.get("/devices/{device_id}/status")
async def device_status(device_id: int, _: CurrentUser) -> dict:
    return await acquisition_service.status(device_id)


@router.post("/devices/{device_id}/test")
async def test_device_connection(
    device_id: int, _: User = Depends(require_roles("admin", "operator"))
) -> dict:
    was_connected = device_id in acquisition_service.runtimes
    started = time.monotonic()
    stages = [
        {"key": "open_port", "label": "Abrir porta", "status": "pending"},
        {"key": "receive_data", "label": "Receber dados", "status": "pending"},
        {"key": "recognize_format", "label": "Reconhecer formato", "status": "pending"},
        {"key": "inspect_channels", "label": "Inspecionar canais", "status": "pending"},
    ]
    try:
        status = await acquisition_service.connect(device_id)
        stages[0]["status"] = "passed"
        runtime = acquisition_service.runtimes[device_id]
        for _ in range(30):
            if runtime.latest:
                break
            await asyncio.sleep(0.1)
        info = await runtime.adapter.get_device_information()
        adapter_status = await runtime.adapter.get_status()
        received = runtime.latest is not None
        stages[1]["status"] = "passed" if received else "failed"
        stages[2]["status"] = "passed" if received else "not_run"
        stages[3]["status"] = "passed" if received else "not_run"
        return {
            "port_open": adapter_status.connected,
            "data_received": received,
            "format_recognized": received,
            "approximate_frequency_hz": adapter_status.messages_per_second,
            "detected_channels": len(runtime.latest.temperatures_c) if runtime.latest else 0,
            "errors": adapter_status.read_errors,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "information": info.model_dump(mode="json"),
            "status": status,
            "stages": stages,
            "physical_validation": "pending",
        }
    except (ValueError, RuntimeError, ConnectionError, OSError) as exc:
        stages[0]["status"] = "failed"
        stages[0]["message"] = str(exc)
        for stage in stages[1:]:
            stage["status"] = "not_run"
        return {
            "port_open": False,
            "data_received": False,
            "format_recognized": False,
            "approximate_frequency_hz": 0.0,
            "detected_channels": 0,
            "errors": 1,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "stages": stages,
            "physical_validation": "pending",
            "message": str(exc),
        }
    finally:
        if not was_connected:
            await acquisition_service.disconnect(device_id)


@router.get("/devices/{device_id}/channels", response_model=None)
def list_channels(device_id: int, db: Db, _: CurrentUser) -> list[ChannelConfiguration]:
    return list(
        db.scalars(
            select(ChannelConfiguration)
            .where(ChannelConfiguration.device_id == device_id)
            .order_by(ChannelConfiguration.display_order, ChannelConfiguration.channel)
        )
    )


@router.put("/devices/{device_id}/channels/{channel_number}", response_model=None)
def update_channel(
    device_id: int,
    channel_number: int,
    payload: ChannelInput,
    db: Db,
    user: User = Depends(require_roles("admin", "operator")),
) -> ChannelConfiguration:
    if channel_number != payload.channel:
        raise HTTPException(status_code=422, detail="Canal da URL difere do payload")
    channel = db.scalar(
        select(ChannelConfiguration).where(
            ChannelConfiguration.device_id == device_id,
            ChannelConfiguration.channel == channel_number,
        )
    )
    if not channel:
        raise HTTPException(status_code=404, detail="Canal não encontrado")
    for field, value in payload.model_dump().items():
        setattr(channel, field, value)
    db.add(
        SystemEvent(
            device_id=device_id,
            category="configuration",
            message=f"Canal T{channel_number} alterado por {user.email}",
        )
    )
    db.commit()
    db.refresh(channel)
    return channel


@router.get("/channel-profiles")
def list_channel_profiles(db: Db, _: CurrentUser) -> list[dict]:
    profiles = db.scalars(
        select(ChannelProfile)
        .options(selectinload(ChannelProfile.channels))
        .order_by(ChannelProfile.name)
    ).all()
    return [
        {
            "id": profile.id,
            "name": profile.name,
            "description": profile.description,
            "channels": [value.settings for value in profile.channels],
        }
        for profile in profiles
    ]


@router.post("/channel-profiles", status_code=201)
def create_channel_profile(
    payload: ChannelProfileCreate,
    db: Db,
    user: User = Depends(require_roles("admin", "operator")),
) -> dict:
    if db.scalar(select(ChannelProfile).where(ChannelProfile.name == payload.name)):
        raise HTTPException(status_code=409, detail="Já existe um perfil com este nome")
    profile = ChannelProfile(name=payload.name, description=payload.description, created_by=user.id)
    profile.channels = [
        ChannelProfileValue(channel=channel.channel, settings=channel.model_dump())
        for channel in payload.channels
    ]
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return {"id": profile.id, "name": profile.name}


@router.post("/channel-profiles/{profile_id}/apply/{device_id}")
def apply_channel_profile(
    profile_id: int,
    device_id: int,
    db: Db,
    _: User = Depends(require_roles("admin", "operator")),
) -> dict:
    profile = db.scalar(
        select(ChannelProfile)
        .options(selectinload(ChannelProfile.channels))
        .where(ChannelProfile.id == profile_id)
    )
    if not profile or not db.get(Device, device_id):
        raise HTTPException(status_code=404, detail="Perfil ou equipamento não encontrado")
    current = {
        item.channel: item
        for item in db.scalars(
            select(ChannelConfiguration).where(ChannelConfiguration.device_id == device_id)
        )
    }
    for value in profile.channels:
        validated = ChannelInput.model_validate(value.settings)
        channel = current.get(value.channel)
        if channel:
            for key, item in validated.model_dump().items():
                setattr(channel, key, item)
        else:
            db.add(ChannelConfiguration(device_id=device_id, **validated.model_dump()))
    db.commit()
    return {"profile_id": profile_id, "device_id": device_id, "updated": len(profile.channels)}


@router.get("/sessions")
def list_sessions(
    db: Db,
    _: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = None,
    status: str | None = None,
    device_id: int | None = None,
) -> dict:
    conditions = []
    if search:
        conditions.append(
            or_(
                MeasurementSession.name.ilike(f"%{search}%"),
                MeasurementSession.description.ilike(f"%{search}%"),
            )
        )
    if status:
        conditions.append(MeasurementSession.status == status)
    if device_id:
        conditions.append(MeasurementSession.device_id == device_id)
    base = select(MeasurementSession).where(*conditions)
    total = db.scalar(select(func.count()).select_from(MeasurementSession).where(*conditions)) or 0
    sessions = list(
        db.scalars(
            base.options(
                selectinload(MeasurementSession.device), selectinload(MeasurementSession.user)
            )
            .order_by(MeasurementSession.started_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    items = []
    for session in sessions:
        aggregates = db.execute(
            select(func.count(Measurement.id), func.avg(Measurement.power_w)).where(
                Measurement.session_id == session.id
            )
        ).one()
        max_temp = db.scalar(
            select(func.max(TemperatureMeasurement.temperature_c))
            .join(Measurement)
            .where(Measurement.session_id == session.id)
        )
        normalized_max_temp = db.scalar(
            select(func.max(TemperatureChannelValue.temperature_c))
            .join(TemperatureSample)
            .where(TemperatureSample.session_id == session.id)
        )
        electrical_aggregates = db.execute(
            select(
                func.count(ElectricalSample.id), func.avg(ElectricalSample.active_power_w)
            ).where(ElectricalSample.session_id == session.id)
        ).one()
        temperature_count = (
            db.scalar(
                select(func.count())
                .select_from(TemperatureSample)
                .where(TemperatureSample.session_id == session.id)
            )
            or 0
        )
        linked_devices = db.execute(
            select(SessionDevice.role, Device.name)
            .join(Device, Device.id == SessionDevice.device_id)
            .where(SessionDevice.session_id == session.id)
        ).all()
        alert_count = (
            db.scalar(
                select(func.count())
                .select_from(AlertEvent)
                .where(AlertEvent.session_id == session.id)
            )
            or 0
        )
        items.append(
            {
                "id": session.id,
                "name": session.name,
                "description": session.description,
                "status": session.status,
                "device_id": session.device_id,
                "device_name": " + ".join(row[1] for row in linked_devices) or session.device.name,
                "devices": [{"role": row[0], "name": row[1]} for row in linked_devices],
                "operator": session.user.name,
                "started_at": session.started_at,
                "ended_at": session.ended_at,
                "duration_seconds": _duration_seconds(session.started_at, session.ended_at),
                "sample_count": max(aggregates[0], electrical_aggregates[0], temperature_count),
                "electrical_sample_count": electrical_aggregates[0],
                "temperature_sample_count": temperature_count,
                "average_power_w": electrical_aggregates[1] or aggregates[1],
                "maximum_temperature_c": normalized_max_temp
                if normalized_max_temp is not None
                else max_temp,
                "alert_count": alert_count,
                "notes": session.notes,
            }
        )
    return _page(items, total, page, page_size)


@router.post("/sessions", status_code=201)
async def start_session(
    payload: SessionCreate, db: Db, user: User = Depends(require_roles("admin", "operator"))
) -> dict:
    roles: list[tuple[str, int]] = []
    if payload.temperature_device_id:
        roles.append(("temperature", payload.temperature_device_id))
    if payload.electrical_device_id:
        roles.append(("electrical", payload.electrical_device_id))
    if payload.device_id and not roles:
        roles.append(("combined", payload.device_id))
    devices: list[tuple[str, Device]] = []
    for role, device_id in roles:
        device = db.get(Device, device_id)
        if not device or not device.active:
            raise HTTPException(
                status_code=404, detail=f"Equipamento {role} não encontrado ou inativo"
            )
        active = db.scalar(
            select(MeasurementSession)
            .outerjoin(SessionDevice, SessionDevice.session_id == MeasurementSession.id)
            .where(
                or_(
                    MeasurementSession.device_id == device_id, SessionDevice.device_id == device_id
                ),
                MeasurementSession.status.in_(["running", "paused"]),
            )
        )
        if active:
            raise HTTPException(
                status_code=409, detail=f"Já existe uma sessão ativa para {device.name}"
            )
        devices.append((role, device))
    primary_device = devices[0][1]
    values = payload.model_dump(
        exclude={"device_id", "temperature_device_id", "electrical_device_id"}
    )
    session = MeasurementSession(
        **values, device_id=primary_device.id, user_id=user.id, status="running"
    )
    db.add(session)
    db.flush()
    for role, device in devices:
        db.add(SessionDevice(session_id=session.id, device_id=device.id, role=role))
    snapshot_device_id = next(
        (device.id for role, device in devices if role in {"temperature", "combined"}), None
    )
    if snapshot_device_id:
        channels = db.scalars(
            select(ChannelConfiguration).where(ChannelConfiguration.device_id == snapshot_device_id)
        )
        for channel in channels:
            db.add(
                SessionChannelConfiguration(
                    session_id=session.id,
                    source_configuration_id=channel.id,
                    channel=channel.channel,
                    name=channel.name,
                    enabled=channel.enabled,
                    sensor_type=channel.sensor_type,
                    unit=channel.unit,
                    correction_offset=channel.correction_offset,
                    warning_limit=channel.warning_limit,
                    critical_limit=channel.critical_limit,
                    color=channel.color,
                    description=channel.description,
                    physical_location=channel.physical_location,
                    display_order=channel.display_order or channel.channel,
                )
            )
    db.add(
        SystemEvent(
            session_id=session.id,
            device_id=primary_device.id,
            category="session_start",
            message="Sessão iniciada",
        )
    )
    db.commit()
    db.refresh(session)
    attached_device_ids: list[int] = []
    try:
        for _, device in devices:
            await acquisition_service.attach_session(device.id, session.id)
            attached_device_ids.append(device.id)
    except Exception:
        for device_id in attached_device_ids:
            await acquisition_service.detach_session(device_id)
        session.status = "failed"
        session.ended_at = datetime.now(UTC)
        db.commit()
        raise
    return {
        "id": session.id,
        "status": session.status,
        "started_at": session.started_at,
        "devices": [{"role": role, "device": _device_dict(device)} for role, device in devices],
    }


@router.get("/sessions/{session_id}")
def get_session(session_id: int, db: Db, _: CurrentUser) -> dict:
    session = db.scalar(
        select(MeasurementSession)
        .options(selectinload(MeasurementSession.device), selectinload(MeasurementSession.user))
        .where(MeasurementSession.id == session_id)
    )
    if not session:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    device_links = db.scalars(
        select(SessionDevice)
        .options(selectinload(SessionDevice.device))
        .where(SessionDevice.session_id == session_id)
    ).all()
    return {
        "id": session.id,
        "name": session.name,
        "description": session.description,
        "notes": session.notes,
        "status": session.status,
        "started_at": session.started_at,
        "ended_at": session.ended_at,
        "sample_interval_ms": session.sample_interval_ms,
        "sync_grid_ms": session.sync_grid_ms,
        "sync_tolerance_ms": session.sync_tolerance_ms,
        "acquisition_mode": session.acquisition_mode,
        "device": _device_dict(session.device),
        "devices": [
            {"role": link.role, "device": _device_dict(link.device)} for link in device_links
        ]
        or [{"role": "combined", "device": _device_dict(session.device)}],
        "operator": {"id": session.user.id, "name": session.user.name, "email": session.user.email},
        "statistics": session_statistics(db, session_id),
    }


async def _transition(session_id: int, target: str, db: Session) -> MeasurementSession:
    session = db.get(MeasurementSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    allowed = {
        "paused": {"running"},
        "running": {"paused"},
        "finished": {"running", "paused"},
        "cancelled": {"running", "paused"},
    }
    if session.status not in allowed[target]:
        raise HTTPException(
            status_code=409, detail=f"Transição {session.status} → {target} não permitida"
        )
    session.status = target
    device_ids = _session_device_ids(db, session)
    if target == "paused":
        for device_id in device_ids:
            await acquisition_service.pause_session(device_id)
    elif target == "running":
        for device_id in device_ids:
            await acquisition_service.resume_session(device_id, session.id)
    else:
        session.ended_at = datetime.now(UTC)
        for device_id in device_ids:
            await acquisition_service.detach_session(device_id)
    db.add(
        SystemEvent(
            session_id=session.id,
            device_id=session.device_id,
            category=f"session_{target}",
            message=f"Sessão alterada para {target}",
        )
    )
    db.commit()
    return session


@router.post("/sessions/{session_id}/pause")
async def pause_session(
    session_id: int, db: Db, _: User = Depends(require_roles("admin", "operator"))
) -> dict:
    session = await _transition(session_id, "paused", db)
    return {"id": session.id, "status": session.status}


@router.post("/sessions/{session_id}/resume")
async def resume_session(
    session_id: int, db: Db, _: User = Depends(require_roles("admin", "operator"))
) -> dict:
    session = await _transition(session_id, "running", db)
    return {"id": session.id, "status": session.status}


@router.post("/sessions/{session_id}/finish")
async def finish_session(
    session_id: int, db: Db, _: User = Depends(require_roles("admin", "operator"))
) -> dict:
    session = await _transition(session_id, "finished", db)
    return {"id": session.id, "status": session.status, "ended_at": session.ended_at}


@router.post("/sessions/{session_id}/cancel")
async def cancel_session(
    session_id: int, db: Db, _: User = Depends(require_roles("admin", "operator"))
) -> dict:
    session = await _transition(session_id, "cancelled", db)
    return {"id": session.id, "status": session.status}


@router.post("/sessions/{session_id}/duplicate", status_code=201)
def duplicate_session(
    session_id: int, db: Db, user: User = Depends(require_roles("admin", "operator"))
) -> dict:
    source = db.get(MeasurementSession, session_id)
    if not source:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    session = MeasurementSession(
        device_id=source.device_id,
        user_id=user.id,
        name=f"Cópia de {source.name}",
        description=source.description,
        notes=source.notes,
        sample_interval_ms=source.sample_interval_ms,
        acquisition_mode=source.acquisition_mode,
        sync_grid_ms=source.sync_grid_ms,
        sync_tolerance_ms=source.sync_tolerance_ms,
        status="draft",
    )
    db.add(session)
    db.flush()
    links = db.scalars(select(SessionDevice).where(SessionDevice.session_id == source.id)).all()
    for link in links:
        db.add(SessionDevice(session_id=session.id, device_id=link.device_id, role=link.role))
    snapshots = db.scalars(
        select(SessionChannelConfiguration).where(
            SessionChannelConfiguration.session_id == source.id
        )
    ).all()
    for snapshot in snapshots:
        values = _orm_dict(snapshot)
        values.pop("id")
        values["session_id"] = session.id
        db.add(SessionChannelConfiguration(**values))
    db.commit()
    db.refresh(session)
    return {"id": session.id, "status": session.status, "name": session.name}


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: int, db: Db, _: User = Depends(require_roles("admin"))) -> Response:
    session = db.get(MeasurementSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    if session.status in {"running", "paused"}:
        raise HTTPException(status_code=409, detail="Finalize a sessão antes de excluir")
    measurement_ids = select(Measurement.id).where(Measurement.session_id == session_id)
    temperature_sample_ids = select(TemperatureSample.id).where(
        TemperatureSample.session_id == session_id
    )
    db.execute(
        delete(TemperatureMeasurement).where(
            TemperatureMeasurement.measurement_id.in_(measurement_ids)
        )
    )
    db.execute(
        delete(TemperatureChannelValue).where(
            TemperatureChannelValue.sample_id.in_(temperature_sample_ids)
        )
    )
    for model in (
        Measurement,
        TemperatureSample,
        ElectricalSample,
        AlertEvent,
        SessionChannelConfiguration,
        SessionDevice,
    ):
        db.execute(delete(model).where(model.session_id == session_id))
    db.execute(
        update(SystemEvent)
        .where(SystemEvent.session_id == session_id)
        .values(session_id=None)
    )
    db.execute(update(Report).where(Report.session_id == session_id).values(session_id=None))
    db.delete(session)
    db.commit()
    return Response(status_code=204)


@router.get("/measurements")
def list_measurements(
    db: Db,
    _: CurrentUser,
    session_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=250),
    power_min: float | None = None,
    power_max: float | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict:
    conditions = [Measurement.session_id == session_id]
    if power_min is not None:
        conditions.append(Measurement.power_w >= power_min)
    if power_max is not None:
        conditions.append(Measurement.power_w <= power_max)
    if start:
        conditions.append(Measurement.timestamp >= start)
    if end:
        conditions.append(Measurement.timestamp <= end)
    total = db.scalar(select(func.count()).select_from(Measurement).where(*conditions)) or 0
    rows = list(
        db.scalars(
            select(Measurement)
            .options(selectinload(Measurement.temperatures))
            .where(*conditions)
            .order_by(Measurement.timestamp.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    alert_times = set(
        db.scalars(select(AlertEvent.timestamp).where(AlertEvent.session_id == session_id))
    )
    items = []
    for row in rows:
        temperatures = {str(item.channel): item.temperature_c for item in row.temperatures}
        items.append(
            {
                "id": row.id,
                "timestamp": row.timestamp,
                "raw_power": row.raw_power,
                "raw_power_unit": row.raw_power_unit,
                "power_w": row.power_w,
                "quality": row.quality,
                "temperatures": temperatures,
                "has_alert": row.timestamp in alert_times,
            }
        )
    return _page(items, total, page, page_size)


@router.get("/measurements/series")
def measurement_series(
    db: Db,
    _: CurrentUser,
    session_id: int,
    max_points: int = Query(600, ge=10, le=5000),
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict:
    conditions = [Measurement.session_id == session_id]
    if start:
        conditions.append(Measurement.timestamp >= start)
    if end:
        conditions.append(Measurement.timestamp <= end)
    bounds = db.execute(
        select(
            func.min(Measurement.timestamp), func.max(Measurement.timestamp), func.count()
        ).where(*conditions)
    ).one()
    if not bounds[0] or not bounds[1]:
        return {"points": [], "source_count": 0, "downsampled": False}
    duration = max((bounds[1] - bounds[0]).total_seconds(), 0.001)
    bucket_seconds = max(duration / max_points, 0.001)
    if engine.dialect.name == "sqlite":
        epoch = cast(func.strftime("%s", Measurement.timestamp), Float)
    else:
        epoch = func.extract("epoch", Measurement.timestamp)
    bucket = cast(epoch / bucket_seconds, Integer)
    rows = db.execute(
        select(
            func.min(Measurement.timestamp),
            func.avg(Measurement.power_w),
            func.min(Measurement.power_w),
            func.max(Measurement.power_w),
            bucket.label("bucket"),
        )
        .where(*conditions)
        .group_by(bucket)
        .order_by(bucket)
    ).all()
    return {
        "points": [
            {"timestamp": row[0], "power_w": row[1], "power_min_w": row[2], "power_max_w": row[3]}
            for row in rows
        ],
        "source_count": bounds[2],
        "downsampled": bounds[2] > len(rows),
        "bucket_seconds": bucket_seconds,
    }


@router.get("/sessions/{session_id}/synchronized-series")
def get_synchronized_series(
    session_id: int,
    db: Db,
    _: CurrentUser,
    grid_ms: int = Query(1000, ge=100, le=60_000),
    tolerance_ms: int = Query(1500, ge=0, le=3000),
    channels: list[int] | None = Query(None),
    max_points: int = Query(5000, ge=10, le=20_000),
) -> dict:
    if not db.get(MeasurementSession, session_id):
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    channel_filter = set(channels) if channels else None
    if channel_filter and any(channel < 1 or channel > 32 for channel in channel_filter):
        raise HTTPException(status_code=422, detail="Canais devem estar entre 1 e 32")
    try:
        return synchronized_series(
            db, session_id, grid_ms, tolerance_ms, channel_filter, max_points
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/imports/gpm8213/preview")
async def preview_gpm8213(_: CurrentUser, file: UploadFile = File(...)) -> dict:
    payload = await _safe_upload(file, ".txt")
    try:
        return Gpm8213TxtImporter().parse(payload).preview()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/imports/at4532/preview")
async def preview_at4532(_: CurrentUser, file: UploadFile = File(...)) -> dict:
    payload = await _safe_upload(file, ".xlsx")
    try:
        return At4532XlsxImporter().parse(payload).preview()
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/imports/session", status_code=201)
async def confirm_import_session(
    db: Db,
    user: User = Depends(require_roles("admin", "operator")),
    name: str = Form(..., min_length=2, max_length=160),
    description: str | None = Form(None),
    temperature_device_id: int | None = Form(None),
    electrical_device_id: int | None = Form(None),
    grid_ms: int = Form(1000, ge=100, le=60_000),
    tolerance_ms: int = Form(1500, ge=0, le=3000),
    at4532_file: UploadFile | None = File(None),
    gpm8213_file: UploadFile | None = File(None),
) -> dict:
    if not at4532_file and not gpm8213_file:
        raise HTTPException(status_code=422, detail="Envie ao menos um arquivo")
    temperatures = []
    electrical = []
    summaries = {}
    try:
        if at4532_file:
            parsed = At4532XlsxImporter().parse(await _safe_upload(at4532_file, ".xlsx"))
            temperatures = parsed.readings
            summaries["temperature"] = parsed.preview(0)
        if gpm8213_file:
            parsed = Gpm8213TxtImporter().parse(await _safe_upload(gpm8213_file, ".txt"))
            electrical = parsed.readings
            summaries["electrical"] = parsed.preview(0)
        session = create_import_session(
            db=db,
            user=user,
            name=name,
            description=description,
            temperature_readings=temperatures,
            electrical_readings=electrical,
            temperature_device_id=temperature_device_id,
            electrical_device_id=electrical_device_id,
            grid_ms=grid_ms,
            tolerance_ms=tolerance_ms,
        )
    except (ValueError, OSError) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"session_id": session.id, "status": session.status, "summaries": summaries}


@router.get("/statistics/sessions/{session_id}")
def get_session_statistics(session_id: int, db: Db, _: CurrentUser) -> dict:
    try:
        return session_statistics(db, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/statistics/executive")
def get_executive_statistics(db: Db, _: CurrentUser) -> dict:
    return executive_statistics(db)


@router.get("/statistics/compare")
def compare_sessions(
    session_ids: list[int] = Query(),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    if len(session_ids) < 2 or len(session_ids) > 8:
        raise HTTPException(status_code=422, detail="Selecione entre duas e oito sessões")
    return {"sessions": [session_statistics(db, session_id) for session_id in session_ids]}


@router.get("/alert-rules", response_model=None)
def list_alert_rules(db: Db, _: CurrentUser, device_id: int | None = None) -> list[AlertRule]:
    statement = select(AlertRule)
    if device_id:
        statement = statement.where(AlertRule.device_id == device_id)
    return list(db.scalars(statement.order_by(AlertRule.id)))


@router.post("/alert-rules", status_code=201, response_model=None)
def create_alert_rule(
    payload: AlertRuleInput, db: Db, _: User = Depends(require_roles("admin"))
) -> AlertRule:
    rule = AlertRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.get("/alerts")
def list_alerts(
    db: Db,
    _: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    acknowledged: bool | None = None,
    severity: str | None = None,
) -> dict:
    conditions = []
    if acknowledged is not None:
        conditions.append(AlertEvent.acknowledged == acknowledged)
    if severity:
        conditions.append(AlertEvent.severity == severity)
    total = db.scalar(select(func.count()).select_from(AlertEvent).where(*conditions)) or 0
    rows = list(
        db.scalars(
            select(AlertEvent)
            .where(*conditions)
            .order_by(AlertEvent.timestamp.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return _page([_orm_dict(row) for row in rows], total, page, page_size)


@router.post("/alerts/{alert_id}/acknowledge", response_model=None)
def acknowledge_alert(
    alert_id: int, db: Db, user: User = Depends(require_roles("admin", "operator"))
) -> AlertEvent:
    alert = db.get(AlertEvent, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alerta não encontrado")
    alert.acknowledged = True
    alert.acknowledged_by = user.id
    alert.acknowledged_at = datetime.now(UTC)
    db.commit()
    db.refresh(alert)
    return alert


@router.get("/events")
def list_events(
    db: Db,
    _: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    level: str | None = None,
    category: str | None = None,
    search: str | None = None,
) -> dict:
    conditions = []
    if level:
        conditions.append(SystemEvent.level == level)
    if category:
        conditions.append(SystemEvent.category == category)
    if search:
        conditions.append(SystemEvent.message.ilike(f"%{search}%"))
    total = db.scalar(select(func.count()).select_from(SystemEvent).where(*conditions)) or 0
    rows = list(
        db.scalars(
            select(SystemEvent)
            .where(*conditions)
            .order_by(SystemEvent.timestamp.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return _page([_orm_dict(row) for row in rows], total, page, page_size)


@router.get("/reports", response_model=None)
def list_reports(db: Db, _: CurrentUser) -> list[Report]:
    return list(db.scalars(select(Report).order_by(Report.generated_at.desc()).limit(100)))


def _period_report_record(
    db: Session, payload: PeriodReportRequest, user_id: int, report_type: str
) -> Report:
    report = Report(
        session_id=None,
        scope_type="period",
        period_start=payload.start,
        period_end=payload.end,
        timezone=payload.timezone,
        type=report_type,
        title=payload.title,
        filters_json=payload.model_dump(mode="json"),
        generated_by=user_id,
        status="generating",
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def _period_content_disposition(title: str, extension: str) -> str:
    filename = safe_report_filename(title, extension)
    return f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}"


def _finish_period_report(db: Session, report: Report, builder: callable) -> bytes:
    try:
        content = builder()
        report.status = "completed"
        report.error_message = None
        db.commit()
        return content
    except Exception as exc:
        report.status = "failed"
        report.error_message = str(exc)[:2000]
        db.commit()
        raise


@router.post("/reports/period/preview")
def preview_period_report(payload: PeriodReportRequest, db: Db, _: CurrentUser) -> dict:
    try:
        return PeriodReportDataService(db).preview(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/reports/period/pdf")
def download_period_pdf(
    payload: PeriodReportRequest, db: Db, user: CurrentUser
) -> StreamingResponse:
    report = _period_report_record(db, payload, user.id, "pdf")
    try:
        content = _finish_period_report(
            db,
            report,
            lambda: render_period_pdf(PeriodReportDataService(db).collect(payload), payload),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/pdf",
        headers={"Content-Disposition": _period_content_disposition(payload.title, "pdf")},
    )


def _period_chart_response(
    payload: PeriodReportRequest,
    db: Session,
    user: User,
    image_type: Literal["png", "jpeg"],
) -> StreamingResponse:
    report = _period_report_record(db, payload, user.id, image_type)
    try:
        content = _finish_period_report(
            db,
            report,
            lambda: render_period_chart(
                PeriodReportDataService(db).collect(payload), payload, image_type
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return StreamingResponse(
        io.BytesIO(content),
        media_type=f"image/{image_type}",
        headers={"Content-Disposition": _period_content_disposition(payload.title, image_type)},
    )


@router.post("/reports/period/chart.png")
def download_period_chart_png(
    payload: PeriodReportRequest, db: Db, user: CurrentUser
) -> StreamingResponse:
    return _period_chart_response(payload, db, user, "png")


@router.post("/reports/period/chart.jpeg")
def download_period_chart_jpeg(
    payload: PeriodReportRequest, db: Db, user: CurrentUser
) -> StreamingResponse:
    return _period_chart_response(payload, db, user, "jpeg")


@router.get("/reports/sessions/{session_id}.{report_type}")
def download_report(
    session_id: int,
    report_type: Literal["csv", "xlsx", "pdf", "png", "jpg", "jpeg"],
    db: Db,
    user: CurrentUser,
    orientation: Literal["portrait", "landscape"] = "landscape",
) -> StreamingResponse:
    builders = {"csv": create_csv, "xlsx": create_xlsx}
    if report_type == "pdf":
        content = create_pdf(db, session_id, user.id, orientation)
    elif report_type in {"png", "jpg", "jpeg"}:
        content = create_chart_image(db, session_id, user.id, report_type)
    else:
        content = builders[report_type](db, session_id, user.id)
    media = {
        "csv": "text/csv; charset=utf-8",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pdf": "application/pdf",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
    }[report_type]
    return StreamingResponse(
        io.BytesIO(content),
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="sessao-{session_id}.{report_type}"'
        },
    )


@router.get("/diagnostics")
async def diagnostics(db: Db, _: CurrentUser) -> dict:
    db.execute(select(1)).scalar_one()
    statuses = await acquisition_service.all_statuses()
    disk = shutil.disk_usage(".")
    return {
        "backend_online": True,
        "database_online": True,
        "database_dialect": engine.dialect.name,
        "websocket_clients": len(websocket_hub.clients),
        "devices": statuses,
        "disk_free_bytes": disk.free,
        "system_version": settings.app_version,
        "uptime_seconds": (datetime.now(UTC) - acquisition_service.started_at).total_seconds(),
        "environment": settings.environment,
    }


@router.get("/simulator/scenarios")
def simulator_scenarios(_: CurrentUser) -> list[str]:
    return list(SCENARIOS)


@router.put("/simulator/{device_id}/config")
async def configure_simulator(
    device_id: int,
    payload: SimulatorConfigInput,
    _: User = Depends(require_roles("admin", "operator")),
) -> dict:
    try:
        return await acquisition_service.configure_simulator(device_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/simulator/{device_id}/scenarios/{scenario}")
async def apply_simulator_scenario(
    device_id: int, scenario: str, _: User = Depends(require_roles("admin", "operator"))
) -> dict:
    try:
        return await acquisition_service.apply_scenario(device_id, scenario)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)) -> None:
    try:
        decode_access_token(token)
    except HTTPException:
        await websocket.close(code=4401)
        return
    await websocket_hub.connect(websocket)
    try:
        await websocket.send_json(
            {
                "type": "connection.ready",
                "timestamp": datetime.now(UTC).isoformat(),
                "payload": {"heartbeat_seconds": 20},
            }
        )
        while True:
            queue = websocket_hub.clients.get(websocket)
            if not queue:
                break
            try:
                message = await asyncio.wait_for(queue.get(), timeout=20)
            except TimeoutError:
                message = {
                    "type": "heartbeat",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "payload": {},
                }
            await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    finally:
        await websocket_hub.disconnect(websocket)
