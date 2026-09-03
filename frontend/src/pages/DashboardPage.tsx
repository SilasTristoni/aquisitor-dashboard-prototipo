import { AlertTriangle, Pause, Play, Plug, Power, Radio, Square, Wifi, WifiOff } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, formatDuration } from "../api";
import { ErrorNotice, Metric, PageHeader, Panel } from "../components/ui";
import { useLive } from "../hooks/useLive";
import type { Channel, Device, PageResult, Reading, RuntimeStatus, Session, SessionStartResult, SourceConnectionResult } from "../types";
import { buildCombinedView, numericStats, validTemperatures } from "../utils/combinedReadings";

const windows = [
  { label: "30 s", value: 30 }, { label: "1 min", value: 60 },
  { label: "5 min", value: 300 }, { label: "15 min", value: 900 },
  { label: "Sessão", value: 0 },
];
const channelColors = ["#ef4444", "#10b981", "#f59e0b", "#3b82f6", "#8b5cf6", "#ec4899", "#0891b2", "#65a30d"];
type ActiveSession = Pick<Session, "id" | "device_id" | "status" | "started_at">;

function elapsedLabel(timestamp: string | undefined, now: number) {
  if (!timestamp) return "sem leitura";
  const seconds = Math.max((now - new Date(timestamp).getTime()) / 1000, 0);
  return `há ${seconds.toFixed(1)} s`;
}

function integrateEnergyWh(readings: Reading[]): number {
  const ordered = readings
    .filter((reading) => reading.power_w != null)
    .sort((left, right) => Date.parse(left.timestamp) - Date.parse(right.timestamp));
  return ordered.slice(1).reduce((total, current, index) => {
    const previous = ordered[index];
    const seconds = (Date.parse(current.timestamp) - Date.parse(previous.timestamp)) / 1000;
    if (seconds <= 0 || seconds > 60) return total;
    return total + ((previous.power_w! + current.power_w!) / 2) * seconds / 3600;
  }, 0);
}

