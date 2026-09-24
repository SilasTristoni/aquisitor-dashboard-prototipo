import asyncio
import logging
import statistics
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import product
from time import monotonic

from sqlalchemy import func, or_, select

from app.adapters import (
    At4532Adapter,
    DeviceAdapter,
    DeviceReading,
    Gpm8213Adapter,
    MockFailureAdapter,
    SerialCsvAdapter,
    SerialJsonAdapter,
    SimulatorAdapter,
)
from app.adapters.transports import SerialTransportError
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import (
    AlertEvent,
    AlertRule,
    ChannelConfiguration,
    Device,
    ElectricalSample,
    Measurement,
    MeasurementSession,
    SessionDevice,
    SystemEvent,
    TemperatureChannelValue,
    TemperatureMeasurement,
    TemperatureSample,
)
from app.schemas.contracts import SimulatorConfigInput
from app.services.device_policy import (
    at4532_identity_fallback_policy,
    mark_at4532_verified_by_measurement,
)
from app.services.session_clock import utc
from app.services.usb_discovery import usb_discovery_service
from app.services.websocket import websocket_hub

logger = logging.getLogger(__name__)
settings = get_settings()


def _compare(value: float, operator: str, threshold: float) -> bool:
    return {
        ">": value > threshold,
        ">=": value >= threshold,
        "<": value < threshold,
        "<=": value <= threshold,
    }.get(operator, False)


@dataclass
class DeviceRuntime:
    adapter: DeviceAdapter
    device_name: str = ""
    protocol: str = ""
    source_role: str = "combined"
    task: asyncio.Task | None = None
    session_id: int | None = None
    paused: bool = False
    buffer: list[DeviceReading] = field(default_factory=list)
    last_flush: float = field(default_factory=monotonic)
    last_alerts: dict[tuple[int, int | None], float] = field(default_factory=dict)
    latest: DeviceReading | None = None
    sample_count: int = 0
    last_error: str | None = None
    pending_start: list[DeviceReading] | None = None
    persisted_count: int = 0
    received_times: deque[datetime] = field(default_factory=lambda: deque(maxlen=61))


