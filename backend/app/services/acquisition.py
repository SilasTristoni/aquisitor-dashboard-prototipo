import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import monotonic

from sqlalchemy import select

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


class AcquisitionService:
    def __init__(self) -> None:
        self.runtimes: dict[int, DeviceRuntime] = {}
        self.last_connection_results: dict[int, dict] = {}
        self._device_locks: dict[int, asyncio.Lock] = {}
        self._port_locks: dict[str, asyncio.Lock] = {}
        self.started_at = datetime.now(UTC)

    def _device_lock(self, device_id: int) -> asyncio.Lock:
        return self._device_locks.setdefault(device_id, asyncio.Lock())

    def _port_lock(self, port: str) -> asyncio.Lock:
        return self._port_locks.setdefault(port.casefold(), asyncio.Lock())

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
                usb_discovery_service.discover(db)
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
                    logger.exception(
                        "failed to persist connection error device_id=%s", device_id
                    )
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
                logger.exception(
                    "failed to persist disconnection error device_id=%s", device_id
                )
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
        return {
            "device_id": device_id,
            **status.model_dump(mode="json"),
            "state": "error" if runtime_failed else status.state,
            "reading": False if runtime_failed else status.reading,
            "device_name": runtime.device_name,
            "protocol": runtime.protocol,
            "source_role": runtime.source_role,
            "session_id": runtime.session_id,
            "paused": runtime.paused,
            "buffered_measurements": len(runtime.buffer),
            "sample_count": runtime.sample_count,
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
                runtime.latest = reading
                runtime.sample_count += 1
                runtime.last_error = None
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
                if runtime.session_id and not runtime.paused:
                    runtime.buffer.append(reading)
                    await self._evaluate_alerts(device_id, runtime, reading)
                    if (
                        len(runtime.buffer) >= settings.measurement_batch_size
                        or monotonic() - runtime.last_flush >= 2
                    ):
                        await self._flush(device_id, runtime)
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
            for sequence, reading in enumerate(readings, 1):
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