export default function DashboardPage() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [electricalDeviceId, setElectricalDeviceId] = useState(0);
  const [temperatureDeviceId, setTemperatureDeviceId] = useState(0);
  const [statuses, setStatuses] = useState<Record<number, RuntimeStatus>>({});
  const [channelConfigurations, setChannelConfigurations] = useState<Channel[]>([]);
  const [activeSession, setActiveSession] = useState<ActiveSession | null>(null);
  const [visualPaused, setVisualPaused] = useState(false);
  const [visualSnapshot, setVisualSnapshot] = useState<Reading[]>([]);
  const [windowSeconds, setWindowSeconds] = useState(300);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(Date.now());
  const { connection, readings, lastAlert } = useLive(3600);

  useEffect(() => {
    Promise.all([api<Device[]>("/devices"), api<PageResult<Session>>("/sessions?status=running&page_size=10")])
      .then(([allDevices, sessions]) => {
        setDevices(allDevices);
        const at = allDevices.find((device) => device.protocol === "at4532_serial");
        const gpm = allDevices.find((device) => device.protocol === "gpm8213_serial");
        const simulator = allDevices.find((device) => device.protocol === "simulator");
        setTemperatureDeviceId(at?.id ?? simulator?.id ?? 0);
        setElectricalDeviceId(gpm?.id ?? simulator?.id ?? 0);
        if (sessions.items[0]) setActiveSession(sessions.items[0]);
      })
      .catch((caught) => setError(caught.message));
  }, []);

  useEffect(() => {
    const refresh = async () => {
      const ids = [...new Set([electricalDeviceId, temperatureDeviceId].filter(Boolean))];
      const results = await Promise.all(ids.map(async (id) => [id, await api<RuntimeStatus>(`/devices/${id}/status`)] as const));
      setStatuses(Object.fromEntries(results));
    };
    void refresh().catch(() => undefined);
    const timer = window.setInterval(() => { setNow(Date.now()); void refresh().catch(() => undefined); }, 1000);
    return () => window.clearInterval(timer);
  }, [electricalDeviceId, temperatureDeviceId]);

  useEffect(() => {
    if (!temperatureDeviceId) { setChannelConfigurations([]); return; }
    api<Channel[]>(`/devices/${temperatureDeviceId}/channels`)
      .then((items) => setChannelConfigurations(Array.isArray(items) ? items : []))
      .catch(() => setChannelConfigurations([]));
  }, [temperatureDeviceId]);

  const visibleReadings = useMemo(() => {
    const source = visualPaused ? visualSnapshot : readings;
    if (!windowSeconds) return source;
    const cutoff = Date.now() - windowSeconds * 1000;
    return source.filter((reading) => new Date(reading.timestamp).getTime() >= cutoff);
  }, [readings, visualPaused, visualSnapshot, windowSeconds]);
  const combined = useMemo(() => buildCombinedView(visibleReadings), [visibleReadings]);
  const powerStats = numericStats(combined.electricalReadings.map((reading) => reading.power_w).filter((value): value is number => value != null));
  const temperatures = validTemperatures(combined.latestTemperature);
  const temperatureStats = numericStats(temperatures);
  const energyWh = integrateEnergyWh(combined.electricalReadings);
  const deltaTemperature = temperatureStats.max != null && temperatureStats.min != null
    ? temperatureStats.max - temperatureStats.min : null;
  const hottestIndex = combined.latestTemperature && temperatureStats.max != null
    ? combined.latestTemperature.temperatures_c.indexOf(temperatureStats.max) + 1 : 0;
  const visibleTemperatureChannels = combined.latestTemperature?.temperatures_c
    .flatMap((value, index) => value == null ? [] : [index + 1]) ?? [];
  const electricalDevice = devices.find((device) => device.id === electricalDeviceId);
  const temperatureDevice = devices.find((device) => device.id === temperatureDeviceId);
  const selectedIds = [...new Set([electricalDeviceId, temperatureDeviceId].filter(Boolean))];
  const allConnected = selectedIds.length > 0 && selectedIds.every((id) => statuses[id]?.connected && statuses[id]?.state !== "error");
  const channelLabel = (channel: number) => {
    const configured = channelConfigurations.find((item) => item.channel === channel)?.name?.trim();
    const generic = new Set([`t${channel}`, `ch${channel}`, `canal ${channel}`, `termopar ${channel}`]);
    return configured && !generic.has(configured.toLocaleLowerCase("pt-BR"))
      ? `T${channel} — ${configured}` : `T${channel}`;
  };

  async function action(run: () => Promise<void>) {
    setBusy(true); setError("");
    try { await run(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Falha na operação"); }
    finally { setBusy(false); }
  }

  function applyConnectionStatuses(result: SourceConnectionResult) {
    setStatuses((current) => {
      const next = { ...current };
      for (const source of [result.electrical, result.thermal]) {
        if (!source.device_id) continue;
        next[source.device_id] = source.runtime_status ?? {
          device_id: source.device_id,
          state: source.status,
          connected: false,
          last_error: source.error,
        };
      }
      return next;
    });
  }

  function requestedFailures(result: SourceConnectionResult) {
    return [result.electrical, result.thermal].filter((source) => source.requested && !source.success);
  }

  const connectAll = () => action(async () => {
    const result = await api<SourceConnectionResult>("/devices/connect-sources", {
      method: "POST",
      body: JSON.stringify({
        electrical_device_id: electricalDeviceId || undefined,
        thermal_device_id: temperatureDeviceId || undefined,
      }),
    });
    applyConnectionStatuses(result);
    if (result.overall === "none") setError("Nenhuma fonte pôde ser conectada.");
    else if (requestedFailures(result).length) setError("Uma fonte falhou; a outra permanece disponível.");
  });
  const disconnectOne = (deviceId: number) => action(async () => {
    await api(`/devices/${deviceId}/disconnect`, { method: "POST" });
    setStatuses((current) => ({ ...current, [deviceId]: { device_id: deviceId, state: "disconnected", connected: false } }));
  });
  const start = () => action(async () => {
    const sameDevice = electricalDeviceId > 0 && electricalDeviceId === temperatureDeviceId;
    const sources = sameDevice ? { device_id: electricalDeviceId } : {
      electrical_device_id: electricalDeviceId || undefined,
      temperature_device_id: temperatureDeviceId || undefined,
    };
    const created = await api<SessionStartResult>("/sessions", { method: "POST", body: JSON.stringify({
      ...sources, name: `Ensaio combinado ${new Date().toLocaleDateString("pt-BR")}`, sample_interval_ms: 1000,
    }) });
    applyConnectionStatuses(created.connection);
    if (created.status === "failed") throw new Error("Nenhuma fonte está disponível para iniciar a sessão.");
    if (requestedFailures(created.connection).length) setError("Sessão iniciada com a fonte disponível; a outra apresentou falha.");
    setActiveSession(created);
  });
  const transition = (name: "pause" | "resume" | "finish") => action(async () => {
    const result = await api<any>(`/sessions/${activeSession!.id}/${name}`, { method: "POST" });
    if (name === "finish") setActiveSession(null);
    else setActiveSession((current) => current ? { ...current, status: result.status } : null);
  });
  function toggleVisualPause() { if (!visualPaused) setVisualSnapshot(readings); setVisualPaused(!visualPaused); }

  const statusCard = (label: string, device: Device | undefined, reading: Reading | undefined) => {
    const status = device ? statuses[device.id] : undefined;
    const sourceFailed = status?.state === "error" || Boolean(status?.last_error);
    const values = reading ? validTemperatures(reading) : [];
    return <div className="source-status">
      <span className={`device-orb ${status?.connected && !sourceFailed ? "connected" : "disconnected"}`}><Radio /></span>
      <div><span>{label}</span><strong>{device?.name ?? "Não selecionado"}</strong>
        <small>{sourceFailed ? "Falha nesta fonte" : status?.connected ? "Conectado" : "Desconectado"} · {elapsedLabel(reading?.timestamp ?? status?.last_message_at, now)}</small>
        {label === "AT4532" && <small>{values.length}/32 canais válidos</small>}
        {label === "GPM-8213" && <small>{reading?.power_w == null ? "Potência indisponível" : `${reading.power_w.toFixed(1)} W`}</small>}
        <small>{status?.sample_count ?? (label === "AT4532" ? combined.temperatureReadings.length : combined.electricalReadings.length)} amostras nesta conexão</small>
        {status?.last_error && <small className="danger-text">{status.last_error}</small>}
      </div>
      {device && status?.connected && <button className="button ghost small" onClick={() => void disconnectOne(device.id)}><Power /> Desconectar</button>}
    </div>;
  };

  return <>
    <PageHeader eyebrow="OPERAÇÃO EM TEMPO REAL" title="Ensaio térmico e elétrico" description="Acompanhe potência e cada ponteira ativa em uma única visão operacional." actions={<>
      <label className="compact-field"><span>Fonte elétrica</span><select value={electricalDeviceId} onChange={(event) => setElectricalDeviceId(Number(event.target.value))} disabled={Boolean(activeSession)}><option value={0}>Não selecionada</option>{devices.filter((device) => device.protocol !== "at4532_serial").map((device) => <option key={device.id} value={device.id}>{device.name}</option>)}</select></label>
      <label className="compact-field"><span>Fonte térmica</span><select value={temperatureDeviceId} onChange={(event) => setTemperatureDeviceId(Number(event.target.value))} disabled={Boolean(activeSession)}><option value={0}>Não selecionada</option>{devices.filter((device) => device.protocol !== "gpm8213_serial").map((device) => <option key={device.id} value={device.id}>{device.name}</option>)}</select></label>
      <button className="button secondary" onClick={connectAll} disabled={!selectedIds.length || busy || allConnected}><Plug /> Conectar fontes</button>
      {!activeSession ? <button className="button primary" onClick={start} disabled={!selectedIds.length || busy}><Play /> Iniciar sessão</button> : activeSession.status === "paused" ? <button className="button primary" onClick={() => transition("resume")}><Play /> Continuar</button> : <button className="button secondary" onClick={() => transition("pause")}><Pause /> Pausar</button>}
      {activeSession && <button className="button dark" onClick={() => transition("finish")}><Square /> Finalizar</button>}
    </>} />
    {error && <ErrorNotice message={error} />}
    <div className="combined-source-status">{statusCard("GPM-8213", electricalDevice, combined.latestElectrical)}{statusCard("AT4532", temperatureDevice, combined.latestTemperature)}
      <div className="source-status session-source-status"><span className="device-orb connected">{connection === "connected" ? <Wifi /> : <WifiOff />}</span><div><span>SESSÃO / WEBSOCKET</span><strong>{activeSession?.status === "running" ? "Em execução" : activeSession?.status === "paused" ? "Pausada" : "Sem sessão"}</strong><small>{connection === "connected" ? "WebSocket conectado" : "WebSocket reconectando"}</small><small>{activeSession ? formatDuration((now - new Date(activeSession.started_at).getTime()) / 1000) : "00:00:00"}</small></div></div>
    </div>
    {lastAlert && <div className="notice warning"><AlertTriangle /><div><strong>Novo alerta crítico</strong><span>{lastAlert.metric === "power" ? "Potência" : `Termopar CH${String(lastAlert.channel).padStart(2, "0")}`} atingiu {lastAlert.measured_value.toFixed(1)}.</span></div></div>}
    <div className="metrics-grid six">
      <Metric label="Potência atual" value={combined.latestElectrical?.power_w == null ? "—" : `${combined.latestElectrical.power_w.toFixed(1)} W`} hint={combined.latestElectrical?.raw_power == null ? "Grandeza indisponível" : `Recebido: ${combined.latestElectrical.raw_power} ${combined.latestElectrical.raw_power_unit}`} tone="primary" />
      <Metric label="Potência média" value={powerStats.avg == null ? "—" : `${powerStats.avg.toFixed(1)} W`} hint={powerStats.min == null ? "Sem leitura elétrica" : `Mín ${powerStats.min.toFixed(1)} · Máx ${powerStats.max!.toFixed(1)}`} />
      <Metric label="Energia monitorada" value={`${energyWh.toFixed(3)} Wh`} hint="Integração por tempo real" />
      <Metric label="Temperatura média" value={temperatureStats.avg == null ? "—" : `${temperatureStats.avg.toFixed(1)} °C`} hint={`${temperatures.length} canais com leitura`} />
      <Metric label="Temperatura máxima" value={temperatureStats.max == null ? "—" : `${temperatureStats.max.toFixed(1)} °C`} hint={hottestIndex ? channelLabel(hottestIndex) : "Sem leitura de temperatura"} tone="warm" />
      <Metric label="ΔT entre canais" value={deltaTemperature == null ? "—" : `${deltaTemperature.toFixed(1)} °C`} hint="Leitura térmica mais recente" />
      <Metric label="Amostras elétricas" value={combined.electricalReadings.length.toLocaleString("pt-BR")} hint="Timestamps reais do GPM" />
      <Metric label="Amostras térmicas" value={combined.temperatureReadings.length.toLocaleString("pt-BR")} hint="Sem duplicação entre ciclos" />
    </div>
    <Panel title="Potência e temperatura na mesma janela" kicker="SÉRIES COM TIMESTAMPS REAIS" actions={<div className="chart-actions"><button onClick={toggleVisualPause}>{visualPaused ? <Play /> : <Pause />} {visualPaused ? "Retomar" : "Pausar visual"}</button></div>}>
      <div className="chart-container combined-chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={combined.chartData}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="time" minTickGap={35} /><YAxis yAxisId="temperature" width={58} unit=" °C" /><YAxis yAxisId="power" orientation="right" width={58} unit=" W" /><Tooltip contentStyle={{ borderRadius: 12 }} /><Legend verticalAlign="top" height={48} /><Line yAxisId="power" type="monotone" dataKey="power" name="Potência ativa" stroke="#2563EB" dot={false} strokeWidth={2.7} connectNulls={false} isAnimationActive={false} />{visibleTemperatureChannels.map((channel) => <Line key={channel} yAxisId="temperature" type="monotone" dataKey={`t${channel}`} name={channelLabel(channel)} stroke={channelColors[(channel - 1) % channelColors.length]} dot={false} connectNulls={false} isAnimationActive={false} />)}</LineChart></ResponsiveContainer></div>
    </Panel>
    <div className="dashboard-bottom"><Panel title="Mapa térmico dos 32 canais" kicker="LEITURA AT4532 MAIS RECENTE"><div className="heatmap">{Array.from({ length: 32 }, (_, index) => { const value = combined.latestTemperature?.temperatures_c[index]; const quality = combined.latestTemperature?.channel_quality?.[index] ?? (value == null ? "unavailable" : "good"); const level = value == null ? "missing" : value >= 80 ? "critical" : value >= 70 ? "warning" : "normal"; const reference = value != null ? " reference-channel" : ""; return <div key={index} className={`heat-cell ${level}${reference}`}><span>{channelLabel(index + 1)}</span><strong>{value == null ? "—" : `${value.toFixed(1)}°`}</strong><small>{quality === "good" ? "Boa" : quality === "open_sensor" ? "Open" : "Indisponível"}</small></div>; })}</div></Panel><Panel title="Janela de visualização" kicker="CONTROLES"><div className="segmented">{windows.map((item) => <button className={windowSeconds === item.value ? "active" : ""} key={item.value} onClick={() => setWindowSeconds(item.value)}>{item.label}</button>)}</div><p className="hint">Cada fonte preserva seu timestamp original; nenhum valor ausente é convertido em zero.</p><p className="hint">Os canais com leitura válida são incluídos dinamicamente nas curvas e na legenda.</p></Panel></div>
  </>;
}
