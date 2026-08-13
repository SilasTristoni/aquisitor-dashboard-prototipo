#!/usr/bin/env python3
"""Engineering-only probe using the exact ThermoPower protocol implementation."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from serial.tools import list_ports

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))

from app.adapters.specific import (  # noqa: E402
    AT4532_MANUAL_URL,
    GPM8213_MANUAL_URL,
)
from app.models.entities import Device  # noqa: E402
from app.services.protocol_probe import protocol_probe_service  # noqa: E402


def gpm_port() -> str:
    matches = [
        port.device
        for port in list_ports.comports()
        if port.serial_number == "GES913349"
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Esperada exatamente uma porta com serial GES913349; encontradas: {matches}"
        )
    return matches[0]


async def run(arguments: argparse.Namespace) -> int:
    is_at4532 = arguments.device == "at4532"
    port = arguments.port if is_at4532 or arguments.port != "auto" else gpm_port()
    source = AT4532_MANUAL_URL if is_at4532 else GPM8213_MANUAL_URL
    terminator = "LF" if is_at4532 else "CR+LF"
    print(f"Equipamento: {'AT4532' if is_at4532 else 'GPM-8213'}")
    print(f"Porta: {port}")
    print(f"Parâmetros: 8-N-1, sem flow control, terminador {terminator}")
    print(f"Fonte oficial: {source}")
    print("Serão enviados somente comandos documentados oficialmente pelo fabricante.")
    if (
        not arguments.yes
        and input("Digite ENVIAR para confirmar: ").strip() != "ENVIAR"
    ):
        print("Operação cancelada; nenhum comando foi enviado.")
        return 2

    device = Device(
        id=0,
        name="Protocol probe",
        manufacturer="Applent" if is_at4532 else "GW Instek",
        model="AT4532" if is_at4532 else "GPM-8213",
        serial_number=None if is_at4532 else "GES913349",
        connection_type="serial",
        port=port,
        baud_rate=19200 if is_at4532 else None,
        protocol="at4532_serial" if is_at4532 else "gpm8213_serial",
        active=True,
        metadata_json={},
    )
    result = await protocol_probe_service.run(device, arguments.mode)
    output = Path(arguments.output).resolve()
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Resultado: {result['result']}")
    print(f"Arquivo: {output}")
    return 0 if result["result"] == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("device", choices=("at4532", "gpm8213"))
    parser.add_argument("port", help="COM explícita ou auto para o GPM-8213")
    parser.add_argument("--mode", choices=("identity", "read", "full"), default="full")
    parser.add_argument("--output", default="protocol-probe-result.json")
    parser.add_argument(
        "--yes", action="store_true", help="confirma o envio sem prompt"
    )
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
