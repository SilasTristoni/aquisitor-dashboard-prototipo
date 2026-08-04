import { AlertTriangle, ArrowLeft, Download, FileImage, FileSpreadsheet, FileText } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Brush, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, download, formatDate, formatDuration } from "../api";
import { Badge, Empty, ErrorNotice, Metric, PageHeader, Panel, Spinner } from "../components/ui";

const colors = ["#f59e0b", "#ef4444", "#10b981", "#8b5cf6", "#06b6d4", "#ec4899", "#84cc16", "#f97316"];

export default function SessionDetailPage() {
  const { id } = useParams();
  const [session, setSession] = useState<any>(null);
  const [chart, setChart] = useState<any>({ points: [], metrics: {} });
  const [alerts, setAlerts] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [gridMs, setGridMs] = useState(1000);
  const [toleranceMs, setToleranceMs] = useState(1500);
  const [powerMetric, setPowerMetric] = useState("active_power_w");
  useEffect(() => {
    Promise.all([
      api<any>(`/sessions/${id}`),
      api<any>(`/sessions/${id}/synchronized-series?grid_ms=${gridMs}&tolerance_ms=${toleranceMs}&max_points=2000`),
      api<any>("/alerts?page_size=100"),
    ]).then(([detail, synchronized, allAlerts]) => {
      setSession(detail); setChart(synchronized);
      setAlerts(allAlerts.items.filter((alert: any) => alert.session_id === Number(id)));
    }).catch((reason) => setError(reason.message));
  }, [id, gridMs, toleranceMs]);
  const series = useMemo(() => chart.points.map((point: any) => ({
    ...point,
    time: new Date(point.timestamp).toLocaleTimeString("pt-BR"),
    ...Object.fromEntries(Object.entries(point.temperatures_c ?? {}).map(([channel, value]) => [`t${channel}`, value])),
  })), [chart]);
  const channels = useMemo<number[]>(() => {
    const detected: number[] = chart.points.flatMap((point: any) =>
      Object.keys(point.temperatures_c ?? {}).map(Number),
    );
    return Array.from(new Set<number>(detected)).sort((a, b) => a - b).slice(0, 8);
  }, [chart]);
  if (error) return <ErrorNotice message={error} />;
  if (!session) return <Spinner label="Carregando análise da sessão" />;
  const stats = session.statistics;
  const power = stats.power ?? { count: 0 };
  const sync = chart.metrics ?? {};
  return <>
    <Link to="/sessoes" className="back-link"><ArrowLeft /> Voltar para sessões</Link>
    <PageHeader eyebrow="ANÁLISE INTEGRADA" title={session.name} description={`${session.devices?.map((item: any) => `${item.role}: ${item.device.name}`).join(" · ") || session.device.name} · ${session.operator.name}`} actions={<><button className="button ghost" onClick={() => download(`/reports/sessions/${id}.csv`, `sessao-${id}.csv`)}><Download /> CSV</button><button className="button secondary" onClick={() => download(`/reports/sessions/${id}.xlsx`, `sessao-${id}.xlsx`)}><FileSpreadsheet /> XLSX</button><button className="button secondary" onClick={() => download(`/reports/sessions/${id}.png`, `sessao-${id}.png`)}><FileImage /> PNG</button><button className="button primary" onClick={() => download(`/reports/sessions/${id}.pdf`, `sessao-${id}.pdf`)}><FileText /> PDF</button></>} />
    <div className="detail-strip"><div><span>STATUS</span><Badge tone={session.status === "finished" ? "success" : "warning"}>{session.status}</Badge></div><div><span>PERÍODO</span><strong>{formatDate(session.started_at)} → {formatDate(session.ended_at)}</strong></div><div><span>DURAÇÃO</span><strong>{formatDuration(stats.duration_seconds)}</strong></div><div><span>SINCRONIZAÇÃO</span><strong>{sync.matched_points ?? 0} pares · {((sync.match_rate ?? 0) * 100).toFixed(1)}%</strong></div></div>
    <div className="metrics-grid six"><Metric label="Amostras elétricas" value={chart.source_counts?.electrical ?? power.count ?? 0} hint="GPM-8213" /><Metric label="Amostras térmicas" value={chart.source_counts?.temperature ?? 0} hint="AT4532" /><Metric label="Potência média" value={`${(power.mean ?? 0).toFixed(1)} W`} hint={`Máx ${(power.max ?? 0).toFixed(1)} W`} tone="primary"/><Metric label="Canal mais quente" value={stats.hottest_channel ? `T${stats.hottest_channel}` : "—"} hint="Maior temperatura" tone="warm"/><Metric label="Desvio médio" value={sync.average_pair_offset_ms == null ? "—" : `${sync.average_pair_offset_ms.toFixed(0)} ms`} hint={`Máx ${sync.maximum_pair_offset_ms?.toFixed(0) ?? "—"} ms`} /><Metric label="Sem par" value={(sync.temperature_only_points ?? 0) + (sync.electrical_only_points ?? 0)} hint="Dentro da grade" /></div>
    <Panel title="Temperatura e grandezas elétricas" kicker="DOIS EIXOS · VIZINHO TEMPORAL MAIS PRÓXIMO" actions={<div className="chart-actions"><label>Elétrica <select value={powerMetric} onChange={(event) => setPowerMetric(event.target.value)}><option value="active_power_w">Potência ativa (W)</option><option value="apparent_power_va">Potência aparente (VA)</option><option value="reactive_power_var">Potência reativa (var)</option><option value="voltage_v">Tensão (V)</option><option value="current_a">Corrente (A)</option><option value="power_factor">Fator de potência</option></select></label><label>Grade <select value={gridMs} onChange={(event) => setGridMs(Number(event.target.value))}><option value="500">500 ms</option><option value="1000">1 s</option><option value="2000">2 s</option></select></label><label>Tolerância <select value={toleranceMs} onChange={(event) => setToleranceMs(Number(event.target.value))}><option value="500">500 ms</option><option value="1500">1,5 s</option><option value="3000">3 s</option></select></label></div>}>
      {!series.length ? <Empty title="Sem dados sincronizáveis" text="Importe ou adquira ao menos uma fonte para visualizar a série." /> : <div className="chart-container tall"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={series}><CartesianGrid strokeDasharray="3 3" vertical={false}/><XAxis dataKey="time" minTickGap={35}/><YAxis yAxisId="temperature" unit=" °C" domain={["auto", "auto"]}/><YAxis yAxisId="electrical" orientation="right" domain={["auto", "auto"]}/><Tooltip/><Legend/>{channels.map((channel, index) => <Line key={channel} yAxisId="temperature" type="monotone" dataKey={`t${channel}`} name={`T${channel} (°C)`} stroke={colors[index % colors.length]} dot={false} connectNulls={false}/>) }<Line yAxisId="electrical" type="monotone" dataKey={powerMetric} name={powerMetric.replaceAll("_", " ")} stroke="#3569ed" strokeWidth={2.5} dot={false} connectNulls={false}/><Brush dataKey="time" height={25}/></ComposedChart></ResponsiveContainer></div>}
    </Panel>
    <div className="charts-grid"><Panel title="Qualidade do pareamento" kicker="MÉTRICAS"><div className="insight-list"><div><span>Pares válidos</span><strong>{sync.matched_points ?? 0}</strong></div><div><span>Somente temperatura</span><strong>{sync.temperature_only_points ?? 0}</strong></div><div><span>Somente elétrica</span><strong>{sync.electrical_only_points ?? 0}</strong></div><div><span>Grade efetiva</span><strong>{chart.effective_grid_ms ?? gridMs} ms</strong></div></div></Panel><Panel title="Estatísticas por termopar" kicker="ATÉ 32 CANAIS"><div className="channel-stat-grid">{Object.entries(stats.temperatures ?? {}).slice(0, 32).map(([channel, value]: any) => <div key={channel}><span>T{channel}</span><strong>{value.mean.toFixed(1)} °C</strong><small>Mín {value.min.toFixed(1)} · Máx {value.max.toFixed(1)}</small></div>)}</div></Panel></div>
    <Panel title="Alertas da sessão" kicker="VIOLAÇÕES"><div className="alert-list">{alerts.length ? alerts.map((alert) => <div key={alert.id}><AlertTriangle /><div><strong>{alert.metric === "power" ? "Potência" : `Termopar T${alert.channel}`}</strong><span>{alert.measured_value.toFixed(2)} · limite {alert.threshold}</span></div><Badge tone={alert.severity === "critical" ? "danger" : "warning"}>{alert.severity}</Badge><time>{formatDate(alert.timestamp)}</time></div>) : <Empty title="Nenhum alerta nesta sessão" />}</div></Panel>
  </>;
}