class AcquisitionService:
    def __init__(self) -> None:
        self.runtimes: dict[int, DeviceRuntime] = {}
        self.last_connection_results: dict[int, dict] = {}
        self._device_locks: dict[int, asyncio.Lock] = {}
        self._port_locks: dict[str, asyncio.Lock] = {}
        self.started_at = datetime.now(UTC)
        self.session_start_lock = asyncio.Lock()
        self.common_start_diagnostic: dict = {}

    async def prepare_common_start(
        self,
        device_ids: list[int],
        tolerance_ms: int,
        timeout_seconds: float = 15,
    ) -> datetime:
        """Wait for actual new samples; do not reuse a preflight/latest value."""
        for device_id in device_ids:
            runtime = self.runtimes.get(device_id)
            if runtime and runtime.session_id:
                raise ValueError("Uma fonte já pertence a uma sessão ativa.")
            # Do not reconnect a running reader because of a transient status flag.
            if not runtime or not runtime.task or runtime.task.done():
                await self.connect(device_id)
        requested_at = datetime.now(UTC)
        for device_id in device_ids:
            self.runtimes[device_id].pending_start = []
        next_log = 0.0
        previous_state = None
        try:
            async with asyncio.timeout(timeout_seconds):
                while True:
                    now = datetime.now(UTC)
                    queues = []
                    sources = {}
                    readers_running = True
                    for device_id in device_ids:
                        runtime = self.runtimes.get(device_id)
                        task_running = bool(
                            runtime
                            and runtime.task
                            and not runtime.task.done()
                            and not runtime.task.cancelling()
                        )
                        readers_running = readers_running and task_running
                        status_error = None
                        try:
                            connected = bool(
                                runtime and (await runtime.adapter.get_status()).connected
                            )
                        except Exception as exc:
                            connected = False
                            status_error = f"{type(exc).__name__}: {exc}"
                        fresh = (
                            [
                                r
                                for r in (runtime.pending_start or [])
                                if requested_at <= utc(r.received_timestamp)
                                and 0 <= (now - utc(r.received_timestamp)).total_seconds() <= 3
                                and (
                                    r.power_w is not None
                                    if runtime.source_role == "electrical"
                                    else any(v is not None for v in r.temperatures_c)
                                )
                            ]
                            if runtime
                            else []
                        )
                        queues.append(fresh)
                        sources[str(device_id)] = {
                            "protocol": runtime.protocol if runtime else None,
                            "source_role": runtime.source_role if runtime else None,
                            "connected": connected,
                            "task_running": task_running,
                            "last_error": runtime.last_error if runtime else "runtime_missing",
                            "status_error": status_error,
                            "latest_received_timestamp": (
                                utc(runtime.latest.received_timestamp).isoformat()
                                if runtime and runtime.latest
                                else None
                            ),
                            "fresh_samples": len(fresh),
                            "interruption_flags": [
                                name
                                for name, active in {
                                    "runtime_missing": runtime is None,
                                    "last_error": bool(runtime and runtime.last_error),
                                    "task_not_running": not task_running,
                                    "not_connected": not connected,
                                }.items()
                                if active
                            ],
                        }
                    best = min(
                        product(*queues),
                        key=lambda pair: (
                            max(utc(r.received_timestamp) for r in pair)
                            - min(utc(r.received_timestamp) for r in pair)
                        ).total_seconds(),
                        default=None,
                    )
                    times = [utc(r.received_timestamp) for r in best] if best else []
                    delta_ms = (max(times) - min(times)).total_seconds() * 1000 if times else None
                    # Status calls may yield: recheck task liveness before accepting.
                    readers_running = readers_running and all(
                        (runtime := self.runtimes.get(device_id))
                        and runtime.task
                        and not runtime.task.done()
                        and not runtime.task.cancelling()
                        for device_id in device_ids
                    )
                    matched = readers_running and delta_ms is not None and delta_ms <= tolerance_ms
                    self.common_start_diagnostic = {
                        "requested_at": requested_at.isoformat(),
                        "timestamp": now.isoformat(),
                        "sources": sources,
                        "best_delta_ms": delta_ms,
                        "tolerance_ms": tolerance_ms,
                        "state": "matched" if matched else "waiting",
                    }
                    observed_state = tuple(
                        (
                            key,
                            source["connected"],
                            source["task_running"],
                            source["last_error"],
                            source["status_error"],
                        )
                        for key, source in sources.items()
                    )
                    if matched or observed_state != previous_state or monotonic() >= next_log:
                        logger.info("common start diagnostic %s", self.common_start_diagnostic)
                        next_log = monotonic() + 1
                        previous_state = observed_state
                    if matched:
                        return min(times)
                    await asyncio.sleep(0.01)
        except BaseException as exc:
            self.common_start_diagnostic = {
                **self.common_start_diagnostic,
                "state": "timeout" if isinstance(exc, TimeoutError) else "cancelled",
            }
            logger.info("common start diagnostic %s", self.common_start_diagnostic)
            self.clear_pending_start(device_ids)
            if isinstance(exc, TimeoutError):
                raise TimeoutError(
                    "Tempo de espera esgotado sem par novo de fontes em aquisição "
                    f"dentro da tolerância de {tolerance_ms} ms. "
                    "Consulte common_start_diagnostic no diagnóstico da aquisição."
                ) from exc
            raise

    def clear_pending_start(self, device_ids: list[int]) -> None:
        for device_id in device_ids:
            if runtime := self.runtimes.get(device_id):
                runtime.pending_start = None

    async def activate_common_start(
        self,
        session_id: int,
        device_ids: list[int],
        origin: datetime,
    ) -> dict:
        captured = []
        # No await between assigning sources: both streams cross the same boundary.
        for device_id in device_ids:
            runtime = self.runtimes[device_id]
            readings = [
                r for r in runtime.pending_start or [] if utc(r.received_timestamp) >= origin
            ]
            runtime.session_id = session_id
            runtime.paused = False
            runtime.persisted_count = 0
            runtime.buffer.extend(readings)
            runtime.pending_start = None
            captured.append((device_id, runtime, readings))
        for device_id, runtime, readings in captured:
            await self._flush(device_id, runtime)
            for reading in readings:
                await self._publish_reading(device_id, runtime, reading)
        return await self._run_source_actions(
            electrical_device_id=device_ids[0],
            thermal_device_id=device_ids[1],
            action=self.status,
        )

    async def _publish_reading(
        self,
        device_id: int,
        runtime: DeviceRuntime,
        reading: DeviceReading,
    ) -> None:
        payload = reading.model_dump(mode="json")
        payload.update(
            {
                "device_id": device_id,
                "device_name": runtime.device_name,
                "device_protocol": runtime.protocol,
                "source_role": runtime.source_role,
                "session_id": runtime.session_id,
            }
        )
        await websocket_hub.publish("measurement.created", payload)

    def _device_lock(self, device_id: int) -> asyncio.Lock:
        return self._device_locks.setdefault(device_id, asyncio.Lock())

    def _port_lock(self, port: str) -> asyncio.Lock:
        return self._port_locks.setdefault(port.casefold(), asyncio.Lock())

    @asynccontextmanager
    async def diagnostic_port(self, port: str):
        """Serialize against connection and refuse to touch a runtime-owned port."""
        async with self._port_lock(port):
            self.assert_diagnostic_port_available(port)
            yield

    def assert_diagnostic_port_available(self, port: str) -> None:
        owner = next(
            (
                device_id
                for device_id, runtime in self.runtimes.items()
                if str(getattr(runtime.adapter, "port", "")).casefold() == port.casefold()
            ),
            None,
        )
        if owner is not None:
            logger.info("diagnostic blocked port=%s runtime_device_id=%s", port, owner)
            raise SerialTransportError(
                "port_owned_by_thermopower",
                "O equipamento está atualmente em aquisição pelo ThermoPower. "
                "Desconecte-o antes de executar o diagnóstico de comunicação.",
            )

    @staticmethod
    def _device_port_key(device_id: int) -> str | None:
        with SessionLocal() as db:
            device = db.get(Device, device_id)
            if (
                not device
                or not device.active
                or device.connection_type == "simulator"
                or not device.port
            ):
                return None
            return device.port.casefold()

    def _adapter_for(self, device: Device) -> DeviceAdapter:
        if device.protocol == "simulator":
            return SimulatorAdapter()
        if device.protocol == "serial_json":
            if device.baud_rate is None:
                raise ValueError("Baud rate não configurado.")
            return SerialJsonAdapter(device.port, device.baud_rate)
        if device.protocol == "serial_csv":
            if device.baud_rate is None:
                raise ValueError("Baud rate não configurado.")
            return SerialCsvAdapter(device.port, device.baud_rate)
        if device.protocol == "mock_failure":
            return MockFailureAdapter()
        if device.protocol == "at4532_serial":
            policy = at4532_identity_fallback_policy(device)
            return At4532Adapter(
                device.port,
                device.baud_rate,
                allow_identity_fallback=policy.allowed,
                association_source=policy.association_source,
            )
        if device.protocol == "gpm8213_serial":
            return Gpm8213Adapter(device.port, device.baud_rate)
        raise ValueError(f"Protocolo não suportado: {device.protocol}")

    @staticmethod
    def _status_is_healthy(status: dict | None) -> bool:
        return bool(
            status
            and status.get("connected")
            and status.get("state") != "error"
            and not status.get("last_error")
        )

    async def connect(self, device_id: int) -> dict:
        port_key = self._device_port_key(device_id)
        if port_key:
            async with self._port_lock(port_key):
                async with self._device_lock(device_id):
                    return await self._connect_locked(device_id)
        async with self._device_lock(device_id):
            return await self._connect_locked(device_id)

    async def _connect_locked(self, device_id: int) -> dict:
        try:
            status = await self._connect_device(device_id)
        except Exception as exc:
            self.last_connection_results[device_id] = {
                "device_id": device_id,
                "success": False,
                "status": "error",
                "error": str(exc),
                "attempted_at": datetime.now(UTC).isoformat(),
            }
            raise
        if not self._status_is_healthy(status):
            error = "A fonte nao permaneceu conectada."
            try:
                await self._disconnect_device(device_id)
            except Exception as cleanup_exc:
                error = f"{error} Falha de limpeza: {type(cleanup_exc).__name__}: {cleanup_exc}"
            self.last_connection_results[device_id] = {
                "device_id": device_id,
                "success": False,
                "status": "error",
                "error": error,
                "attempted_at": datetime.now(UTC).isoformat(),
            }
            raise ConnectionError(error)
        self.last_connection_results[device_id] = {
            "device_id": device_id,
            "success": True,
            "status": "connected",
            "error": None,
            "attempted_at": datetime.now(UTC).isoformat(),
        }
        return status

    async def _connect_device(self, device_id: int) -> dict:
        existing = self.runtimes.get(device_id)
        if existing:
            current_status = await self.status(device_id)
            task_running = existing.task is None or not existing.task.done()
            if current_status.get("connected") and not existing.last_error and task_running:
                return current_status
            # Keep the runtime map retryable after an acquisition task or transport failed.
            await self._disconnect_device(device_id)
        with SessionLocal() as db:
            device = db.get(Device, device_id)
            if not device or not device.active:
                raise ValueError("Equipamento não encontrado ou inativo")
            if device.port:
                port_key = device.port.casefold()
                conflicting_runtime = next(
                    (
                        other_id
                        for other_id, runtime in self.runtimes.items()
                        if other_id != device_id
                        and str(getattr(runtime.adapter, "port", "")).casefold() == port_key
                    ),
                    None,
                )
                if conflicting_runtime is not None:
                    raise SerialTransportError(
                        "port_busy",
                        f"A porta {device.port} já está sob controle do equipamento "
                        f"#{conflicting_runtime} explicitamente conectado.",
                    )
            if device.protocol == "gpm8213_serial" and device.serial_number:
                # The USB serial is stable; Windows may assign a different COM port.
                usb_discovery_service.discover(
                    db,
                    {
                        port
                        for runtime in self.runtimes.values()
                        if (port := getattr(runtime.adapter, "port", None))
                    },
                )
                db.refresh(device)
            adapter = self._adapter_for(device)
            logger.info(
                "device connect requested device_id=%s protocol=%s port=%s",
                device_id,
                device.protocol,
                device.port,
            )
            try:
                await adapter.connect()
                device.last_connected_at = datetime.now(UTC)
                if hasattr(adapter, "expected_interval_seconds"):
                    device.metadata_json = {
                        **(device.metadata_json or {}),
                        "expected_interval_ms": round(adapter.expected_interval_seconds * 1000),
                    }
                if (
                    device.protocol == "at4532_serial"
                    and getattr(adapter, "protocol_status", None) == "verified_by_measurement"
                ):
                    mark_at4532_verified_by_measurement(device, datetime.now(UTC))
                db.add(
                    SystemEvent(
                        device_id=device_id, category="connection", message="Equipamento conectado"
                    )
                )
                db.commit()
            except Exception as exc:
                db.rollback()
                close_error: Exception | None = None
                try:
                    await adapter.disconnect()
                except Exception as cleanup_exc:
                    close_error = cleanup_exc
                    logger.exception(
                        "failed to close adapter after connection error device_id=%s", device_id
                    )
                    self.runtimes[device_id] = DeviceRuntime(
                        adapter=adapter,
                        device_name=device.name,
                        protocol=device.protocol,
                        source_role=(
                            "temperature"
                            if device.protocol == "at4532_serial"
                            else "electrical"
                            if device.protocol == "gpm8213_serial"
                            else "combined"
                        ),
                        last_error=(
                            f"{type(exc).__name__}: {exc}; fechamento pendente: "
                            f"{type(cleanup_exc).__name__}: {cleanup_exc}"
                        ),
                    )
                try:
                    db.add(
                        SystemEvent(
                            device_id=device_id,
                            level="error",
                            category="connection_error",
                            message="Falha ao conectar equipamento",
                            details={
                                "error": type(exc).__name__,
                                "close_failed": close_error is not None,
                            },
                        )
                    )
                    db.commit()
                except Exception:
                    db.rollback()
                    logger.exception("failed to persist connection error device_id=%s", device_id)
                raise
        source_role = (
            "temperature"
            if device.protocol == "at4532_serial"
            else "electrical"
            if device.protocol == "gpm8213_serial"
            else "combined"
        )
        runtime = DeviceRuntime(
            adapter=adapter,
            device_name=device.name,
            protocol=device.protocol,
            source_role=source_role,
        )
        with SessionLocal() as db:
            active_session = db.scalar(
                select(MeasurementSession)
                .outerjoin(SessionDevice, SessionDevice.session_id == MeasurementSession.id)
                .where(
                    or_(
                        SessionDevice.device_id == device_id,
                        MeasurementSession.device_id == device_id,
                    ),
                    MeasurementSession.status.in_(["running", "paused"]),
                )
            )
            if active_session:
                runtime.session_id = active_session.id
                runtime.paused = active_session.status == "paused"
                sample_model = (
                    TemperatureSample if source_role == "temperature" else ElectricalSample
                )
                runtime.persisted_count = (
                    db.scalar(
                        select(func.count())
                        .select_from(sample_model)
                        .where(
                            sample_model.session_id == active_session.id,
                            sample_model.device_id == device_id,
                        )
                    )
                    or 0
                )
        self.runtimes[device_id] = runtime
        runtime.task = asyncio.create_task(self._read_loop(device_id, runtime))
        await websocket_hub.publish("device.status", {"device_id": device_id, "state": "connected"})
        return await self.status(device_id)

    async def connect_sources(
        self,
        *,
        electrical_device_id: int | None,
        thermal_device_id: int | None,
    ) -> dict:
        """Connect requested sources independently and never roll back a healthy source."""

        return await self._run_source_actions(
            electrical_device_id=electrical_device_id,
            thermal_device_id=thermal_device_id,
            action=self.connect,
        )

    async def attach_session_sources(
        self,
        *,
        session_id: int,
        electrical_device_id: int | None,
        thermal_device_id: int | None,
    ) -> dict:
        """Attach every requested stream independently to the same session."""

        async def attach(device_id: int) -> dict:
            attached = False
            try:
                await self.attach_session(device_id, session_id)
                attached = True
                status = await self.status(device_id)
                if not self._status_is_healthy(status):
                    raise ConnectionError("A fonte nao permaneceu conectada a sessao.")
                return status
            except Exception as exc:
                if attached:
                    try:
                        await self.detach_session(device_id)
                    except Exception as detach_exc:
                        raise RuntimeError(
                            f"{exc}; falha ao desfazer vinculo da sessao: "
                            f"{type(detach_exc).__name__}: {detach_exc}"
                        ) from exc
                raise

        result = await self._run_source_actions(
            electrical_device_id=electrical_device_id,
            thermal_device_id=thermal_device_id,
            action=attach,
        )
        with SessionLocal() as db:
            for role in ("electrical", "thermal"):
                source = result[role]
                if source["requested"] and not source["success"]:
                    db.add(
                        SystemEvent(
                            session_id=session_id,
                            device_id=source["device_id"],
                            level="error",
                            category="session_source_error",
                            message=f"Falha ao anexar fonte {role} a sessao",
                            details={"role": role, "error": source["error"]},
                        )
                    )
            db.commit()
        return result

    async def _run_source_actions(
        self,
        *,
        electrical_device_id: int | None,
        thermal_device_id: int | None,
        action: Callable[[int], Awaitable[dict]],
    ) -> dict:
        requested = {
            "electrical": electrical_device_id,
            "thermal": thermal_device_id,
        }
        results: dict[str, dict] = {}
        action_results: dict[int, tuple[dict | None, Exception | None]] = {}
        for device_id in dict.fromkeys(
            device_id for device_id in requested.values() if device_id is not None
        ):
            try:
                action_results[device_id] = (await action(device_id), None)
            except Exception as exc:
                logger.warning(
                    "independent source action failed device_id=%s error=%s",
                    device_id,
                    type(exc).__name__,
                )
                action_results[device_id] = (None, exc)

        for role, device_id in requested.items():
            if device_id is None:
                results[role] = {
                    "device_id": None,
                    "requested": False,
                    "success": False,
                    "status": "not_requested",
                    "error": None,
                    "runtime_status": None,
                }
                continue
            runtime_status, error = action_results[device_id]
            connected = self._status_is_healthy(runtime_status)
            results[role] = {
                "device_id": device_id,
                "requested": True,
                "success": connected and error is None,
                "status": "connected" if connected and error is None else "error",
                "error": str(error)
                if error is not None
                else None
                if connected
                else "A fonte nao permaneceu conectada.",
                "runtime_status": runtime_status,
            }

        successes = sum(source["success"] for source in results.values())
        results["overall"] = "both" if successes == 2 else "partial" if successes else "none"
        return results

    async def disconnect(self, device_id: int) -> None:
        async with self._device_lock(device_id):
            await self._disconnect_device(device_id)

    async def _disconnect_device(self, device_id: int) -> None:
        runtime = self.runtimes.get(device_id)
        if not runtime:
            return
        cleanup_errors: list[Exception] = []
        flush_error: Exception | None = None
        close_error: Exception | None = None
        try:
            await runtime.adapter.stop_reading()
        except Exception as exc:
            cleanup_errors.append(exc)
            logger.exception("failed to stop acquisition device_id=%s", device_id)
        if runtime.task and runtime.task is not asyncio.current_task():
            runtime.task.cancel()
            try:
                await runtime.task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                cleanup_errors.append(exc)
                logger.exception(
                    "acquisition task failed during disconnect device_id=%s", device_id
                )
        # Stop the producer before the final flush so no already acquired reading can be
        # appended between persistence and teardown.
        try:
            await self._flush(device_id, runtime)
        except Exception as exc:
            flush_error = exc
            cleanup_errors.append(exc)
            logger.exception("failed to flush before disconnect device_id=%s", device_id)
        try:
            await runtime.adapter.disconnect()
        except Exception as exc:
            close_error = exc
            cleanup_errors.append(exc)
            logger.exception("failed to close adapter device_id=%s", device_id)

        if flush_error is not None or close_error is not None:
            cleanup_summary = "; ".join(
                f"{type(error).__name__}: {error}" for error in cleanup_errors
            )
            runtime.last_error = f"Desconexao pendente: {cleanup_summary}"
            self.last_connection_results[device_id] = {
                "device_id": device_id,
                "success": False,
                "status": "error",
                "error": runtime.last_error,
                "attempted_at": datetime.now(UTC).isoformat(),
            }
            try:
                with SessionLocal() as db:
                    db.add(
                        SystemEvent(
                            device_id=device_id,
                            level="error",
                            category="disconnection_error",
                            message="Desconexao incompleta; estado retido para nova tentativa",
                            details={
                                "buffered_measurements": len(runtime.buffer),
                                "flush_failed": flush_error is not None,
                                "close_failed": close_error is not None,
                            },
                        )
                    )
                    db.commit()
            except Exception:
                logger.exception("failed to persist disconnection error device_id=%s", device_id)
            await websocket_hub.publish(
                "device.status",
                {
                    "device_id": device_id,
                    "state": "error",
                    "message": "Desconexao incompleta; nova tentativa necessaria",
                },
            )
            raise flush_error or close_error

        logger.info("device disconnected device_id=%s", device_id)
        self.runtimes.pop(device_id, None)
        self.last_connection_results[device_id] = {
            "device_id": device_id,
            "success": False,
            "status": "disconnected",
            "error": None,
            "attempted_at": datetime.now(UTC).isoformat(),
        }
        try:
            with SessionLocal() as db:
                db.add(
                    SystemEvent(
                        device_id=device_id,
                        category="disconnection",
                        message="Equipamento desconectado",
                    )
                )
                db.commit()
        except Exception:
            logger.exception("failed to persist disconnection event device_id=%s", device_id)
        await websocket_hub.publish(
            "device.status", {"device_id": device_id, "state": "disconnected"}
        )
        if cleanup_errors:
            raise cleanup_errors[0]

    async def attach_session(self, device_id: int, session_id: int) -> None:
        runtime = self.runtimes.get(device_id)
        if (
            runtime is None
            or runtime.last_error is not None
            or (runtime.task is not None and runtime.task.done())
            or not (await runtime.adapter.get_status()).connected
        ):
            await self.connect(device_id)
        runtime = self.runtimes[device_id]
        if runtime.session_id != session_id:
            runtime.persisted_count = 0
        runtime.session_id = session_id
        runtime.paused = False
        await websocket_hub.publish(
            "session.status",
            {"device_id": device_id, "session_id": session_id, "status": "running"},
        )

    async def pause_session(self, device_id: int) -> None:
        runtime = self.runtimes.get(device_id)
        if runtime:
            previous_paused = runtime.paused
            runtime.paused = True
            try:
                await self._flush(device_id, runtime)
            except Exception:
                runtime.paused = previous_paused
                raise

    async def resume_session(self, device_id: int, session_id: int) -> None:
        await self.attach_session(device_id, session_id)

    async def detach_session(self, device_id: int) -> None:
        runtime = self.runtimes.get(device_id)
        if runtime:
            previous_paused = runtime.paused
            runtime.paused = True
            try:
                await self._flush(device_id, runtime)
            except Exception:
                runtime.paused = previous_paused
                raise
            runtime.session_id = None
            runtime.paused = False

    async def configure_simulator(self, device_id: int, config: SimulatorConfigInput) -> dict:
        runtime = self.runtimes.get(device_id)
        if not runtime or not isinstance(runtime.adapter, SimulatorAdapter):
            raise ValueError("Simulador deve estar conectado")
        runtime.adapter.configure(config)
        return config.model_dump()

    async def apply_scenario(self, device_id: int, scenario: str) -> dict:
        runtime = self.runtimes.get(device_id)
        if not runtime or not isinstance(runtime.adapter, SimulatorAdapter):
            raise ValueError("Simulador deve estar conectado")
        runtime.adapter.apply_scenario(scenario)
        return {"scenario": scenario, "config": runtime.adapter.config.model_dump()}

    async def status(self, device_id: int) -> dict:
        runtime = self.runtimes.get(device_id)
        if not runtime:
            connection_result = self.last_connection_results.get(device_id)
            failed = bool(connection_result and connection_result["status"] == "error")
            return {
                "device_id": device_id,
                "state": "error" if failed else "disconnected",
                "connected": False,
                "reading": False,
                "last_error": connection_result.get("error") if connection_result else None,
                "last_connection_result": connection_result,
            }
        status = await runtime.adapter.get_status()
        latest = runtime.latest.model_dump(mode="json") if runtime.latest else None
        last_message_at = status.last_message_at
        age_seconds = (
            max((datetime.now(UTC) - last_message_at).total_seconds(), 0)
            if last_message_at
            else None
        )
        valid_channels = (
            sum(value is not None for value in runtime.latest.temperatures_c)
            if runtime.latest
            else 0
        )
        runtime_failed = runtime.last_error is not None or bool(
            runtime.task and runtime.task.done() and not runtime.task.cancelled()
        )
        intervals = [
            (b - a).total_seconds() * 1000
            for a, b in zip(runtime.received_times, list(runtime.received_times)[1:], strict=False)
            if b > a
        ]
        observed = statistics.median(intervals) if intervals else None
        expected = round(getattr(runtime.adapter, "expected_interval_seconds", 1) * 1000)
        metrics = getattr(runtime.adapter, "fetch_diagnostics", None)
        return {
            "device_id": device_id,
            **status.model_dump(mode="json"),
            "state": "error" if runtime_failed else status.state,
            "reading": False if runtime_failed else status.reading,
            "device_name": runtime.device_name,
            "observed_interval_ms": observed,
            "cadence_degraded": len(intervals) >= 4 and observed > expected * 1.5,
            "acquisition_diagnostics": metrics.snapshot(monotonic()) if metrics else None,
            "persistent_failure": bool(metrics and metrics.consecutive_reconnect_failures >= 3),
            "protocol": runtime.protocol,
            "source_role": runtime.source_role,
            "session_id": runtime.session_id,
            "paused": runtime.paused,
            "buffered_measurements": len(runtime.buffer),
            "sample_count": runtime.sample_count,
            "session_sample_count": runtime.persisted_count + len(runtime.buffer),
            "persisted_sample_count": runtime.persisted_count,
            "expected_interval_ms": round(
                getattr(runtime.adapter, "expected_interval_seconds", 1) * 1000
            ),
            "last_reading_age_seconds": age_seconds,
            "valid_channels": valid_channels,
            "channel_count": len(runtime.latest.temperatures_c) if runtime.latest else 0,
            "latest_reading": latest,
            "last_error": runtime.last_error,
            "last_connection_result": self.last_connection_results.get(device_id),
            "identity_status": getattr(runtime.adapter, "identity_status", "not_applicable"),
            "protocol_status": getattr(runtime.adapter, "protocol_status", "not_verified"),
        }

    async def all_statuses(self) -> list[dict]:
        return [await self.status(device_id) for device_id in self.runtimes]

    async def integration_snapshot(self) -> dict:
        with SessionLocal() as db:
            devices = list(
                db.scalars(
                    select(Device).where(
                        Device.active.is_(True),
                        Device.protocol.in_(["at4532_serial", "gpm8213_serial"]),
                    )
                )
            )
            configured = [
                {
                    "id": device.id,
                    "name": device.name,
                    "protocol": device.protocol,
                    "port": device.port,
                    "baud_rate": device.baud_rate,
                }
                for device in devices
            ]
        statuses = []
        for device in configured:
            status = await self.status(device["id"])
            status.update({key: value for key, value in device.items() if key not in status})
            status.setdefault(
                "source_role",
                "temperature" if device["protocol"] == "at4532_serial" else "electrical",
            )
            statuses.append(status)

        def selected_status(protocol: str) -> dict | None:
            candidates = [status for status in statuses if status["protocol"] == protocol]
            if not candidates:
                return None

            def priority(status: dict) -> tuple[bool, bool, str, int]:
                healthy = (
                    bool(status.get("connected"))
                    and status.get("state") != "error"
                    and not status.get("last_error")
                )
                connection = status.get("last_connection_result") or {}
                return (
                    healthy,
                    status["device_id"] in self.runtimes,
                    str(connection.get("attempted_at") or ""),
                    -int(status["device_id"]),
                )

            return max(candidates, key=priority)

        electrical_status = selected_status("gpm8213_serial")
        thermal_status = selected_status("at4532_serial")

        def source_snapshot(status: dict | None) -> dict:
            if status is None:
                return {
                    "device_id": None,
                    "configured": False,
                    "success": False,
                    "status": "not_configured",
                    "error": None,
                    "sample_count": 0,
                    "last_reading": None,
                    "last_message_at": None,
                    "runtime_status": None,
                }
            healthy = (
                bool(status.get("connected"))
                and status.get("state") != "error"
                and not status.get("last_error")
            )
            return {
                "device_id": status["device_id"],
                "configured": True,
                "success": healthy,
                "status": "connected"
                if healthy
                else "error"
                if status.get("last_error")
                else "disconnected",
                "error": status.get("last_error"),
                "connect_result": status.get("last_connection_result"),
                "sample_count": status.get("sample_count", 0),
                "last_reading": status.get("latest_reading"),
                "last_message_at": status.get("last_message_at"),
                "runtime_status": status,
            }

        sources = {
            "electrical": source_snapshot(electrical_status),
            "thermal": source_snapshot(thermal_status),
        }
        connected_sources = sum(source["success"] for source in sources.values())
        return {
            "timestamp": datetime.now(UTC).isoformat(),
            **sources,
            "overall": "both"
            if connected_sources == 2
            else "partial"
            if connected_sources
            else "none",
            "devices": statuses,
            "common_start_diagnostic": self.common_start_diagnostic,
            "sample_counts": {
                str(status["device_id"]): status.get("sample_count", 0) for status in statuses
            },
            "errors": {
                str(status["device_id"]): status.get("last_error")
                for status in statuses
                if status.get("last_error")
            },
            "connect_results": {
                role: source.get("connect_result") for role, source in sources.items()
            },
        }

    async def _read_loop(self, device_id: int, runtime: DeviceRuntime) -> None:
        try:
            async for reading in runtime.adapter.start_reading():
                # The instrument clock remains evidence, never the live session clock.
                reading = reading.model_copy(
                    update={
                        "timestamp": utc(reading.received_timestamp),
                        "received_timestamp": utc(reading.received_timestamp),
                        "device_timestamp": utc(reading.device_timestamp)
                        if reading.device_timestamp
                        else None,
                    }
                )
                runtime.latest = reading
                runtime.received_times.append(utc(reading.received_timestamp))
                runtime.sample_count += 1
                runtime.last_error = None
                if runtime.pending_start is not None:
                    runtime.pending_start.append(reading)
                if runtime.session_id and not runtime.paused:
                    runtime.buffer.append(reading)
                    await self._evaluate_alerts(device_id, runtime, reading)
                    if (
                        len(runtime.buffer) >= settings.measurement_batch_size
                        or monotonic() - runtime.last_flush >= 2
                    ):
                        await self._flush(device_id, runtime)
                if runtime.pending_start is None:
                    await self._publish_reading(device_id, runtime, reading)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            runtime.last_error = f"{type(exc).__name__}: {exc}"
            logger.exception("Acquisition loop failed for device %s", device_id)
            cleanup_errors: list[str] = []
            try:
                await self._flush(device_id, runtime)
            except Exception as flush_exc:
                cleanup_errors.append(f"flush={type(flush_exc).__name__}: {flush_exc}")
                logger.exception("Failed to flush buffered readings for device %s", device_id)
            try:
                await runtime.adapter.stop_reading()
            except Exception as stop_exc:
                cleanup_errors.append(f"stop={type(stop_exc).__name__}: {stop_exc}")
                logger.exception("Failed to stop errored adapter for device %s", device_id)
            try:
                await runtime.adapter.disconnect()
            except Exception as close_exc:
                cleanup_errors.append(f"close={type(close_exc).__name__}: {close_exc}")
                logger.exception("Failed to close errored adapter for device %s", device_id)
            if cleanup_errors:
                runtime.last_error = f"{runtime.last_error}; {'; '.join(cleanup_errors)}"
            with SessionLocal() as db:
                db.add(
                    SystemEvent(
                        device_id=device_id,
                        session_id=runtime.session_id,
                        level="error",
                        category="read_error",
                        message="Aquisição interrompida",
                        details={
                            "error": type(exc).__name__,
                            "message": str(exc),
                            "cleanup_errors": cleanup_errors,
                        },
                    )
                )
                db.commit()
            await websocket_hub.publish(
                "device.status",
                {"device_id": device_id, "state": "error", "message": "Falha de aquisição"},
            )

    async def _flush(self, device_id: int, runtime: DeviceRuntime) -> None:
        if not runtime.buffer or not runtime.session_id:
            runtime.buffer.clear()
            runtime.last_flush = monotonic()
            return
        readings = runtime.buffer[:]
        session_id = runtime.session_id
        with SessionLocal() as db:
            role = (
                db.scalar(
                    select(SessionDevice.role).where(
                        SessionDevice.session_id == session_id,
                        SessionDevice.device_id == device_id,
                    )
                )
                or "combined"
            )
            channels = {
                channel.channel: channel
                for channel in db.scalars(
                    select(ChannelConfiguration).where(ChannelConfiguration.device_id == device_id)
                )
            }
            for sequence, reading in enumerate(readings, runtime.persisted_count + 1):
                if role in {"combined", "electrical"}:
                    db.add(
                        ElectricalSample(
                            session_id=session_id,
                            device_id=device_id,
                            device_timestamp=reading.device_timestamp,
                            received_timestamp=reading.received_timestamp,
                            active_power_w=reading.power_w,
                            voltage_v=reading.voltage_v,
                            current_a=reading.current_a,
                            apparent_power_va=reading.apparent_power_va,
                            reactive_power_var=reading.reactive_power_var,
                            power_factor=reading.power_factor,
                            voltage_frequency_hz=reading.voltage_frequency_hz,
                            current_frequency_hz=reading.current_frequency_hz,
                            original_values=reading.raw_values
                            or {"active_power": reading.raw_power},
                            original_units=reading.raw_units
                            or {"active_power": reading.raw_power_unit},
                            quality=reading.quality,
                            source="live",
                            sequence=sequence,
                            raw_payload=reading.raw_payload,
                        )
                    )
                corrected_values: list[tuple[int, float | None]] = []
                for index, value in enumerate(reading.temperatures_c[:32], 1):
                    config = channels.get(index)
                    corrected = value
                    if value is not None and config:
                        corrected = value + config.correction_offset
                    corrected_values.append((index, corrected))
                if role in {"combined", "temperature"} and corrected_values:
                    temperature_sample = TemperatureSample(
                        session_id=session_id,
                        device_id=device_id,
                        device_timestamp=reading.device_timestamp,
                        received_timestamp=reading.received_timestamp,
                        ambient_temperature_c=reading.ambient_temperature_c,
                        quality=reading.quality,
                        source="live",
                        sequence=sequence,
                        raw_payload=reading.raw_payload,
                    )
                    temperature_sample.channels = [
                        TemperatureChannelValue(
                            channel=index,
                            temperature_c=corrected,
                            original_value=reading.temperatures_c[index - 1],
                            original_unit="°C",
                            quality=(
                                reading.channel_quality[index - 1]
                                if index <= len(reading.channel_quality)
                                else "missing"
                                if value is None
                                else "good"
                            ),
                        )
                        for (index, corrected), value in zip(
                            corrected_values, reading.temperatures_c, strict=False
                        )
                    ]
                    db.add(temperature_sample)
                if (
                    role == "combined"
                    and reading.power_w is not None
                    and reading.raw_power is not None
                ):
                    measurement = Measurement(
                        session_id=session_id,
                        timestamp=reading.timestamp,
                        power_w=reading.power_w,
                        raw_power=reading.raw_power,
                        raw_power_unit=reading.raw_power_unit,
                        quality=reading.quality,
                    )
                    measurement.temperatures = [
                        TemperatureMeasurement(
                            channel=index,
                            temperature_c=corrected,
                            quality="missing" if corrected is None else "good",
                        )
                        for index, corrected in corrected_values
                    ]
                    db.add(measurement)
            db.commit()
        del runtime.buffer[: len(readings)]
        runtime.persisted_count += len(readings)
        runtime.last_flush = monotonic()

    async def _evaluate_alerts(
        self, device_id: int, runtime: DeviceRuntime, reading: DeviceReading
    ) -> None:
        if not runtime.session_id:
            return
        now = monotonic()
        created: list[dict] = []
        with SessionLocal() as db:
            rules = db.scalars(
                select(AlertRule).where(
                    AlertRule.device_id == device_id, AlertRule.enabled.is_(True)
                )
            ).all()
            for rule in rules:
                values: list[tuple[int | None, float]] = []
                if rule.metric == "power" and reading.power_w is not None:
                    values = [(None, reading.power_w)]
                elif rule.metric == "temperature":
                    values = [
                        (index, value)
                        for index, value in enumerate(reading.temperatures_c, 1)
                        if value is not None and (rule.channel is None or rule.channel == index)
                    ]
                for channel, value in values:
                    key = (rule.id, channel)
                    if not _compare(value, rule.operator, rule.threshold):
                        continue
                    if now - runtime.last_alerts.get(key, -1e12) < rule.cooldown_seconds:
                        continue
                    runtime.last_alerts[key] = now
                    event = AlertEvent(
                        session_id=runtime.session_id,
                        rule_id=rule.id,
                        metric=rule.metric,
                        channel=channel,
                        measured_value=value,
                        threshold=rule.threshold,
                        severity=rule.severity,
                    )
                    db.add(event)
                    db.flush()
                    created.append(
                        {
                            "id": event.id,
                            "session_id": runtime.session_id,
                            "metric": rule.metric,
                            "channel": channel,
                            "measured_value": value,
                            "threshold": rule.threshold,
                            "severity": rule.severity,
                        }
                    )
            db.commit()
        for alert in created:
            await websocket_hub.publish("alert.created", alert)


acquisition_service = AcquisitionService()
