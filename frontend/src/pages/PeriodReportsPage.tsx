import {
  AlertTriangle,
  Download,
  FileImage,
  FileSpreadsheet,
  FileText,
  Search,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, download, downloadWithBody, formatDate } from "../api";
import { Badge, Empty, ErrorNotice, Metric, PageHeader, Panel, Spinner } from "../components/ui";
import type { Device, PageResult, Session } from "../types";

type Tab = "period" | "session" | "history";
type Preview = {
  period: { start: string; end: string; timezone: string };
  sessions: Array<{ id: number; name: string; electrical_samples: number; temperature_samples: number }>;
  statistics: {
    general: {
      session_count: number;
      electrical_sample_count: number;
      temperature_sample_count: number;
      alert_count: number;
      gap_count: number;
      coverage_seconds: number;
    };
    electrical: {
      energy_wh: number;
      active_power_w: { mean?: number; max?: number };
    };
  };
  selected_channels: number[];
  series: Array<{
    session_id: number;
    session_name: string;
    electrical: Array<Record<string, any>>;
    temperatures: Array<Record<string, any>>;
  }>;
  warnings: string[];
};

const channelColors = [
  "#2563EB", "#16A34A", "#D97706", "#DC2626", "#7C3AED", "#0891B2", "#DB2777", "#4F46E5",
];

