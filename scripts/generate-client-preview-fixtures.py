"""Generate deterministic, synthetic report artifacts for visual release review."""

from __future__ import annotations

import argparse
import math
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))

from app.schemas.contracts import PeriodReportRequest  # noqa: E402
from app.services.period_documents import (  # noqa: E402
    render_executive_summary,
    render_period_chart,
    render_period_pdf,
)
from app.services.period_reporting import period_statistics  # noqa: E402
from app.services.period_workbook import render_period_xlsx  # noqa: E402


def fixture_data() -> tuple[dict, PeriodReportRequest]:
    start = datetime(2026, 9, 3, 13, 0, tzinfo=UTC)
    end = start + timedelta(hours=2)
    request = PeriodReportRequest(
        start=start,
        end=end,
        title="Ensaio combinado — validação térmica e elétrica",
        subtitle="Relatório Técnico de Ensaio Térmico e Elétrico",
        description="Fixture sintética determinística para revisão visual da build de cliente.",
        notes="Valores exclusivamente sintéticos; não representam uma amostra de produção.",
        channels=list(range(24, 33)),
        include_open_channels=True,
        table_max_rows=0,
        dpi=140,
    )
    names = {
        24: "T24",
        25: "Entrada de ar",
        26: "Saída de ar",
        27: "Carcaça superior",
        28: "Carcaça lateral",
        29: "Resistência",
        30: "Painel frontal",
        31: "Cabo de alimentação",
        32: "Ambiente interno",
    }
    electrical = []
    temperatures = []
    for index in range(721):
        timestamp = start + timedelta(seconds=index * 10)
        elapsed_minutes = index / 6
        cycle_on = (index // 30) % 2 == 0
        active_power = (1120 if cycle_on else 160) + 35 * math.sin(index / 13)
        electrical.append(
            {
                "session_id": 1,
                "device_id": 2,
                "timestamp": timestamp,
                "timestamp_source": "device",
                "quality": "good",
                "source": "fixture",
                "voltage_v": 220 + 1.2 * math.sin(index / 31),
                "current_a": active_power / 220,
                "active_power_w": active_power,
                "apparent_power_va": active_power / 0.96,
                "reactive_power_var": 130 + 8 * math.sin(index / 17),
                "power_factor": 0.96,
                "voltage_frequency_hz": 60,
                "current_frequency_hz": 60,
            }
        )
        values = {24: None}
        for channel in range(25, 33):
            target = 58 + (channel - 25) * 3.2
            if elapsed_minutes < 48:
                value = 24 + (target - 24) * elapsed_minutes / 48
            else:
                value = target + 0.15 * math.sin(index / 23 + channel)
            values[channel] = value
        temperatures.append(
            {
                "session_id": 1,
                "device_id": 1,
                "timestamp": timestamp,
                "timestamp_source": "device",
                "quality": "good",
                "source": "fixture",
                "ambient_temperature_c": 23.5,
                "channels": values,
                "channel_names": names,
            }
        )
    session = {
        "id": 1,
        "name": "Ensaio combinado — amostra de revisão",
        "started_at": start.isoformat(),
        "ended_at": end.isoformat(),
        "status": "finished",
        "operator": "Engenharia de Produto",
        "metadata": {
            "product": "Produto sintético de validação",
            "model": "TP-Preview",
            "sample": "Amostra de revisão visual",
            "code": "FIXTURE-006",
            "nominal_voltage": "220 V",
            "setpoint": "80 °C",
            "responsible": "Engenharia de Produto",
            "location": "Laboratório de Ensaios",
        },
        "devices": [
            {
                "id": 1,
                "name": "AT4532",
                "role": "temperature",
                "manufacturer": "Applent Instruments",
                "model": "AT4532",
                "serial_number": "FIXTURE-AT",
                "port": "COM5",
                "baud_rate": 19200,
                "cadence_ms": 3000,
            },
            {
                "id": 2,
                "name": "GPM-8213",
                "role": "electrical",
                "manufacturer": "GW Instek",
                "model": "GPM-8213",
                "serial_number": "FIXTURE-GPM",
                "port": "COM4",
                "baud_rate": 9600,
                "cadence_ms": 1000,
            },
        ],
        "electrical_samples": len(electrical),
        "temperature_samples": len(temperatures),
    }
    data = {
        "request": request,
        "sessions": [session],
        "electrical": electrical,
        "temperatures": temperatures,
        "selected_channels": list(range(24, 33)),
        "alerts": [],
        "timestamp_fallback_count": 0,
        "table_rows": [],
    }
    data["statistics"] = period_statistics(data)
    return data, request


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "build" / "client-preview-review",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    data, request = fixture_data()
    artifacts = {
        "relatorio-tecnico.pdf": render_period_pdf(data, request),
        "resumo-executivo.pdf": render_executive_summary(data, request, "pdf"),
        "resumo-executivo.png": render_executive_summary(data, request, "png"),
        "curvas-do-ensaio.png": render_period_chart(data, request, "png"),
        "relatorio-tecnico.xlsx": render_period_xlsx(data, request),
    }
    for name, content in artifacts.items():
        (args.output / name).write_bytes(content)
        print(f"{name}: {len(content)} bytes")


if __name__ == "__main__":
    main()
