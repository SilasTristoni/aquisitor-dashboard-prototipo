from __future__ import annotations

import csv
import io
from bisect import bisect_left
from copy import copy
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.core.version import APPLICATION_VERSION
from app.schemas.contracts import PeriodReportRequest

NAVY = "17233F"
BLUE = "2563EB"
PALE_BLUE = "EAF0FF"
PALE_GRAY = "F3F6FB"
WHITE = "FFFFFF"


def _local_excel(value: datetime, zone: ZoneInfo) -> datetime:
    localized = value.astimezone(zone)
    return localized.replace(tzinfo=None)


def _header(sheet: Any, row: int, columns: int) -> None:
    for cell in sheet[row][:columns]:
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.font = Font(color=WHITE, bold=True)
        cell.alignment = Alignment(horizontal="center")


def _finish_sheet(sheet: Any, freeze: str = "A2") -> None:
    sheet.freeze_panes = freeze
    sheet.auto_filter.ref = sheet.dimensions
    for column in range(1, sheet.max_column + 1):
        values = [str(sheet.cell(row, column).value or "") for row in range(1, sheet.max_row + 1)]
        sheet.column_dimensions[get_column_letter(column)].width = min(
            34, max(11, max(map(len, values), default=0) + 2)
        )


def synchronized_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Create the visualization grid without changing either real source stream."""
    tolerance = data["request"].sync_tolerance_ms / 1000
    rows: list[dict[str, Any]] = []
    for session in data["sessions"]:
        session_id = session["id"]
        electrical = sorted(
            (point for point in data["electrical"] if point["session_id"] == session_id),
            key=lambda point: point["timestamp"],
        )
        temperatures = sorted(
            (point for point in data["temperatures"] if point["session_id"] == session_id),
            key=lambda point: point["timestamp"],
        )
        electrical_times = [point["timestamp"] for point in electrical]
        if not temperatures:
            rows.extend({**point, "channels": {}} for point in electrical)
            continue
        for temperature in temperatures:
            nearest = None
            index = bisect_left(electrical_times, temperature["timestamp"])
            candidates = electrical[max(0, index - 1) : index + 1]
            if candidates:
                candidate = min(
                    candidates,
                    key=lambda point: abs(
                        (point["timestamp"] - temperature["timestamp"]).total_seconds()
                    ),
                )
                if (
                    abs((candidate["timestamp"] - temperature["timestamp"]).total_seconds())
                    <= tolerance
                ):
                    nearest = candidate
            rows.append(
                {
                    "session_id": session_id,
                    "timestamp": temperature["timestamp"],
                    "temperature_sample_timestamp": temperature["timestamp"],
                    "electrical_sample_timestamp": nearest["timestamp"] if nearest else None,
                    "channels": temperature["channels"],
                    "ambient_temperature_c": temperature["ambient_temperature_c"],
                    "active_power_w": nearest["active_power_w"] if nearest else None,
                    "voltage_v": nearest["voltage_v"] if nearest else None,
                    "current_a": nearest["current_a"] if nearest else None,
                    "apparent_power_va": nearest["apparent_power_va"] if nearest else None,
                    "reactive_power_var": nearest["reactive_power_var"] if nearest else None,
                    "power_factor": nearest["power_factor"] if nearest else None,
                    "voltage_frequency_hz": nearest["voltage_frequency_hz"] if nearest else None,
                }
            )
    return rows


def _append_synchronized(
    sheet: Any,
    rows: list[dict[str, Any]],
    channels: list[int],
    zone: ZoneInfo,
) -> None:
    sheet.append(
        [
            "Sessão",
            "Timestamp",
            "Potência ativa (W)",
            *[f"T{channel} (°C)" for channel in channels],
            "Tensão (V)",
            "Corrente (A)",
            "Potência aparente (VA)",
            "Potência reativa (var)",
            "Fator de potência",
            "Frequência (Hz)",
        ]
    )
    for row in rows:
        sheet.append(
            [
                row["session_id"],
                _local_excel(row["timestamp"], zone),
                row.get("active_power_w"),
                *[row["channels"].get(channel) for channel in channels],
                row.get("voltage_v"),
                row.get("current_a"),
                row.get("apparent_power_va"),
                row.get("reactive_power_var"),
                row.get("power_factor"),
                row.get("voltage_frequency_hz"),
            ]
        )
    _header(sheet, 1, sheet.max_column)
    for cell in sheet["B"][1:]:
        cell.number_format = "dd/mm/yyyy hh:mm:ss"
    _finish_sheet(sheet)


def _add_curve_chart(sheet: Any, channels: list[int], anchor: str) -> None:
    if sheet.max_row < 3:
        return
    temperature_chart = LineChart()
    temperature_chart.title = "Temperaturas e potência — período analisado"
    temperature_chart.y_axis.title = "Temperatura (°C)"
    temperature_chart.x_axis.title = "Tempo"
    temperature_chart.height = 11
    temperature_chart.width = 24
    categories = Reference(sheet, min_col=2, min_row=2, max_row=sheet.max_row)
    if channels:
        temperature_chart.add_data(
            Reference(
                sheet,
                min_col=4,
                max_col=3 + len(channels),
                min_row=1,
                max_row=sheet.max_row,
            ),
            titles_from_data=True,
        )
    temperature_chart.set_categories(categories)
    power_chart = LineChart()
    power_chart.add_data(
        Reference(sheet, min_col=3, min_row=1, max_row=sheet.max_row),
        titles_from_data=True,
    )
    power_chart.set_categories(categories)
    power_chart.y_axis.title = "Potência (W)"
    power_chart.y_axis.axId = 200
    power_chart.y_axis.crosses = "max"
    power_chart.y_axis.majorGridlines = None
    temperature_chart += power_chart
    sheet.add_chart(temperature_chart, anchor)


def render_period_xlsx(data: dict[str, Any], request: PeriodReportRequest) -> bytes:
    zone = ZoneInfo(request.timezone)
    workbook = Workbook()
    summary = workbook.active
    summary.title = "Resumo Executivo"
    channels = data["selected_channels"]
    channel_stats = [item for item in data["statistics"]["channels"] if item["count"]]
    general = data["statistics"]["general"]
    electrical = data["statistics"]["electrical"]
    temperature = data["statistics"]["temperature"]
    summary.merge_cells("A1:H2")
    summary["A1"] = "THERMOPOWER MONITOR\nRelatório Técnico de Ensaio Térmico e Elétrico"
    summary["A1"].font = Font(size=18, bold=True, color=WHITE)
    summary["A1"].fill = PatternFill("solid", fgColor=NAVY)
    summary["A1"].alignment = Alignment(vertical="center", wrap_text=True)
    summary["A4"] = request.title
    summary["A4"].font = Font(size=15, bold=True, color=NAVY)
    summary["A5"] = "Período analisado"
    summary["B5"] = _local_excel(request.start, zone)
    summary["C5"] = _local_excel(request.end, zone)
    summary["B5"].number_format = summary["C5"].number_format = "dd/mm/yyyy hh:mm:ss"
    kpis = [
        ("Amostras elétricas", general["electrical_sample_count"]),
        ("Amostras térmicas", general["temperature_sample_count"]),
        ("Potência média (W)", electrical["active_power_w"]["mean"]),
        ("Potência máxima (W)", electrical["active_power_w"]["max"]),
        ("Energia (Wh)", electrical["energy_wh"]),
        ("Temperatura máxima (°C)", temperature["max"]),
        ("Canal crítico", temperature["critical_channel_label"]),
        (
            "ΔT máximo (°C)",
            temperature["maximum_delta_t"]["value_c"] if temperature["maximum_delta_t"] else None,
        ),
    ]
    for index, (label, value) in enumerate(kpis):
        row = 7 + index // 4 * 3
        column = 1 + (index % 4) * 2
        summary.cell(row, column, label)
        summary.cell(row + 1, column, value)
        summary.cell(row, column).font = Font(size=9, color="64748B", bold=True)
        summary.cell(row + 1, column).font = Font(size=14, color=NAVY, bold=True)
        summary.cell(row, column).fill = summary.cell(row + 1, column).fill = PatternFill(
            "solid", fgColor=PALE_BLUE
        )
    table_row = 14
    summary.append([])
    summary.cell(table_row, 1, "Canal")
    summary.cell(table_row, 2, "Identificação")
    summary.cell(table_row, 3, "Amostras")
    summary.cell(table_row, 4, "Média (°C)")
    summary.cell(table_row, 5, "Máx (°C)")
    summary.cell(table_row, 6, "Mín (°C)")
    summary.cell(table_row, 7, "ΔT (°C)")
    summary.cell(table_row, 8, "P95 (°C)")
    _header(summary, table_row, 8)
    for item in channel_stats:
        summary.append(
            [
                f"T{item['channel']}",
                item["friendly_name"],
                item["count"],
                item["mean"],
                item["max"],
                item["min"],
                item["range"],
                item["p95"],
            ]
        )
    summary.column_dimensions["A"].width = 22
    for column in "BCDEFGH":
        summary.column_dimensions[column].width = 18
    summary.freeze_panes = "A5"

    synchronized = synchronized_rows(data)
    curves = workbook.create_sheet("Curvas do Ensaio")
    _append_synchronized(curves, synchronized, channels, zone)
    _add_curve_chart(curves, channels, "A4")

    stabilized = workbook.create_sheet("Análise Estabilizada")
    _append_synchronized(stabilized, synchronized, channels, zone)

    channel_sheet = workbook.create_sheet("Estatística por Canal")
    channel_sheet.append(
        [
            "Canal",
            "Nome",
            "Amostras",
            "Média",
            "Mínimo",
            "Máximo",
            "Mediana",
            "Desvio padrão",
            "P95",
            "Amplitude",
            "Taxa °C/min",
            "Disponibilidade (%)",
        ]
    )
    for item in data["statistics"]["channels"]:
        channel_sheet.append(
            [
                f"T{item['channel']}",
                item["friendly_name"],
                item["count"],
                item["mean"],
                item["min"],
                item["max"],
                item["median"],
                item["standard_deviation"],
                item["p95"],
                item["range"],
                item["heating_rate_c_per_minute"],
                item["availability_percent"],
            ]
        )
    _header(channel_sheet, 1, channel_sheet.max_column)
    _finish_sheet(channel_sheet)

    electric_sheet = workbook.create_sheet("Grandezas Elétricas")
    electric_sheet.append(
        ["Grandeza", "Amostras", "Média", "Mínimo", "Máximo", "Mediana", "Desvio", "P95"]
    )
    electric_labels = {
        "active_power_w": "Potência ativa (W)",
        "voltage_v": "Tensão (V)",
        "current_a": "Corrente (A)",
        "apparent_power_va": "Potência aparente (VA)",
        "reactive_power_var": "Potência reativa (var)",
        "power_factor": "Fator de potência",
        "voltage_frequency_hz": "Frequência (Hz)",
    }
    for key, label in electric_labels.items():
        item = electrical[key]
        electric_sheet.append(
            [
                label,
                item["count"],
                item["mean"],
                item["min"],
                item["max"],
                item["median"],
                item["standard_deviation"],
                item["p95"],
            ]
        )
    electric_sheet.append(["Energia (Wh)", None, electrical["energy_wh"]])
    _header(electric_sheet, 1, electric_sheet.max_column)
    _finish_sheet(electric_sheet)

    real_electrical = workbook.create_sheet("Amostras Elétricas Reais")
    real_electrical.append(
        [
            "Sessão",
            "Timestamp original",
            "Tensão (V)",
            "Corrente (A)",
            "Potência ativa (W)",
            "Potência aparente (VA)",
            "Potência reativa (var)",
            "Fator de potência",
            "Frequência tensão (Hz)",
            "Frequência corrente (Hz)",
            "Qualidade",
        ]
    )
    for point in data["electrical"]:
        real_electrical.append(
            [
                point["session_id"],
                _local_excel(point["timestamp"], zone),
                point["voltage_v"],
                point["current_a"],
                point["active_power_w"],
                point["apparent_power_va"],
                point["reactive_power_var"],
                point["power_factor"],
                point["voltage_frequency_hz"],
                point["current_frequency_hz"],
                point["quality"],
            ]
        )
    _header(real_electrical, 1, real_electrical.max_column)
    for cell in real_electrical["B"][1:]:
        cell.number_format = "dd/mm/yyyy hh:mm:ss.000"
    _finish_sheet(real_electrical)

    real_thermal = workbook.create_sheet("Amostras Térmicas Reais")
    real_thermal.append(
        [
            "Sessão",
            "Timestamp original",
            "Ambiente (°C)",
            *[f"T{channel} (°C)" for channel in channels],
            "Qualidade",
        ]
    )
    for point in data["temperatures"]:
        real_thermal.append(
            [
                point["session_id"],
                _local_excel(point["timestamp"], zone),
                point["ambient_temperature_c"],
                *[point["channels"].get(channel) for channel in channels],
                point["quality"],
            ]
        )
    _header(real_thermal, 1, real_thermal.max_column)
    for cell in real_thermal["B"][1:]:
        cell.number_format = "dd/mm/yyyy hh:mm:ss.000"
    _finish_sheet(real_thermal)

    synchronized_sheet = workbook.create_sheet("Dados Sincronizados")
    _append_synchronized(synchronized_sheet, synchronized, channels, zone)

    metadata_sheet = workbook.create_sheet("Metadados")
    metadata_sheet.append(["Campo", "Valor"])
    metadata_sheet.append(["Versão", APPLICATION_VERSION])
    metadata_sheet.append(["Fuso horário", request.timezone])
    metadata_sheet.append(["Início analisado", _local_excel(request.start, zone)])
    metadata_sheet.append(["Fim analisado", _local_excel(request.end, zone)])
    for session in data["sessions"]:
        metadata_sheet.append([f"Sessão #{session['id']}", session["name"]])
        metadata_sheet.append(["Operador", session["operator"] or "Operador não informado"])
        for key, value in session.get("metadata", {}).items():
            if value not in (None, ""):
                metadata_sheet.append([key, value])
        for device in session["devices"]:
            identity = " ".join(
                str(value) for value in (device.get("manufacturer"), device.get("model")) if value
            )
            metadata_sheet.append(
                [f"Fonte {device.get('role', 'combined')}", identity or device["name"]]
            )
            for key in ("serial_number", "port", "baud_rate", "cadence_ms"):
                if device.get(key) is not None:
                    metadata_sheet.append([f"  {key}", device[key]])
    _header(metadata_sheet, 1, 2)
    _finish_sheet(metadata_sheet)

    # Reuse the same chart definition in the executive sheet while keeping its source data intact.
    if curves._charts:
        summary.add_chart(copy(curves._charts[0]), "J4")
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def render_period_csv(
    data: dict[str, Any], request: PeriodReportRequest, dataset: str = "synchronized"
) -> bytes:
    zone = ZoneInfo(request.timezone)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=";", lineterminator="\n")
    channels = data["selected_channels"]
    if dataset == "electrical":
        writer.writerow(
            [
                "sessao",
                "timestamp_original",
                "tensao_v",
                "corrente_a",
                "potencia_ativa_w",
                "potencia_aparente_va",
                "potencia_reativa_var",
                "fator_potencia",
                "frequencia_hz",
                "qualidade",
            ]
        )
        for point in data["electrical"]:
            writer.writerow(
                [
                    point["session_id"],
                    point["timestamp"].astimezone(zone).isoformat(),
                    point["voltage_v"],
                    point["current_a"],
                    point["active_power_w"],
                    point["apparent_power_va"],
                    point["reactive_power_var"],
                    point["power_factor"],
                    point["voltage_frequency_hz"],
                    point["quality"],
                ]
            )
    elif dataset == "thermal":
        writer.writerow(
            [
                "sessao",
                "timestamp_original",
                "temperatura_ambiente_c",
                *[f"temperatura_t{channel}_c" for channel in channels],
                "qualidade",
            ]
        )
        for point in data["temperatures"]:
            writer.writerow(
                [
                    point["session_id"],
                    point["timestamp"].astimezone(zone).isoformat(),
                    point["ambient_temperature_c"],
                    *[point["channels"].get(channel) for channel in channels],
                    point["quality"],
                ]
            )
    else:
        writer.writerow(
            [
                "sessao",
                "timestamp_grade",
                "timestamp_temperatura",
                "timestamp_eletrica",
                "potencia_ativa_w",
                *[f"temperatura_t{channel}_c" for channel in channels],
            ]
        )
        for row in synchronized_rows(data):
            writer.writerow(
                [
                    row["session_id"],
                    row["timestamp"].astimezone(zone).isoformat(),
                    row.get("temperature_sample_timestamp").astimezone(zone).isoformat()
                    if row.get("temperature_sample_timestamp")
                    else None,
                    row.get("electrical_sample_timestamp").astimezone(zone).isoformat()
                    if row.get("electrical_sample_timestamp")
                    else None,
                    row.get("active_power_w"),
                    *[row["channels"].get(channel) for channel in channels],
                ]
            )
    return ("\ufeff" + stream.getvalue()).encode("utf-8")
