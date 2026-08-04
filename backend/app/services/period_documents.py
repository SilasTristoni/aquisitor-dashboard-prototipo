from __future__ import annotations

import io
import re
import unicodedata
from datetime import UTC, datetime
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.schemas.contracts import PeriodReportRequest
from app.services.period_reporting import downsample_time_buckets

CHANNEL_COLORS = [
    "#2563EB",
    "#16A34A",
    "#D97706",
    "#DC2626",
    "#7C3AED",
    "#0891B2",
    "#DB2777",
    "#4F46E5",
    "#65A30D",
    "#EA580C",
    "#0D9488",
    "#9333EA",
    "#E11D48",
    "#0284C7",
    "#CA8A04",
    "#475569",
]


def safe_report_filename(title: str, extension: str) -> str:
    normalized = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", normalized).strip("-._").lower()
    return f"{(stem or 'relatorio-thermopower')[:80]}.{extension}"


def _segments(
    points: list[dict[str, Any]], gap_seconds: float = 60.0
) -> list[list[dict[str, Any]]]:
    if not points:
        return []
    ordered = sorted(points, key=lambda item: item["timestamp"])
    result = [[ordered[0]]]
    for point in ordered[1:]:
        if (point["timestamp"] - result[-1][-1]["timestamp"]).total_seconds() > gap_seconds:
            result.append([])
        result[-1].append(point)
    return result