function localInput(date: Date): string {
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

function mergedSeries(series: Preview["series"][number]): Array<Record<string, any>> {
  const values = new Map<string, Record<string, any>>();
  for (const point of [...series.electrical, ...series.temperatures]) {
    const timestamp = String(point.timestamp);
    values.set(timestamp, { ...(values.get(timestamp) ?? {}), ...point, timestamp });
  }
  return [...values.values()].sort((left, right) => String(left.timestamp).localeCompare(String(right.timestamp)));
}

export default function PeriodReportsPage() {
  const now = useMemo(() => new Date(), []);
  const [tab, setTab] = useState<Tab>("period");
  const [sessions, setSessions] = useState<Session[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [reports, setReports] = useState<any[]>([]);
  const [sessionId, setSessionId] = useState(0);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [start, setStart] = useState(localInput(new Date(now.getTime() - 24 * 3_600_000)));
  const [end, setEnd] = useState(localInput(now));
  const [title, setTitle] = useState("Relatório de medições por período");
  const [subtitle, setSubtitle] = useState("");
  const [description, setDescription] = useState("");
  const [notes, setNotes] = useState("");
  const [deviceId, setDeviceId] = useState(0);
  const [filterSessionId, setFilterSessionId] = useState(0);
  const [channels, setChannels] = useState<number[]>(Array.from({ length: 8 }, (_, index) => index + 1));
  const [includePower, setIncludePower] = useState(true);
  const [includeTemperatures, setIncludeTemperatures] = useState(true);
  const [includeElectrical, setIncludeElectrical] = useState(true);
  const [includeAlerts, setIncludeAlerts] = useState(true);
  const [includeQuality, setIncludeQuality] = useState(true);
  const [includeTable, setIncludeTable] = useState(true);
  const [orientation, setOrientation] = useState("landscape");
  const [theme, setTheme] = useState("light");
  const [dpi, setDpi] = useState(160);
  const [tableRows, setTableRows] = useState(100);
  const [channelGroupSize, setChannelGroupSize] = useState(8);
  const [tolerance, setTolerance] = useState(1500);
  const [useDeviceTimestamp, setUseDeviceTimestamp] = useState(true);
  const [interpolation, setInterpolation] = useState("none");
  const periodValid = Boolean(
    start
    && end
    && new Date(end) > new Date(start)
    && (includePower || includeTemperatures || includeElectrical)
    && (!includeTemperatures || channels.length),
  );

  async function load() {
    try {
      const [sessionResult, deviceResult, reportResult] = await Promise.all([
        api<PageResult<Session>>("/sessions?page_size=100"),
        api<Device[]>("/devices"),
        api<any[]>("/reports"),
      ]);
      setSessions(sessionResult.items);
      setDevices(deviceResult);
      setReports(reportResult);
      if (sessionResult.items[0]) setSessionId((current) => current || sessionResult.items[0].id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao carregar relatórios");
    }
  }

  useEffect(() => { void load(); }, []);

  function applyPreset(hours: number) {
    const presetEnd = new Date();
    setEnd(localInput(presetEnd));
    setStart(localInput(new Date(presetEnd.getTime() - hours * 3_600_000)));
  }

  function toggleChannel(channel: number) {
    setChannels((current) => current.includes(channel) ? current.filter((item) => item !== channel) : [...current, channel].sort((a, b) => a - b));
  }

  function payload() {
    return {
      start: new Date(start).toISOString(),
      end: new Date(end).toISOString(),
      timezone: "America/Sao_Paulo",
      title,
      subtitle: subtitle || null,
      description: description || null,
      notes: notes || null,
      device_ids: deviceId ? [deviceId] : null,
      session_ids: filterSessionId ? [filterSessionId] : null,
      channels: channels.length ? channels : null,
      include_power: includePower,
      include_temperatures: includeTemperatures,
      include_electrical_details: includeElectrical,
      include_alerts: includeAlerts,
      include_quality: includeQuality,
      include_session_list: true,
      include_table: includeTable,
      orientation,
      theme,
      dpi,
      table_max_rows: tableRows,
      channel_group_size: channelGroupSize,
      sync_tolerance_ms: tolerance,
      use_device_timestamp: useDeviceTimestamp,
      interpolation,
    };
  }

  async function generatePreview() {
    if (!periodValid) {
      setError("Revise as datas, métricas e canais antes de gerar a prévia.");
      return;
    }
    setError("");
    setBusy("Consultando amostras e calculando estatísticas…");
    try {
      setPreview(await api<Preview>("/reports/period/preview", { method: "POST", body: JSON.stringify(payload()) }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao gerar prévia");
    } finally {
      setBusy("");
    }
  }

  async function generateFile(kind: "pdf" | "png" | "jpeg") {
    if (!periodValid) {
      setError("Revise as datas, métricas e canais antes de gerar o arquivo.");
      return;
    }
    setError("");
    setBusy(kind === "pdf" ? "Consultando dados, renderizando gráficos e montando o PDF…" : "Consultando dados e renderizando o gráfico…");
    try {
      const endpoint = kind === "pdf" ? "/reports/period/pdf" : `/reports/period/chart.${kind}`;
      await downloadWithBody(endpoint, `relatorio-periodo.${kind}`, payload());
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao gerar arquivo");
    } finally {
      setBusy("");
    }
  }

  const selected = sessions.find((session) => session.id === sessionId);

  return (
    <>
      <PageHeader eyebrow="DOCUMENTAÇÃO TÉCNICA" title="Central de relatórios" description="Gere relatórios rastreáveis por período ou por sessão, com gráficos renderizados no servidor." />
      {error && <ErrorNotice message={error} />}
      <div className="tab-list" role="tablist">
        <button className={tab === "period" ? "active" : ""} onClick={() => setTab("period")}>Por período</button>
        <button className={tab === "session" ? "active" : ""} onClick={() => setTab("session")}>Por sessão</button>
        <button className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}>Histórico</button>
      </div>

      {tab === "period" && (
        <>
          <div className="report-layout period-layout">
            <Panel title="Configurar período" kicker="NOVA GERAÇÃO">
              <div className="preset-row"><button className="button small ghost" onClick={() => applyPreset(1)}>Última hora</button><button className="button small ghost" onClick={() => applyPreset(24)}>24 horas</button><button className="button small ghost" onClick={() => applyPreset(168)}>7 dias</button><button className="button small ghost" onClick={() => applyPreset(720)}>30 dias</button></div>
              <div className="form-grid">
                <label className="field"><span>Início</span><input type="datetime-local" value={start} onChange={(event) => setStart(event.target.value)} /></label>
                <label className="field"><span>Fim</span><input type="datetime-local" value={end} onChange={(event) => setEnd(event.target.value)} /></label>
                <label className="field"><span>Título</span><input value={title} onChange={(event) => setTitle(event.target.value)} /></label>
                <label className="field"><span>Subtítulo</span><input value={subtitle} onChange={(event) => setSubtitle(event.target.value)} /></label>
                <label className="field"><span>Equipamento</span><select value={deviceId} onChange={(event) => setDeviceId(Number(event.target.value))}><option value={0}>Todos</option>{devices.map((device) => <option key={device.id} value={device.id}>{device.name}</option>)}</select></label>
                <label className="field"><span>Sessão</span><select value={filterSessionId} onChange={(event) => setFilterSessionId(Number(event.target.value))}><option value={0}>Todas as sobrepostas</option>{sessions.map((session) => <option key={session.id} value={session.id}>{session.name}</option>)}</select></label>
              </div>
              <label className="field"><span>Descrição</span><textarea value={description} onChange={(event) => setDescription(event.target.value)} /></label>
              <label className="field"><span>Notas</span><textarea value={notes} onChange={(event) => setNotes(event.target.value)} /></label>
              <div className="field"><span>Canais incluídos</span><div className="channel-picker">{Array.from({ length: 32 }, (_, index) => index + 1).map((channel) => <label key={channel}><input type="checkbox" checked={channels.includes(channel)} onChange={() => toggleChannel(channel)} /> T{channel}</label>)}</div></div>
              <div className="check-grid">
                <label><input type="checkbox" checked={includePower} onChange={(event) => setIncludePower(event.target.checked)} /> Potência</label>
                <label><input type="checkbox" checked={includeTemperatures} onChange={(event) => setIncludeTemperatures(event.target.checked)} /> Temperaturas</label>
                <label><input type="checkbox" checked={includeElectrical} onChange={(event) => setIncludeElectrical(event.target.checked)} /> Elétricas detalhadas</label>
                <label><input type="checkbox" checked={includeAlerts} onChange={(event) => setIncludeAlerts(event.target.checked)} /> Alertas</label>
                <label><input type="checkbox" checked={includeQuality} onChange={(event) => setIncludeQuality(event.target.checked)} /> Qualidade</label>
                <label><input type="checkbox" checked={includeTable} onChange={(event) => setIncludeTable(event.target.checked)} /> Tabela resumida</label>
              </div>
              <details className="advanced-options"><summary>Opções avançadas</summary><div className="form-grid">
                <label className="field"><span>Orientação</span><select value={orientation} onChange={(event) => setOrientation(event.target.value)}><option value="landscape">Paisagem</option><option value="portrait">Retrato</option></select></label>
                <label className="field"><span>Tema</span><select value={theme} onChange={(event) => setTheme(event.target.value)}><option value="light">Claro</option><option value="dark">Escuro</option></select></label>
                <label className="field"><span>DPI</span><input type="number" min={96} max={300} value={dpi} onChange={(event) => setDpi(Number(event.target.value))} /></label>
                <label className="field"><span>Linhas da tabela</span><input type="number" min={0} max={2000} value={tableRows} onChange={(event) => setTableRows(Number(event.target.value))} /></label>
                <label className="field"><span>Canais por gráfico</span><input type="number" min={1} max={16} value={channelGroupSize} onChange={(event) => setChannelGroupSize(Number(event.target.value))} /></label>
                <label className="field"><span>Tolerância (ms)</span><input type="number" min={0} max={3000} value={tolerance} onChange={(event) => setTolerance(Number(event.target.value))} /></label>
                <label className="field"><span>Interpolação</span><select value={interpolation} onChange={(event) => setInterpolation(event.target.value)}><option value="none">Nenhuma</option><option value="visual_only">Somente visual</option></select></label>
                <label className="field check-field"><input type="checkbox" checked={useDeviceTimestamp} onChange={(event) => setUseDeviceTimestamp(event.target.checked)} /><span>Preferir timestamp do equipamento</span></label>
              </div></details>
              <div className="report-buttons">
                <button className="button secondary" disabled={Boolean(busy) || !periodValid} onClick={() => void generatePreview()}><Search /> Gerar prévia</button>
                <button className="button primary" disabled={Boolean(busy) || !periodValid} onClick={() => void generateFile("pdf")}><FileText /> Gerar PDF</button>
                <button className="button ghost" disabled={Boolean(busy) || !periodValid} onClick={() => void generateFile("png")}><FileImage /> PNG</button>
                <button className="button ghost" disabled={Boolean(busy) || !periodValid} onClick={() => void generateFile("jpeg")}><FileImage /> JPEG</button>
              </div>
              {!periodValid && <p className="hint danger-text">O fim deve ser posterior ao início; selecione ao menos uma métrica e os canais térmicos.</p>}
              {busy && <Spinner label={busy} />}
            </Panel>

            <Panel title="Prévia do período" kicker="DADOS REDUZIDOS PARA VISUALIZAÇÃO">
              {!preview ? <Empty title="Configure o período e gere uma prévia" text="As estatísticas usarão todos os dados; apenas o gráfico será reduzido." /> : (
                <div className="period-preview">
                  <div className="metrics-grid four"><Metric label="Sessões" value={preview.statistics.general.session_count} /><Metric label="Amostras elétricas" value={preview.statistics.general.electrical_sample_count.toLocaleString("pt-BR")} /><Metric label="Amostras térmicas" value={preview.statistics.general.temperature_sample_count.toLocaleString("pt-BR")} /><Metric label="Energia" value={`${preview.statistics.electrical.energy_wh.toFixed(3)} Wh`} /></div>
                  {preview.warnings.map((warning) => <div className="preview-warning" key={warning}><AlertTriangle /> {warning}</div>)}
                  {preview.series.map((series) => {
                    const points = mergedSeries(series);
                    return <div className="preview-chart" key={series.session_id}><h3>{series.session_name}</h3><ResponsiveContainer width="100%" height={280}><LineChart data={points}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="timestamp" tickFormatter={(value) => new Date(value).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })} minTickGap={45} /><YAxis yAxisId="power" /><YAxis yAxisId="temperature" orientation="right" /><Tooltip labelFormatter={(value) => formatDate(String(value))} /><Legend /><Line yAxisId="power" type="linear" dataKey="active_power_w" name="Potência (W)" stroke="#3B82F6" dot={false} connectNulls={false} />{preview.selected_channels.slice(0, 8).map((channel, index) => <Line key={channel} yAxisId="temperature" type="linear" dataKey={`channel_${channel}`} name={`T${channel}`} stroke={channelColors[index % channelColors.length]} dot={false} connectNulls={false} />)}</LineChart></ResponsiveContainer></div>;
                  })}
                </div>
              )}
            </Panel>
          </div>
        </>
      )}

      {tab === "session" && (
        <div className="report-layout">
          <Panel title="Relatório por sessão" kicker="COMPATIBILIDADE PRESERVADA">
            <label className="field"><span>Sessão</span><select value={sessionId} onChange={(event) => setSessionId(Number(event.target.value))}>{sessions.map((session) => <option key={session.id} value={session.id}>{session.name}</option>)}</select></label>
            <div className="report-buttons"><button className="button primary" disabled={!selected} onClick={() => void download(`/reports/sessions/${sessionId}.pdf`, `sessao-${sessionId}.pdf`)}><FileText /> PDF</button><button className="button secondary" disabled={!selected} onClick={() => void download(`/reports/sessions/${sessionId}.xlsx`, `sessao-${sessionId}.xlsx`)}><FileSpreadsheet /> XLSX</button><button className="button ghost" disabled={!selected} onClick={() => void download(`/reports/sessions/${sessionId}.csv`, `sessao-${sessionId}.csv`)}><Download /> CSV</button></div>
          </Panel>
          <Panel title="Sessão selecionada" kicker="RESUMO">{selected ? <div className="report-preview"><p>RELATÓRIO DE MEDIÇÃO</p><h2>{selected.name}</h2><div><span>Equipamento</span><strong>{selected.device_name}</strong></div><div><span>Operador</span><strong>{selected.operator}</strong></div><div><span>Amostras</span><strong>{selected.sample_count.toLocaleString("pt-BR")}</strong></div><div><span>Alertas</span><strong>{selected.alert_count}</strong></div></div> : <Empty />}</Panel>
        </div>
      )}

      {tab === "history" && (
        <Panel title="Histórico de geração" kicker="ARQUIVOS RECENTES"><div className="table-scroll"><table><thead><tr><th>Status</th><th>Tipo</th><th>Escopo</th><th>Período / sessão</th><th>Título</th><th>Gerado em</th><th>Usuário</th></tr></thead><tbody>{reports.map((report) => <tr key={report.id}><td><Badge tone={report.status === "failed" ? "danger" : report.status === "generating" ? "warning" : "success"}>{report.status === "failed" ? "Falhou" : report.status === "generating" ? "Gerando" : "Concluído"}</Badge></td><td><Badge>{report.type.toUpperCase()}</Badge></td><td>{report.scope_type === "period" ? "Período" : "Sessão"}</td><td>{report.scope_type === "period" ? `${formatDate(report.period_start)} — ${formatDate(report.period_end)}` : `#${report.session_id}`}</td><td>{report.title || "—"}</td><td>{formatDate(report.generated_at)}</td><td>#{report.generated_by}</td></tr>)}</tbody></table></div></Panel>
      )}
    </>
  );
}
