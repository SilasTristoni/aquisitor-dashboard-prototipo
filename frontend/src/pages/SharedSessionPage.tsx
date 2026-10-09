import { Activity, Moon, Sun } from "lucide-react";
import { EventMarkerLabel, groupChartEvents, ResultEvents } from "../components/ResultEvents";
import { SeriesControls } from "../components/SeriesControls";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { API_BASE, formatDate, formatDuration } from "../api";
import { Metric, Panel, Spinner } from "../components/ui";
import { CHANNEL_COLORS, POWER_COLOR, formatTimeAxis, mergeIndependentSeries } from "../utils/chartPresentation";

export default function SharedSessionPage() {
  const [dark, setDark] = useState(() => localStorage.getItem("thermopower.theme") === "dark");
  const [hidden, setHidden] = useState<string[]>([]);
  useEffect(() => { document.documentElement.dataset.theme = dark ? "dark" : "light"; }, [dark]);
  const [token] = useState(() => window.location.hash.slice(1));
  const [password, setPassword] = useState("");
  const [credential, setCredential] = useState("");
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");
  const [needsPassword, setNeedsPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  async function request(path: string, secret: string) {
    const response = await fetch(`${API_BASE}/public/shares/${path}`, { method: "POST", credentials: "omit", cache: "no-store", referrerPolicy: "no-referrer", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token, password: secret || null }) });
    if (!response.ok) {
      if (response.status === 401) setNeedsPassword(true);
      const body = await response.json().catch(() => null);
      throw new Error(body?.error?.message ?? "Compartilhamento indisponível");
    }
    return response;
  }
  async function load(secret: string) {
    setBusy(true); setError("");
    try { const response = await request("access", secret); setResult(await response.json()); setCredential(secret); setPassword(""); setNeedsPassword(false); }
    catch (reason) { setResult(null); setError((reason as Error).message); } finally { setBusy(false); }
  }
  useEffect(() => { if (token) void load(""); else setError("Link de compartilhamento inválido"); }, [token]);
  const rows = useMemo(() => mergeIndependentSeries(result?.series?.[0]?.electrical ?? [], result?.series?.[0]?.temperatures ?? [], "real"), [result]);
  async function download(kind: string) {
    setBusy(true); setError("");
    try { const response = await request(`download/${kind}`, credential); const url = URL.createObjectURL(await response.blob()); const anchor = document.createElement("a"); anchor.href = url; anchor.download = `resultado.${kind}`; anchor.click(); URL.revokeObjectURL(url); }
    catch (reason) { setError((reason as Error).message); } finally { setBusy(false); }
  }
  const metric = (value: number | null | undefined, unit: string) => value == null ? "—" : `${value.toLocaleString("pt-BR", { maximumFractionDigits: 2 })} ${unit}`;
  const eventGroups = groupChartEvents(result?.annotations ?? [], (value) => new Date(value).getTime(), Math.max(1, Number(rows.at(-1)?.axisValue) - Number(rows[0]?.axisValue)));
  const chartSeries = [{ key: "active_power_w", label: "Potência", color: POWER_COLOR }, ...(result?.selected_channels ?? []).map((channel: number) => ({ key: `channel_${channel}`, label: result.channel_labels[String(channel)], color: CHANNEL_COLORS[(channel - 1) % CHANNEL_COLORS.length] }))];
  const downloads = ["pdf", "xlsx", "csv"].filter((kind) => result?.permissions[kind]);
  return <main className="page shared-result">
    <div className="public-brand"><span className="brand-mark"><Activity /></span><div><strong>ThermoPower</strong><span>Resultado compartilhado</span></div><button className="icon-button" aria-label="Alternar tema" onClick={() => setDark(!dark)}>{dark ? <Sun /> : <Moon />}</button></div>
    <header className="page-header"><div><h1>{result?.name ?? "Resultado do ensaio"}</h1><p className="subtitle">Consulta do resultado · Somente leitura</p></div></header>
    {busy && <Spinner label="Carregando resultado" />}{error && <p role="alert" className="notice warning">{error}</p>}
    {!result && needsPassword && <Panel title="Acesso protegido" className="access-card"><p className="hint">Informe a senha fornecida por quem compartilhou o ensaio.</p><form className="compact-form" onSubmit={(event: FormEvent) => { event.preventDefault(); void load(password); }}><label className="field"><span>Senha do compartilhamento</span><input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required maxLength={72} /></label><div className="action-bar"><button className="button primary" disabled={busy}>Abrir resultado</button></div></form></Panel>}
    {result && <><Panel title="Identificação do ensaio"><dl className="metadata-grid">{Object.entries(result.metadata).map(([key, value]) => <div key={key}><dt>{{ product: "Produto", model: "Modelo", sample: "Amostra", code: "Código", nominal_voltage: "Tensão nominal", setpoint: "Setpoint" }[key]}</dt><dd>{String(value || "—")}</dd></div>)}</dl><p className="applied-period"><strong>{result.official ? "Período oficial analisado" : "Período analisado"}{result.analysis_label && ` · ${result.analysis_label}`}</strong><span>{formatDate(result.period.start)} → {formatDate(result.period.end)} · {formatDuration(result.statistics.general.analyzed_period_seconds)}</span></p></Panel>
      <div className="metrics-grid six"><Metric label="Potência média" value={metric(result.statistics.electrical.active_power_w.mean, "W")} /><Metric label="Potência máxima" value={metric(result.statistics.electrical.active_power_w.max, "W")} /><Metric label="Energia" value={metric(result.statistics.electrical.energy_wh, "Wh")} /><Metric label="Temperatura máxima" value={metric(result.statistics.temperature.max, "°C")} /><Metric label="Canal crítico" value={result.statistics.temperature.critical_channel_label ?? "—"} /><Metric label="Duração analisada" value={formatDuration(result.statistics.general.analyzed_period_seconds)} /></div>
      {result.permissions.graphs && <Panel title="Temperatura e potência" kicker="PERÍODO ANALISADO"><SeriesControls series={chartSeries} hidden={hidden} onChange={setHidden} /><div className="chart-container tall"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={rows}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="axisValue" type="number" domain={["dataMin", "dataMax"]} minTickGap={45} tickFormatter={(value) => formatTimeAxis(value, "real")} /><YAxis yAxisId="temperature" unit=" °C" /><YAxis yAxisId="power" orientation="right" unit=" W" /><Tooltip labelFormatter={(value) => formatTimeAxis(Number(value), "real")} /><Line data={rows.filter((row) => row.electricalTimestamp)} yAxisId="power" dataKey="active_power_w" name="Potência" stroke={POWER_COLOR} hide={hidden.includes("active_power_w")} connectNulls={false} dot={false} isAnimationActive={false} />{result.selected_channels.map((channel: number) => <Line key={channel} data={rows.filter((row) => row.thermalTimestamp)} yAxisId="temperature" dataKey={`channel_${channel}`} name={result.channel_labels[String(channel)]} stroke={CHANNEL_COLORS[(channel - 1) % CHANNEL_COLORS.length]} hide={hidden.includes(`channel_${channel}`)} connectNulls={false} dot={false} isAnimationActive={false} />)}{eventGroups.map((group, index) => <ReferenceLine key={index} yAxisId="temperature" x={group.x} stroke="var(--muted)" strokeOpacity={0.6} strokeDasharray="3 5" label={<EventMarkerLabel events={group.events} index={index} />} />)}</ComposedChart></ResponsiveContainer></div></Panel>}
      <Panel title="Indicadores térmicos"><p className="hint">ΔT máximo: {metric(result.statistics.temperature.maximum_delta_t?.value_c, "°C")}</p><div className="table-scroll" tabIndex={0} role="region" aria-label="Indicadores térmicos por canal"><table className="numeric-table"><thead><tr><th>Canal</th><th>Temperatura média</th><th>Temperatura máxima</th></tr></thead><tbody>{(result.statistics.channels ?? []).map((channel: any) => <tr key={channel.channel}><td>{channel.label ?? `T${channel.channel}`}</td><td>{metric(channel.mean, "°C")}</td><td>{metric(channel.max, "°C")}</td></tr>)}</tbody></table></div></Panel>
      <Panel title="Eventos do período"><ResultEvents items={result.annotations} /></Panel>
      {downloads.length > 0 && <section className="download-bar" aria-label="Downloads autorizados"><div><strong>Documentos do ensaio</strong><p className="hint">Arquivos do período analisado.</p></div><div className="action-bar">{downloads.map((kind) => <button className="button secondary" key={kind} disabled={busy} onClick={() => void download(kind)}>Baixar {kind.toUpperCase()}</button>)}</div></section>}
    </>}
    <footer className="public-footer">ThermoPower Monitor · Resultado disponibilizado pelo responsável pelo ensaio.</footer>
  </main>;
}