def render_period_chart(
    data: dict[str, Any], request: PeriodReportRequest, image_type: str = "png"
) -> bytes:
    channels = data["selected_channels"] if request.include_temperatures else []
    channel_groups = [
        channels[index : index + request.channel_group_size]
        for index in range(0, len(channels), request.channel_group_size)
    ]
    if not channel_groups:
        channel_groups = [[]]
    extra_electrical = int(request.include_electrical_details)
    row_count = len(channel_groups) + extra_electrical
    dark = request.theme == "dark"
    background = "#111827" if dark else "#FFFFFF"
    foreground = "#E5E7EB" if dark else "#17233F"
    grid = "#374151" if dark else "#D9E1EC"
    figure = Figure(
        figsize=(15 if request.orientation == "landscape" else 10, max(5, row_count * 4.2)),
        facecolor=background,
        constrained_layout=True,
    )
    FigureCanvasAgg(figure)
    axes = figure.subplots(row_count, 1, squeeze=False).flatten()
    figure.suptitle(request.title, color=foreground, fontsize=16, fontweight="bold")
    session_limit = max(200, 12_000 // max(1, len(data["sessions"])))
    visual_gap_seconds = 300.0 if request.interpolation == "visual_only" else 60.0
    line_styles = ["-", "--", ":", "-."]

    for group_index, group in enumerate(channel_groups):
        temperature_axis = axes[group_index] if group else None
        power_axis = temperature_axis.twinx() if temperature_axis is not None else axes[group_index]
        axes[group_index].set_facecolor(background)
        for session_index, session in enumerate(data["sessions"]):
            session_id = session["id"]
            if request.include_power:
                power_points = [
                    point
                    for point in data["electrical"]
                    if point["session_id"] == session_id and point["active_power_w"] is not None
                ]
                power_points = downsample_time_buckets(
                    power_points, ["active_power_w"], session_limit
                )
                for segment_index, segment in enumerate(
                    _segments(power_points, visual_gap_seconds)
                ):
                    power_axis.plot(
                        [point["timestamp"] for point in segment],
                        [point["active_power_w"] for point in segment],
                        color="#3B82F6",
                        linewidth=1.35,
                        alpha=0.9,
                        linestyle=line_styles[session_index % len(line_styles)],
                        label=f"Potência · {session['name']}" if segment_index == 0 else None,
                    )
            if temperature_axis is not None:
                temperature_points = [
                    point for point in data["temperatures"] if point["session_id"] == session_id
                ]
                flat = [
                    {
                        **point,
                        **{
                            f"channel_{channel}": point["channels"].get(channel)
                            for channel in group
                        },
                    }
                    for point in temperature_points
                ]
                flat = downsample_time_buckets(
                    flat, [f"channel_{channel}" for channel in group], session_limit
                )
                for channel in group:
                    key = f"channel_{channel}"
                    channel_points = [point for point in flat if point.get(key) is not None]
                    for segment_index, segment in enumerate(
                        _segments(channel_points, visual_gap_seconds)
                    ):
                        name = next(
                            (
                                point["channel_names"].get(channel)
                                for point in temperature_points
                                if point["channel_names"].get(channel)
                            ),
                            f"Termopar {channel}",
                        )
                        temperature_axis.plot(
                            [point["timestamp"] for point in segment],
                            [point[key] for point in segment],
                            color=CHANNEL_COLORS[(channel - 1) % len(CHANNEL_COLORS)],
                            linewidth=1.05,
                            linestyle=line_styles[session_index % len(line_styles)],
                            label=f"T{channel} · {name} · {session['name']}"
                            if segment_index == 0
                            else None,
                        )
        power_axis.set_ylabel("Potência ativa (W)", color="#3B82F6")
        power_axis.grid(True, color=grid, alpha=0.6, linewidth=0.55)
        power_axis.tick_params(colors=foreground, labelsize=8)
        power_axis.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m\n%H:%M"))
        for spine in power_axis.spines.values():
            spine.set_color(grid)
        if temperature_axis is not None:
            temperature_axis.set_ylabel("Temperatura (°C)", color="#D97706")
            temperature_axis.tick_params(colors=foreground, labelsize=8)
            handles, labels = temperature_axis.get_legend_handles_labels()
            power_handles, power_labels = power_axis.get_legend_handles_labels()
            if handles or power_handles:
                legend = power_axis.legend(
                    power_handles + handles,
                    power_labels + labels,
                    loc="upper left",
                    fontsize=7,
                    ncol=min(4, len(power_handles + handles)),
                )
                legend.get_frame().set_alpha(0.85)
        power_axis.set_title(
            f"Canais {group[0]}–{group[-1]}" if group else "Potência ativa",
            color=foreground,
            fontsize=10,
        )

    if request.include_electrical_details:
        axis = axes[-1]
        axis.set_facecolor(background)
        electrical_fields = [
            ("voltage_v", "Tensão (V)", "#7C3AED"),
            ("current_a", "Corrente (A)", "#16A34A"),
            ("power_factor", "Fator de potência", "#D97706"),
        ]
        for session_index, session in enumerate(data["sessions"]):
            points = [point for point in data["electrical"] if point["session_id"] == session["id"]]
            points = downsample_time_buckets(
                points, [field for field, _, _ in electrical_fields], session_limit
            )
            for field, label, color in electrical_fields:
                candidates = [point for point in points if point.get(field) is not None]
                for segment_index, segment in enumerate(_segments(candidates, visual_gap_seconds)):
                    axis.plot(
                        [point["timestamp"] for point in segment],
                        [point[field] for point in segment],
                        label=f"{label} · {session['name']}" if segment_index == 0 else None,
                        color=color,
                        linewidth=1.1,
                        linestyle=line_styles[session_index % len(line_styles)],
                    )
        axis.set_title("Grandezas elétricas complementares", color=foreground, fontsize=10)
        axis.grid(True, color=grid, alpha=0.6, linewidth=0.55)
        axis.tick_params(colors=foreground, labelsize=8)
        axis.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m\n%H:%M"))
        axis.legend(loc="upper left", fontsize=7, ncol=3)

    stream = io.BytesIO()
    format_name = "jpeg" if image_type in {"jpg", "jpeg"} else "png"
    figure.savefig(
        stream,
        format=format_name,
        dpi=request.dpi,
        facecolor=figure.get_facecolor(),
        bbox_inches="tight",
        pil_kwargs={"quality": 94} if format_name == "jpeg" else None,
    )
    figure.clear()
    return stream.getvalue()


def _format_number(value: Any, suffix: str = "", decimals: int = 2) -> str:
    if value is None:
        return "—"
    return (
        f"{float(value):,.{decimals}f}{suffix}".replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def _styled_table(rows: list[list[Any]], widths: list[float] | None = None) -> Table:
    table = Table(rows, repeatRows=1, colWidths=widths)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17233F")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F9FD")]),
                ("PADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def render_period_pdf(data: dict[str, Any], request: PeriodReportRequest) -> bytes:
    output = io.BytesIO()
    page_size = landscape(A4) if request.orientation == "landscape" else A4
    document = SimpleDocTemplate(
        output,
        pagesize=page_size,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=17 * mm,
        bottomMargin=16 * mm,
        title=request.title,
        author="ThermoPower Monitor",
        subject="Relatório técnico de medições por período",
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="CoverTitle",
            parent=styles["Title"],
            fontSize=25,
            leading=31,
            textColor=colors.HexColor("#17233F"),
            alignment=TA_CENTER,
            spaceAfter=8 * mm,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Section",
            parent=styles["Heading2"],
            fontSize=14,
            textColor=colors.HexColor("#234FCE"),
            spaceBefore=5 * mm,
            spaceAfter=3 * mm,
        )
    )
    zone = ZoneInfo(request.timezone)
    local_start = request.start.astimezone(zone)
    local_end = request.end.astimezone(zone)
    generated = datetime.now(UTC).astimezone(zone)
    story: list[Any] = [
        Spacer(1, 24 * mm),
        Paragraph("THERMOPOWER MONITOR", styles["Heading3"]),
        Paragraph(escape(request.title), styles["CoverTitle"]),
    ]
    if request.subtitle:
        story.append(Paragraph(escape(request.subtitle), styles["Heading2"]))
    story.extend(
        [
            Spacer(1, 8 * mm),
            Paragraph(
                f"Período: {local_start:%d/%m/%Y %H:%M:%S} a {local_end:%d/%m/%Y %H:%M:%S}",
                styles["Normal"],
            ),
            Paragraph(f"Fuso horário: {escape(request.timezone)}", styles["Normal"]),
            Paragraph(f"Gerado em: {generated:%d/%m/%Y %H:%M:%S}", styles["Normal"]),
            Spacer(1, 12 * mm),
            Paragraph(
                escape(
                    request.description or "Relatório consolidado de medições térmicas e elétricas."
                ),
                styles["BodyText"],
            ),
            PageBreak(),
            Paragraph("Resumo executivo", styles["Section"]),
        ]
    )
    general = data["statistics"]["general"]
    electrical = data["statistics"]["electrical"]
    summary = [
        ["Indicador", "Valor", "Indicador", "Valor"],
        [
            "Sessões",
            general["session_count"],
            "Alertas",
            general["alert_count"],
        ],
        [
            "Amostras elétricas",
            general["electrical_sample_count"],
            "Amostras de temperatura",
            general["temperature_sample_count"],
        ],
        [
            "Potência média",
            _format_number(electrical["active_power_w"]["mean"], " W"),
            "Energia integrada",
            _format_number(electrical["energy_wh"], " Wh", 3),
        ],
        [
            "Lacunas",
            general["gap_count"],
            "Fallbacks de timestamp",
            general["timestamp_fallback_count"],
        ],
    ]
    story.extend([_styled_table(summary), Spacer(1, 4 * mm)])
    if request.notes:
        story.extend(
            [
                Paragraph("Notas", styles["Heading3"]),
                Paragraph(escape(request.notes), styles["BodyText"]),
            ]
        )
    chart = render_period_chart(data, request, "png")
    story.extend(
        [
            Paragraph("Séries temporais", styles["Section"]),
            Paragraph(
                "As linhas são interrompidas em lacunas e nas fronteiras de sessão. "
                "A redução de pontos afeta somente esta visualização.",
                styles["BodyText"],
            ),
            Image(io.BytesIO(chart), width=document.width, height=document.width * 0.48),
            PageBreak(),
        ]
    )
    if request.include_power or request.include_electrical_details:
        story.append(Paragraph("Estatísticas elétricas", styles["Section"]))
    electric_rows = [["Grandeza", "Amostras", "Mínimo", "Média", "Mediana", "Máximo", "P95"]]
    electrical_labels = {
        "active_power_w": ("Potência ativa (W)", ""),
        "voltage_v": ("Tensão (V)", ""),
        "current_a": ("Corrente (A)", ""),
        "apparent_power_va": ("Potência aparente (VA)", ""),
        "reactive_power_var": ("Potência reativa (var)", ""),
        "power_factor": ("Fator de potência", ""),
        "voltage_frequency_hz": ("Frequência de tensão (Hz)", ""),
        "current_frequency_hz": ("Frequência de corrente (Hz)", ""),
    }
    for key, (label, suffix) in electrical_labels.items():
        stats = electrical[key]
        electric_rows.append(
            [
                label,
                stats["count"],
                _format_number(stats["min"], suffix),
                _format_number(stats["mean"], suffix),
                _format_number(stats["median"], suffix),
                _format_number(stats["max"], suffix),
                _format_number(stats["p95"], suffix),
            ]
        )
    if request.include_power or request.include_electrical_details:
        story.extend(
            [
                _styled_table(electric_rows),
                Paragraph(
                    "Energia por integração trapezoidal: "
                    f"<b>{_format_number(electrical['energy_wh'], ' Wh', 3)}</b>. "
                    f"Intervalos excluídos por lacuna: "
                    f"{electrical['excluded_energy_intervals']} "
                    f"(limite {electrical['energy_gap_limit_seconds']:.0f} s).",
                    styles["BodyText"],
                ),
            ]
        )
    if request.include_temperatures:
        story.append(Paragraph("Estatísticas dos termopares", styles["Section"]))
    channel_rows = [
        ["Canal", "Nome(s)", "Amostras", "Disponibilidade", "Mínimo", "Média", "Máximo"]
    ]
    for stats in data["statistics"]["channels"]:
        channel_rows.append(
            [
                f"T{stats['channel']}",
                ", ".join(stats["names"]),
                stats["count"],
                _format_number(stats["availability_percent"], "%"),
                _format_number(stats["min"], " °C"),
                _format_number(stats["mean"], " °C"),
                _format_number(stats["max"], " °C"),
            ]
        )
    if request.include_temperatures:
        story.append(_styled_table(channel_rows))

    if request.include_session_list:
        story.extend([PageBreak(), Paragraph("Sessões incluídas", styles["Section"])])
        session_rows = [
            ["ID", "Sessão", "Início", "Fim", "Equipamentos", "Operador", "Amostras E/T"]
        ]
        for session in data["sessions"]:
            session_rows.append(
                [
                    session["id"],
                    session["name"],
                    session["started_at"].replace("T", " ")[:19],
                    (session["ended_at"] or "Em andamento").replace("T", " ")[:19],
                    ", ".join(device["name"] for device in session["devices"]),
                    session["operator"] or "—",
                    f"{session['electrical_samples']} / {session['temperature_samples']}",
                ]
            )
        story.append(_styled_table(session_rows))

    if request.include_alerts:
        story.extend([Paragraph("Alertas", styles["Section"])])
        alert_rows = [["Horário", "Sessão", "Severidade", "Métrica", "Canal", "Valor", "Limite"]]
        alert_rows.extend(
            [
                alert["timestamp"].replace("T", " ")[:19],
                alert["session_id"],
                alert["severity"],
                alert["metric"],
                f"T{alert['channel']}" if alert["channel"] else "—",
                _format_number(alert["measured_value"]),
                _format_number(alert["threshold"]),
            ]
            for alert in data["alerts"][:200]
        )
        if len(alert_rows) == 1:
            alert_rows.append(["—", "—", "Nenhum alerta", "—", "—", "—", "—"])
        story.append(_styled_table(alert_rows))

    if request.include_quality:
        story.extend(
            [
                Paragraph("Qualidade e rastreabilidade", styles["Section"]),
                Paragraph(
                    f"Qualidades registradas: {escape(str(general['quality_counts']))}. "
                    f"Lacunas detectadas: {general['gap_count']}; duração acumulada: "
                    f"{_format_number(general['gap_seconds'], ' s')}. "
                    "Cada sessão foi processada como segmento independente; "
                    "nenhum valor zero foi criado.",
                    styles["BodyText"],
                ),
            ]
        )

    if request.include_table and data["table_rows"]:
        story.extend(
            [PageBreak(), Paragraph("Amostra tabular sincronizada por sessão", styles["Section"])]
        )
        table_rows = [
            ["Sessão", "Timestamp", "Potência (W)", "Tensão (V)", "Corrente (A)", "Temperaturas"]
        ]
        for row in data["table_rows"]:
            temperatures = ", ".join(
                f"T{channel}={_format_number(value, ' °C')}"
                for channel, value in sorted(row["channels"].items())
                if value is not None
            )
            table_rows.append(
                [
                    row["session_id"],
                    row["timestamp"].replace("T", " ")[:23],
                    _format_number(row["active_power_w"]),
                    _format_number(row["voltage_v"]),
                    _format_number(row["current_a"]),
                    temperatures or "—",
                ]
            )
        story.append(_styled_table(table_rows))

    def footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#CBD5E1"))
        canvas.line(doc.leftMargin, 11 * mm, page_size[0] - doc.rightMargin, 11 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(doc.leftMargin, 7 * mm, "ThermoPower Monitor · Relatório por período")
        canvas.drawRightString(page_size[0] - doc.rightMargin, 7 * mm, f"Página {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
