import {
  AlertTriangle, ArrowLeft, CheckCircle2, Download, FileImage, FileSpreadsheet,
  FileText, Save, Sparkles,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Brush, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api, downloadWithBody, formatDate, formatDuration } from "../api";
import { Badge, Empty, ErrorNotice, Metric, PageHeader, Panel, Spinner } from "../components/ui";

const colors = [
  "#2563EB", "#16A34A", "#D97706", "#DC2626", "#7C3AED", "#0891B2", "#DB2777", "#4F46E5",
  "#65A30D", "#EA580C", "#0D9488", "#9333EA", "#E11D48", "#0284C7", "#CA8A04", "#475569",
];
const metadataFields = [
  ["product", "Produto"], ["model", "Modelo"], ["sample", "Amostra"], ["code", "Código"],
  ["nominal_voltage", "Tensão nominal"], ["setpoint", "Setpoint"],
  ["responsible", "Responsável"], ["location", "Laboratório / local"], ["project", "Projeto"],
] as const;

function saoPauloInput(value?: string | null): string {
  if (!value) return "";
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: "America/Sao_Paulo", year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hourCycle: "h23",
    }).formatToParts(new Date(value)).map((part) => [part.type, part.value]),
  );
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

function mergedSeries(preview: any): Array<Record<string, any>> {
  const values = new Map<string, Record<string, any>>();
  const stream = preview?.series?.[0];
  for (const point of [...(stream?.electrical ?? []), ...(stream?.temperatures ?? [])]) {
    values.set(point.timestamp, { ...(values.get(point.timestamp) ?? {}), ...point });
  }
  return [...values.values()].sort((left, right) => left.timestamp.localeCompare(right.timestamp));
}

function number(value: number | null | undefined, unit = "", decimals = 1): string {
  return value == null ? "—" : `${value.toLocaleString("pt-BR", {
    maximumFractionDigits: decimals, minimumFractionDigits: decimals,
  })}${unit}`;
}

