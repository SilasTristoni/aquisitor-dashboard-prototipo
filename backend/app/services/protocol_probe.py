from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, Literal

from app.adapters.specific import At4532SerialAdapter, Gpm8213UsbSerialAdapter
from app.models.entities import Device
from app.services.device_policy import at4532_identity_fallback_policy

logger = logging.getLogger(__name__)
ProbeMode = Literal["identity", "read", "full"]


class ProtocolProbeService:
    def __init__(self) -> None:
        self.latest_results: dict[int, dict[str, Any]] = {}

    async def run(self, device: Device, mode: ProbeMode) -> dict[str, Any]:
        if device.protocol == "at4532_serial":
            policy = at4532_identity_fallback_policy(device)
            adapter = At4532SerialAdapter(
                device.port,
                device.baud_rate,
                allow_identity_fallback=policy.allowed and mode in {"read", "full"},
                association_source=policy.association_source,
            )
        elif device.protocol == "gpm8213_serial":
            adapter = Gpm8213UsbSerialAdapter(device.port, device.baud_rate)
        else:
            raise ValueError("O probe documentado aceita apenas AT4532 ou GPM-8213.")

        stages = [
            self._stage("usb", "USB detectado", bool(device.port)),
            self._stage("identity", "Identidade", False),
            self._stage("port", "Porta", False),
            self._stage("protocol", "Protocolo", False),
            self._stage("configuration", "Configuração", False),
            self._stage("reading", "Leitura", False),
            self._stage("acquisition", "Aquisição", False),
        ]
        readings: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        result = "failed"
        configuration: dict[str, Any] = {}
        identity: dict[str, Any] = {}
        try:
            configuration = adapter._configuration().public_dict()
            await adapter.connect()
            if adapter.identity_status == "confirmed":
                stages[1] = self._stage("identity", "Identidade", True, "Resposta validada.")
            else:
                stages[1] = self._stage(
                    "identity",
                    "Identidade",
                    False,
                    "*IDN? não respondeu; protocolo validado pela medição documentada.",
                    status="warning",
                )
            stages[2] = self._stage("port", "Porta", True, "Porta aberta.")
            stages[3] = self._stage(
                "protocol", "Protocolo", True, "Comando oficial respondido e interpretado."
            )
            stages[4] = self._stage(
                "configuration",
                "Configuração",
                True,
                "Unidade Celsius configurada."
                if device.protocol == "at4532_serial"
                else "Quantidade e cabeçalhos consultados e validados.",
            )
            identity = (await adapter.get_device_information()).model_dump(mode="json")
            if mode in {"read", "full"}:
                readings.append((await adapter.read_once()).model_dump(mode="json"))
                stages[5] = self._stage(
                    "reading", "Leitura", True, "Resposta de medição interpretada."
                )
            if mode == "full":
                await asyncio.sleep(adapter.expected_interval_seconds)
                readings.append((await adapter.read_once()).model_dump(mode="json"))
                stages[6] = self._stage(
                    "acquisition", "Aquisição", True, "Duas leituras consecutivas válidas."
                )
            result = "passed_with_warning" if adapter.identity_status == "unconfirmed" else "passed"
        except Exception as exc:
            logger.exception("protocol probe failed device_id=%s mode=%s", device.id, mode)
            error = {"code": getattr(exc, "code", type(exc).__name__), "message": str(exc)}
            error.update(getattr(exc, "details", {}))
            errors.append(error)
            at_fallback_attempted = (
                device.protocol == "at4532_serial"
                and adapter.identity_status == "unconfirmed"
                and getattr(adapter, "allow_identity_fallback", False)
            )
            if at_fallback_attempted:
                stages[1] = self._stage(
                    "identity",
                    "Identidade",
                    False,
                    "*IDN? não respondeu; a validação funcional prosseguiu.",
                    status="warning",
                )
                stages[2] = self._stage("port", "Porta", True, "Porta aberta.")
                configured = any(
                    transaction["command_name"] == "configure_celsius"
                    and not transaction.get("error")
                    for transaction in adapter.transactions
                )
                fetch = next(
                    (
                        transaction
                        for transaction in reversed(adapter.transactions)
                        if transaction["command_name"] == "temperatures"
                    ),
                    None,
                )
                stages[3] = self._stage(
                    "protocol",
                    "Protocolo",
                    bool(fetch and fetch.get("bytes_received")),
                    "FETCH? respondeu; parser/critério de leitura falhou."
                    if fetch and fetch.get("bytes_received")
                    else "FETCH? não produziu uma resposta classificável.",
                    status="passed" if fetch and fetch.get("bytes_received") else "failed",
                )
                stages[4] = self._stage(
                    "configuration",
                    "Configuração",
                    configured,
                    "SYST:UNIT CEL transmitido." if configured else "Configuração não concluída.",
                    status="passed" if configured else "failed",
                )
                stages[5]["status"] = "failed"
                stages[5]["message"] = str(exc)
            elif adapter._identity and stages[4]["status"] == "pending":
                stages[1] = self._stage(
                    "identity", "Identidade", True, "Resposta de identidade validada."
                )
                stages[2] = self._stage("port", "Porta", True, "Porta aberta.")
                stages[3] = self._stage(
                    "protocol", "Protocolo", True, "SCPI básico respondido e interpretado."
                )
                stages[4]["status"] = "failed"
                stages[4]["message"] = str(exc)
            else:
                first_pending = next(
                    (index for index, stage in enumerate(stages) if stage["status"] == "pending"),
                    None,
                )
                if first_pending is not None:
                    stages[first_pending]["status"] = "failed"
                    stages[first_pending]["message"] = str(exc)
        finally:
            try:
                await adapter.disconnect()
            except Exception as exc:
                errors.append({"code": "close_failed", "message": str(exc)})

        for transaction in adapter.transactions:
            transaction.setdefault("parsed", {})
        report = {
            "device_id": device.id,
            "device": adapter.equipment,
            "timestamp": datetime.now(UTC).isoformat(),
            "port": device.port,
            "serial_parameters": configuration,
            "serial_open_boundary": adapter.serial_open_boundary,
            "parameters_source": "vendor_documented",
            "physical_validation": "pending",
            "identity": identity,
            "identity_status": getattr(
                adapter, "identity_status", "confirmed" if identity else "unconfirmed"
            ),
            "protocol_status": getattr(adapter, "protocol_status", "not_verified"),
            "identity_error": getattr(adapter, "identity_error", None),
            "identity_fallback_policy": policy.public_dict()
            if device.protocol == "at4532_serial"
            else None,
            "transactions": adapter.transactions,
            "readings": readings,
            "stages": stages,
            "result": result,
            "errors": errors,
        }
        if device.protocol == "at4532_serial" and readings:
            raw = readings[-1].get("raw_payload", {})
            report["at4532_channel_summary"] = {
                "channel_count_requested": raw.get("channel_count_requested", 32),
                "channel_count_received": raw.get("channel_count_received", 0),
                "valid_channels": raw.get("valid_channels", 0),
                "unavailable_channels": raw.get("unavailable_channels", 32),
                "valid_channel_results": raw.get("valid_channel_results", {}),
                "channels": raw.get("channels", []),
                "unknown_tokens": raw.get("unknown_tokens", []),
            }
        self.latest_results[device.id] = report
        return report

    @staticmethod
    def _stage(
        key: str,
        label: str,
        passed: bool,
        message: str = "",
        *,
        status: str | None = None,
    ) -> dict[str, str]:
        return {
            "key": key,
            "label": label,
            "status": status or ("passed" if passed else "pending"),
            "message": message,
        }


protocol_probe_service = ProtocolProbeService()
