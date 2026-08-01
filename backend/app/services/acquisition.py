import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import monotonic

from sqlalchemy import select

from app.adapters import (
    DeviceAdapter,
    DeviceReading,
    MockFailureAdapter,
    SerialCsvAdapter,
    SerialJsonAdapter,
    SimulatorAdapter,
)
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import (
    AlertEvent,
    AlertRule,
    ChannelConfiguration,
    Device,
    Measurement,
    SystemEvent,
    TemperatureMeasurement,
)
from app.schemas.contracts import SimulatorConfigInput
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
    task: asyncio.Task | None = None
    session_id: int | None = None
    paused: bool = False
    buffer: list[DeviceReading] = field(default_factory=list)
    last_flush: float = field(default_factory=monotonic)
    last_alerts: dict[tuple[int, int | None], float] = field(default_factory=dict)
    latest: DeviceReading | None = None


class AcquisitionService:
    def __init__(self) -> None:
        self.runtimes: dict[int, DeviceRuntime] = {}
        self.started_at = datetime.now(UTC)

    def _adapter_for(self, device: Device) -> DeviceAdapter:
        if device.protocol == "simulator":
            return SimulatorAdapter()
        if device.protocol == "serial_json":
            return SerialJsonAdapter(device.port, device.baud_rate)
        if device.protocol == "serial_csv":
            return SerialCsvAdapter(device.port, device.baud_rate)
        if device.protocol == "mock_failure":
            return MockFailureAdapter()
        raise ValueError(f"Protocolo não suportado: {device.protocol}")

    async def connect(self, device_id: int) -> dict:
        if device_id in self.runtimes:
            return await self.status(device_id)
        with SessionLocal() as db:
            device = db.get(Device, device_id)
            if not device or not device.active:
                raise ValueError("Equipamento não encontrado ou inativo")
            adapter = self._adapter_for(device)
            await adapter.connect()
            device.last_connected_at = datetime.now(UTC)
            db.add(
                SystemEvent(
                    device_id=device_id, category="connection", message="Equipamento conectado"
                )
            )
            db.commit()
        runtime = DeviceRuntime(adapter=adapter)
        self.runtimes[device_id] = runtime
        runtime.task = asyncio.create_task(self._read_loop(device_id, runtime))
        await websocket_hub.publish("device.status", {"device_id": device_id, "state": "connected"})
        return await self.status(device_id)

    async def disconnect(self, device_id: int) -> None:
        runtime = self.runtimes.get(device_id)
        if not runtime:
            return
        await self._flush(device_id, runtime)
        await runtime.adapter.stop_reading()
        await runtime.adapter.disconnect()
        if runtime.task:
            runtime.task.cancel()
            try:
                await runtime.task
            except asyncio.CancelledError:
                pass
        self.runtimes.pop(device_id, None)
        with SessionLocal() as db:
            db.add(
                SystemEvent(
                    device_id=device_id,
                    category="disconnection",
                    message="Equipamento desconectado",
                )
            )
            db.commit()
        await websocket_hub.publish(
            "device.status", {"device_id": device_id, "state": "disconnected"}
        )

    async def attach_session(self, device_id: int, session_id: int) -> None:
        if device_id not in self.runtimes:
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
            await self._flush(device_id, runtime)
            runtime.paused = True

    async def resume_session(self, device_id: int, session_id: int) -> None:
        await self.attach_session(device_id, session_id)

    async def detach_session(self, device_id: int) -> None:
        runtime = self.runtimes.get(device_id)
        if runtime:
            await self._flush(device_id, runtime)
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
            return {"device_id": device_id, "state": "disconnected", "connected": False}
        status = await runtime.adapter.get_status()
        return {
            "device_id": device_id,
            **status.model_dump(mode="json"),
            "session_id": runtime.session_id,
            "paused": runtime.paused,
            "buffered_measurements": len(runtime.buffer),
        }

    async def all_statuses(self) -> list[dict]:
        return [await self.status(device_id) for device_id in self.runtimes]

    async def _read_loop(self, device_id: int, runtime: DeviceRuntime) -> None:
        try:
            async for reading in runtime.adapter.start_reading():
                runtime.latest = reading
                payload = reading.model_dump(mode="json")
                payload.update({"device_id": device_id, "session_id": runtime.session_id})
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
            logger.exception("Acquisition loop failed for device %s", device_id)
            with SessionLocal() as db:
                db.add(
                    SystemEvent(
                        device_id=device_id,
                        session_id=runtime.session_id,
                        level="error",
                        category="read_error",
                        message="Aquisição interrompida",
                        details={"error": type(exc).__name__},
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
        runtime.buffer.clear()
        session_id = runtime.session_id
        with SessionLocal() as db:
            channels = {
                channel.channel: channel
                for channel in db.scalars(
                    select(ChannelConfiguration).where(ChannelConfiguration.device_id == device_id)
                )
            }
            for reading in readings:
                measurement = Measurement(
                    session_id=session_id,
                    timestamp=reading.timestamp,
                    power_w=reading.power_w,
                    raw_power=reading.raw_power,
                    raw_power_unit=reading.raw_power_unit,
                    quality=reading.quality,
                )
                for index, value in enumerate(reading.temperatures_c, 1):
                    config = channels.get(index)
                    corrected = value
                    if value is not None and config:
                        corrected = value + config.correction_offset
                    measurement.temperatures.append(
                        TemperatureMeasurement(
                            channel=index,
                            temperature_c=corrected,
                            quality="missing" if value is None else "good",
                        )
                    )
                db.add(measurement)
            db.commit()
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
                if rule.metric == "power":
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