export default function SessionDetailPage() {
  const { id } = useParams();
  const [session, setSession] = useState<any>(null);
  const [analysis, setAnalysis] = useState<any>(null);
  const [alerts, setAlerts] = useState<any[]>([]);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [elapsedTime, setElapsedTime] = useState(false);
  const [showOpen, setShowOpen] = useState(false);
  const [metadata, setMetadata] = useState<Record<string, string>>({});
  const [channelNames, setChannelNames] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [saved, setSaved] = useState(false);

  function reportPayload(detail = session, periodStart = start, periodEnd = end) {
    return {
      start: periodStart, end: periodEnd, timezone: "America/Sao_Paulo",
      title: detail?.name ?? "Ensaio ThermoPower",
      subtitle: "Relatório Técnico de Ensaio Térmico e Elétrico",
      description: detail?.description || null, notes: detail?.notes || null,
      session_ids: [Number(id)], channels: null, include_open_channels: showOpen,
      include_power: true, include_temperatures: true, include_electrical_details: true,
      include_alerts: true, include_quality: true, include_session_list: true, include_table: true,
      orientation: "landscape", theme: "light", dpi: 180, table_max_rows: 250,
      channel_group_size: 8, sync_tolerance_ms: detail?.sync_tolerance_ms ?? 1500,
      use_device_timestamp: true, interpolation: "none",
    };
  }

  async function loadAnalysis(detail: any, periodStart: string, periodEnd: string) {
    setBusy("Calculando indicadores do período…");
    try {
      setAnalysis(await api<any>("/reports/period/preview", {
        method: "POST", body: JSON.stringify(reportPayload(detail, periodStart, periodEnd)),
      }));
    } finally {
      setBusy("");
    }
  }

  useEffect(() => {
    Promise.all([api<any>(`/sessions/${id}`), api<any>("/alerts?page_size=100")])
      .then(([detail, allAlerts]) => {
        const analysisStart = saoPauloInput(detail.started_at);
        const analysisEnd = saoPauloInput(detail.ended_at ?? new Date().toISOString());
        setSession(detail); setStart(analysisStart); setEnd(analysisEnd);
        setMetadata(detail.metadata ?? {});
        setChannelNames(Object.fromEntries(
          (detail.channels ?? []).map((item: any) => [item.channel, item.name]),
        ));
        setAlerts(allAlerts.items.filter((alert: any) => alert.session_id === Number(id)));
        return loadAnalysis(detail, analysisStart, analysisEnd);
      }).catch((reason) => setError(reason.message));
  }, [id]);

  const series = useMemo(() => mergedSeries(analysis), [analysis]);
  const firstTimestamp = series[0]?.timestamp ? new Date(series[0].timestamp).getTime() : 0;
  const channels: number[] = analysis?.selected_channels ?? [];
  const statistics = analysis?.statistics;
  const general = statistics?.general ?? {};
  const electrical = statistics?.electrical ?? {};
  const temperature = statistics?.temperature ?? {};
  const stabilization = temperature.stabilization ?? {};
  const operator = session?.operator?.name?.toLocaleLowerCase("pt-BR").includes("demo")
    ? "Operador não informado" : session?.operator?.name ?? "Operador não informado";

  async function refreshAnalysis() {
    if (!start || !end || start >= end) {
      setError("O fim do período analisado deve ser posterior ao início."); return;
    }
    setError("");
    try { await loadAnalysis(session, start, end); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Falha ao analisar o período"); }
  }

  async function exportFile(
    kind: "pdf" | "xlsx" | "png" | "csv" | "executive.png" | "executive.pdf",
  ) {
    setBusy("Preparando arquivo profissional…"); setError("");
    try {
      const endpoint = kind === "png" ? "/reports/period/chart.png" : `/reports/period/${kind}`;
      const extension = kind.split(".").at(-1) ?? kind;
      await downloadWithBody(endpoint, `sessao-${id}.${extension}`, reportPayload());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao gerar o arquivo");
    } finally { setBusy(""); }
  }

  async function saveIdentification() {
    setBusy("Salvando identificação do ensaio…"); setSaved(false);
    try {
      await api(`/sessions/${id}`, {
        method: "PATCH", body: JSON.stringify({ metadata, channel_names: channelNames }),
      });
      setSaved(true); setSession((current: any) => ({ ...current, metadata }));
      await refreshAnalysis();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao salvar identificação");
    } finally { setBusy(""); }
  }

  function updateFromBrush(range: { startIndex?: number; endIndex?: number }) {
    if (range.startIndex == null || range.endIndex == null || !series.length) return;
    setStart(saoPauloInput(series[range.startIndex]?.timestamp));
    setEnd(saoPauloInput(series[range.endIndex]?.timestamp));
  }

  if (error && !session) return <ErrorNotice message={error} />;
  if (!session) return <Spinner label="Carregando análise da sessão" />;

  return <>
    <Link to="/sessoes" className="back-link"><ArrowLeft /> Voltar para sessões</Link>
    <PageHeader eyebrow="VISÃO EXECUTIVA DO ENSAIO" title={session.name}
      description={`${operator} · ${session.devices?.map((item: any) => item.device.name).join(" + ") || session.device.name}`}
      actions={<>
        <button className="button ghost" onClick={() => void exportFile("csv")}><Download /> CSV</button>
        <button className="button secondary" onClick={() => void exportFile("xlsx")}><FileSpreadsheet /> XLSX técnico</button>
        <button className="button secondary" onClick={() => void exportFile("executive.png")}><FileImage /> Resumo executivo</button>
        <button className="button primary" onClick={() => void exportFile("pdf")}><FileText /> Relatório PDF</button>
      </>} />
    {error && <ErrorNotice message={error} />}
    {busy && <Spinner label={busy} />}

    <div className="detail-strip">
      <div><span>STATUS</span><Badge tone={session.status === "finished" ? "success" : "warning"}>{session.status === "finished" ? "Finalizada" : session.status}</Badge></div>
      <div><span>SESSÃO COMPLETA</span><strong>{formatDate(session.started_at)} → {formatDate(session.ended_at)}</strong></div>
      <div><span>DURAÇÃO TOTAL</span><strong>{formatDuration(general.full_session_duration_seconds ?? session.statistics.duration_seconds)}</strong></div>
      <div><span>PERÍODO ANALISADO</span><strong>{formatDuration(general.analyzed_period_seconds)}</strong></div>
    </div>

    <Panel title="Período de análise" kicker="KPIs RECALCULADOS PARA A JANELA" className="analysis-window-panel">
      <div className="analysis-window-controls">
        <label className="field"><span>Início</span><input type="datetime-local" value={start} onChange={(event) => setStart(event.target.value)} /></label>
        <span className="analysis-arrow">→</span>
        <label className="field"><span>Fim</span><input type="datetime-local" value={end} onChange={(event) => setEnd(event.target.value)} /></label>
        <button className="button primary" onClick={() => void refreshAnalysis()}>Aplicar período</button>
        {stabilization.suggested && <button className="button ghost" onClick={() => setStart(saoPauloInput(stabilization.start))}><Sparkles /> Usar sugestão estabilizada</button>}
      </div>
      {stabilization.suggested && <p className="stability-note"><Sparkles /> Estabilização sugerida a partir de {formatDate(stabilization.start)} — confirme ou ajuste manualmente. Critério: inclinação ≤ 0,2 °C/min e amplitude ≤ 1,0 °C em janela de 3 min.</p>}
    </Panel>

    <div className="metrics-grid six executive-kpis">
      <Metric label="Potência média" value={number(electrical.active_power_w?.mean, " W", 2)} hint={`P95 ${number(electrical.active_power_w?.p95, " W", 2)}`} tone="primary" />
      <Metric label="Potência máxima" value={number(electrical.active_power_w?.max, " W", 2)} hint={`Mín ${number(electrical.active_power_w?.min, " W", 2)}`} />
      <Metric label="Energia" value={number(electrical.energy_wh, " Wh", 3)} hint="Integração por timestamps reais" />
      <Metric label="Temperatura máxima" value={number(temperature.max, " °C", 2)} hint={temperature.critical_channel_label ?? "Sem leitura"} tone="warm" />
      <Metric label="ΔT máximo" value={number(temperature.maximum_delta_t?.value_c, " °C", 2)} hint={temperature.maximum_delta_t ? `T${temperature.maximum_delta_t.cold_channel} ↔ T${temperature.maximum_delta_t.hot_channel}` : "Sem pares térmicos"} />
      <Metric label="Integridade" value={general.gap_count ? `${general.gap_count} lacuna(s)` : "Íntegra"} hint={`${general.electrical_sample_count ?? 0} elétricas · ${general.temperature_sample_count ?? 0} térmicas`} tone={general.gap_count ? "danger" : "default"} />
    </div>

    <Panel title="Temperatura + potência" kicker="TEMPO REAL · DOIS EIXOS INDEPENDENTES" actions={<div className="chart-actions"><label><input type="checkbox" checked={elapsedTime} onChange={(event) => setElapsedTime(event.target.checked)} /> Tempo decorrido</label><label><input type="checkbox" checked={showOpen} onChange={(event) => setShowOpen(event.target.checked)} /> Mostrar canais Open</label><button className="button small ghost" onClick={() => void exportFile("png")}><FileImage /> Exportar gráfico</button></div>}>
      {!series.length ? <Empty title="Sem dados no período" /> : <div className="chart-container tall executive-chart"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={series}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="timestamp" minTickGap={35} tickFormatter={(value) => elapsedTime ? formatDuration((new Date(value).getTime() - firstTimestamp) / 1000) : new Date(value).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", timeZone: "America/Sao_Paulo" })} /><YAxis yAxisId="temperature" unit=" °C" width={64} domain={["auto", "auto"]} /><YAxis yAxisId="power" orientation="right" unit=" W" width={64} domain={["auto", "auto"]} /><Tooltip labelFormatter={(value) => formatDate(String(value))} /><Legend verticalAlign="top" height={58} /><Line yAxisId="power" type="linear" dataKey="active_power_w" name="Potência ativa" stroke="#2563EB" strokeWidth={2.7} dot={false} connectNulls={false} isAnimationActive={false} />{channels.map((channel) => <Line key={channel} yAxisId="temperature" type="linear" dataKey={`channel_${channel}`} name={analysis.channel_labels?.[String(channel)] ?? `T${channel}`} stroke={colors[(channel - 1) % colors.length]} dot={false} connectNulls={false} isAnimationActive={false} />)}<Brush dataKey="timestamp" height={28} tickFormatter={(value) => new Date(value).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", timeZone: "America/Sao_Paulo" })} onChange={updateFromBrush} /></ComposedChart></ResponsiveContainer></div>}
      <p className="hint">Arraste os controles inferiores para marcar uma janela; clique em “Aplicar período” para recalcular indicadores e exports.</p>
    </Panel>

    <div className="charts-grid">
      <Panel title="Fontes do ensaio" kicker="RASTREABILIDADE"><div className="instrument-list">{session.devices?.map((item: any) => <div key={`${item.role}-${item.device.id}`}><span>{item.role === "electrical" ? "Fonte elétrica" : item.role === "temperature" ? "Fonte térmica" : "Fonte combinada"}</span><strong>{[item.device.manufacturer, item.device.model].filter(Boolean).join(" ") || item.device.name}</strong><small>{[item.device.serial_number, item.device.port, item.device.baud_rate ? `${item.device.baud_rate} baud` : null].filter(Boolean).join(" · ") || "Identificação de conexão não informada"}</small></div>)}</div></Panel>
      <Panel title="Destaques térmicos" kicker="PERÍODO ANALISADO"><div className="insight-list"><div><span>Canal crítico</span><strong>{temperature.critical_channel_label ?? "—"}</strong></div><div><span>Máxima registrada</span><strong>{number(temperature.critical_value_c, " °C", 2)}</strong></div><div><span>Horário da máxima</span><strong>{formatDate(temperature.critical_timestamp)}</strong></div><div><span>Maior taxa de aquecimento</span><strong>{temperature.greatest_heating_rate ? `T${temperature.greatest_heating_rate.channel} · ${number(temperature.greatest_heating_rate.value_c_per_minute, " °C/min", 2)}` : "—"}</strong></div></div></Panel>
    </div>

    <Panel title="Resumo por ponteira" kicker="SOMENTE CANAIS COM LEITURA" actions={<button className="button small ghost" onClick={() => setShowOpen(!showOpen)}>{showOpen ? "Ocultar Open" : "Mostrar canais Open"}</button>}>
      <div className="table-scroll"><table><thead><tr><th>Canal</th><th>Identificação</th><th>Amostras</th><th>Média</th><th>Máx</th><th>Mín</th><th>ΔT</th><th>Desvio</th><th>P95</th></tr></thead><tbody>{(statistics?.channels ?? []).filter((item: any) => showOpen || item.count).map((item: any) => <tr key={item.channel}><td><strong style={{ color: colors[(item.channel - 1) % colors.length] }}>T{item.channel}</strong></td><td>{item.friendly_name || "—"}</td><td>{item.count}</td><td>{number(item.mean, " °C", 2)}</td><td>{number(item.max, " °C", 2)}</td><td>{number(item.min, " °C", 2)}</td><td>{number(item.range, " °C", 2)}</td><td>{number(item.standard_deviation, " °C", 2)}</td><td>{number(item.p95, " °C", 2)}</td></tr>)}</tbody></table></div>
    </Panel>

    <Panel title="Identificação do ensaio" kicker="CAMPOS OPCIONAIS PARA DOCUMENTOS">
      <div className="form-grid session-metadata-grid">{metadataFields.map(([key, label]) => <label className="field" key={key}><span>{label}</span><input value={metadata[key] ?? ""} onChange={(event) => setMetadata((current) => ({ ...current, [key]: event.target.value }))} /></label>)}</div>
      <label className="field"><span>Observações</span><textarea value={metadata.observations ?? ""} onChange={(event) => setMetadata((current) => ({ ...current, observations: event.target.value }))} /></label>
      <h3 className="subsection-title">Nomes amigáveis das ponteiras</h3>
      <div className="probe-name-grid">{(session.channels ?? []).filter((item: any) => channels.includes(item.channel)).map((item: any) => <label className="field" key={item.channel}><span>T{item.channel}</span><input value={channelNames[item.channel] ?? ""} placeholder={`T${item.channel}`} onChange={(event) => setChannelNames((current) => ({ ...current, [item.channel]: event.target.value }))} /></label>)}</div>
      <div className="report-buttons"><button className="button primary" onClick={() => void saveIdentification()}><Save /> Salvar identificação</button>{saved && <span className="saved-state"><CheckCircle2 /> Informações salvas</span>}</div>
    </Panel>

    <Panel title="Downloads complementares" kicker="APRESENTAÇÃO E ENGENHARIA"><div className="report-buttons"><button className="button secondary" onClick={() => void exportFile("executive.pdf")}><FileText /> Resumo de 1 página</button><button className="button ghost" onClick={() => void exportFile("png")}><FileImage /> Gráfico PNG</button><button className="button ghost" onClick={() => void exportFile("csv")}><Download /> Dados sincronizados CSV</button></div></Panel>
    <Panel title="Alertas da sessão" kicker="QUALIDADE"><div className="alert-list">{alerts.length ? alerts.map((alert) => <div key={alert.id}><AlertTriangle /><div><strong>{alert.metric === "power" ? "Potência" : `Termopar T${alert.channel}`}</strong><span>{number(alert.measured_value, "")} · limite {alert.threshold}</span></div><Badge tone={alert.severity === "critical" ? "danger" : "warning"}>{alert.severity}</Badge><time>{formatDate(alert.timestamp)}</time></div>) : <Empty title="Nenhum alerta nesta sessão" />}</div></Panel>
  </>;
}
