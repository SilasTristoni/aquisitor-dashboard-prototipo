import { AlertTriangle, Expand, Pause, Play, Plug, Power, Radio, Square, Wifi, WifiOff } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Area, AreaChart, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, formatDuration } from "../api";
import { useLive } from "../hooks/useLive";
import type { Device, PageResult, Reading, Session } from "../types";
import { Badge, ErrorNotice, Metric, PageHeader, Panel } from "../components/ui";

const windows = [{ label: "30 s", value: 30 }, { label: "1 min", value: 60 }, { label: "5 min", value: 300 }, { label: "15 min", value: 900 }, { label: "Sessão", value: 0 }];
const scenarioLabels: Record<string, string> = { normal: "Operação normal", gradual_heating: "Aquecimento gradual", overheating: "Superaquecimento", power_spike: "Pico de potência", sensor_failure: "Sensor com defeito", connection_loss: "Perda de conexão", invalid_messages: "Mensagens inválidas", long_session: "Sessão longa" };

function stats(values: number[]) {
  return values.length ? { min: Math.min(...values), max: Math.max(...values), avg: values.reduce((a, b) => a + b, 0) / values.length } : { min: 0, max: 0, avg: 0 };
}

export default function DashboardPage() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [deviceId, setDeviceId] = useState(0);
  const [deviceState, setDeviceState] = useState("disconnected");
  const [activeSession, setActiveSession] = useState<Session | null>(null);
  const [visualPaused, setVisualPaused] = useState(false);
  const [visualSnapshot, setVisualSnapshot] = useState<Reading[]>([]);
  const [windowSeconds, setWindowSeconds] = useState(300);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const { connection, readings, lastAlert } = useLive(3600);

  useEffect(() => {
    Promise.all([api<Device[]>("/devices"), api<PageResult<Session>>("/sessions?status=running&page_size=10")]).then(([allDevices, sessions]) => {
      setDevices(allDevices); const selected = allDevices[0]; if (selected) setDeviceId(selected.id);
      if (sessions.items[0]) { setActiveSession(sessions.items[0]); setDeviceId(sessions.items[0].device_id); }
    }).catch((err) => setError(err.message));
  }, []);
  useEffect(() => { if (deviceId) api<any>(`/devices/${deviceId}/status`).then((s) => setDeviceState(s.state)).catch(() => setDeviceState("disconnected")); }, [deviceId]);
  const visibleReadings = useMemo(() => {
    const source = visualPaused ? visualSnapshot : readings;
    if (!windowSeconds) return source;
    const cutoff = Date.now() - windowSeconds * 1000;
    return source.filter((reading) => new Date(reading.timestamp).getTime() >= cutoff);
  }, [readings, visualPaused, visualSnapshot, windowSeconds]);
  const latest = visibleReadings.at(-1);
  const powerStats = stats(visibleReadings.map((reading) => reading.power_w));
  const temperatures = latest?.temperatures_c.filter((value): value is number => value != null) ?? [];
  const temperatureStats = stats(temperatures);
  const hottestIndex = latest ? latest.temperatures_c.indexOf(temperatureStats.max) + 1 : 0;
  const firstTime = visibleReadings[0] ? new Date(visibleReadings[0].timestamp).getTime() : Date.now();
  const lastTime = latest ? new Date(latest.timestamp).getTime() : firstTime;
  const frequency = visibleReadings.length > 1 ? (visibleReadings.length - 1) / Math.max((lastTime - firstTime) / 1000, 0.001) : 0;
  const chartData = visibleReadings.map((reading) => ({ time: new Date(reading.timestamp).toLocaleTimeString("pt-BR"), power: reading.power_w, avgTemp: stats(reading.temperatures_c.filter((value): value is number => value != null)).avg, ...Object.fromEntries(reading.temperatures_c.map((value, index) => [`t${index + 1}`, value])) }));

  async function action(run: () => Promise<void>) { setBusy(true); setError(""); try { await run(); } catch (err) { setError(err instanceof Error ? err.message : "Falha na operação"); } finally { setBusy(false); } }
  const connect = () => action(async () => { const status = await api<any>(`/devices/${deviceId}/connect`, { method: "POST" }); setDeviceState(status.state); });
  const disconnect = () => action(async () => { await api(`/devices/${deviceId}/disconnect`, { method: "POST" }); setDeviceState("disconnected"); });
  const start = () => action(async () => { const created = await api<any>("/sessions", { method: "POST", body: JSON.stringify({ device_id: deviceId, name: `Ensaio ${new Date().toLocaleDateString("pt-BR")}`, sample_interval_ms: 1000 }) }); setActiveSession({ ...created, device_id: deviceId } as Session); setDeviceState("reading"); });
  const transition = (name: "pause" | "resume" | "finish") => action(async () => { const result = await api<any>(`/sessions/${activeSession!.id}/${name}`, { method: "POST" }); if (name === "finish") setActiveSession(null); else setActiveSession((current) => current ? { ...current, status: result.status } : null); });
  function toggleVisualPause() { if (!visualPaused) setVisualSnapshot(readings); setVisualPaused(!visualPaused); }
  const applyScenario = (scenario: string) => action(async () => { if (deviceState === "disconnected") await connect(); await api(`/simulator/${deviceId}/scenarios/${scenario}`, { method: "POST" }); });

  return <>
    <PageHeader eyebrow="OPERAÇÃO EM TEMPO REAL" title="Visão geral da aquisição" description="Potência e temperatura com atualização contínua, rastreabilidade e alertas." actions={<><label className="compact-field"><span>Equipamento</span><select value={deviceId} onChange={(e) => setDeviceId(Number(e.target.value))} disabled={deviceState !== "disconnected"}>{devices.map((device) => <option key={device.id} value={device.id}>{device.name}</option>)}</select></label><button className={`button ${deviceState === "disconnected" ? "secondary" : "danger-outline"}`} onClick={deviceState === "disconnected" ? connect : disconnect} disabled={!deviceId || busy}>{deviceState === "disconnected" ? <><Plug /> Conectar</> : <><Power /> Desconectar</>}</button>{!activeSession ? <button className="button primary" onClick={start} disabled={deviceState === "disconnected" || busy}><Play /> Iniciar sessão</button> : activeSession.status === "paused" ? <button className="button primary" onClick={() => transition("resume")}><Play /> Continuar</button> : <button className="button secondary" onClick={() => transition("pause")}><Pause /> Pausar</button>}{activeSession && <button className="button dark" onClick={() => transition("finish")}><Square /> Finalizar</button>}</>}/>
    {error && <ErrorNotice message={error} />}
    <div className="status-strip"><div className="status-main"><span className={`device-orb ${deviceState}`}><Radio /></span><div><span>STATUS DO EQUIPAMENTO</span><strong>{deviceState === "disconnected" ? "Desconectado" : deviceState === "reading" ? "Aquisição em andamento" : "Conectado e disponível"}</strong></div></div><div className="status-facts"><div><span>SESSÃO</span><Badge tone={activeSession?.status === "running" ? "success" : "neutral"}>{activeSession?.status === "running" ? "Em execução" : activeSession?.status === "paused" ? "Pausada" : "Sem sessão"}</Badge></div><div><span>WEBSOCKET</span><strong className={connection === "connected" ? "success-text" : "danger-text"}>{connection === "connected" ? <><Wifi /> Conectado</> : <><WifiOff /> Reconectando</>}</strong></div><div><span>ÚLTIMA LEITURA</span><strong>{latest ? new Date(latest.timestamp).toLocaleTimeString("pt-BR") : "—"}</strong></div><div><span>TEMPO DA SESSÃO</span><strong>{activeSession ? formatDuration((Date.now() - new Date(activeSession.started_at).getTime()) / 1000) : "00:00:00"}</strong></div></div></div>
    {lastAlert && <div className="notice warning"><AlertTriangle /><div><strong>Novo alerta crítico</strong><span>{lastAlert.metric === "power" ? "Potência" : `Termopar T${lastAlert.channel}`} atingiu {lastAlert.measured_value.toFixed(1)} (limite {lastAlert.threshold}).</span></div></div>}
    <div className="metrics-grid six"><Metric label="Potência atual" value={`${(latest?.power_w ?? 0).toFixed(1)} W`} hint={latest ? `Recebido: ${latest.raw_power} ${latest.raw_power_unit}` : "Aguardando leitura"} tone="primary"/><Metric label="Potência média" value={`${powerStats.avg.toFixed(1)} W`} hint={`Mín ${powerStats.min.toFixed(1)} · Máx ${powerStats.max.toFixed(1)}`} /><Metric label="Temperatura média" value={`${temperatureStats.avg.toFixed(1)} °C`} hint={`${temperatures.length} canais com leitura`} /><Metric label="Temperatura máxima" value={`${temperatureStats.max.toFixed(1)} °C`} hint={hottestIndex ? `Termopar T${hottestIndex}` : "Sem leitura"} tone="warm" /><Metric label="Amostras na tela" value={visibleReadings.length.toLocaleString("pt-BR")} hint={`${frequency.toFixed(2)} amostras/s`} /><Metric label="Alertas" value={lastAlert ? "1+" : "0"} hint="Nesta conexão" tone={lastAlert ? "danger" : "default"} /></div>
    <div className="charts-grid"><Panel title="Potência ao longo do tempo" kicker="CURVA DE AQUISIÇÃO" actions={<div className="chart-actions"><button onClick={toggleVisualPause}>{visualPaused ? <Play /> : <Pause />} {visualPaused ? "Retomar" : "Pausar visual"}</button><button><Expand /></button></div>}><div className="chart-container"><ResponsiveContainer width="100%" height="100%"><AreaChart data={chartData}><defs><linearGradient id="powerFill" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#3b6ef5" stopOpacity={0.28}/><stop offset="95%" stopColor="#3b6ef5" stopOpacity={0}/></linearGradient></defs><CartesianGrid strokeDasharray="3 3" vertical={false}/><XAxis dataKey="time" minTickGap={35}/><YAxis width={48} unit=" W"/><Tooltip contentStyle={{borderRadius:12}}/><ReferenceLine y={2000} stroke="#ef4444" strokeDasharray="5 5" label="Limite"/><Area type="monotone" dataKey="power" stroke="#3b6ef5" fill="url(#powerFill)" strokeWidth={2.3} isAnimationActive={false}/></AreaChart></ResponsiveContainer></div></Panel>
      <Panel title="Temperaturas por canal" kicker="TERMOPARES SELECIONADOS" actions={<Badge tone="success">● Tempo real</Badge>}><div className="chart-container"><ResponsiveContainer width="100%" height="100%"><LineChart data={chartData}><CartesianGrid strokeDasharray="3 3" vertical={false}/><XAxis dataKey="time" minTickGap={35}/><YAxis width={45} unit="°"/><Tooltip contentStyle={{borderRadius:12}}/><ReferenceLine y={80} stroke="#ef4444" strokeDasharray="5 5"/><Line type="monotone" dataKey="t1" name="T1" stroke="#3b82f6" dot={false} strokeWidth={2} isAnimationActive={false}/><Line type="monotone" dataKey="t2" name="T2" stroke="#10b981" dot={false} strokeWidth={2} isAnimationActive={false}/><Line type="monotone" dataKey="t3" name="T3" stroke="#f59e0b" dot={false} strokeWidth={2} isAnimationActive={false}/><Line type="monotone" dataKey="t4" name="T4" stroke="#ef4444" dot={false} strokeWidth={2} isAnimationActive={false}/><Line type="monotone" dataKey="avgTemp" name="Média" stroke="#8b5cf6" dot={false} strokeDasharray="5 4" isAnimationActive={false}/></LineChart></ResponsiveContainer></div></Panel></div>
    <div className="dashboard-bottom"><Panel title="Mapa térmico dos 32 canais" kicker="LEITURAS INSTANTÂNEAS"><div className="heatmap">{Array.from({ length: 32 }, (_, index) => { const value = latest?.temperatures_c[index]; const level = value == null ? "missing" : value >= 80 ? "critical" : value >= 70 ? "warning" : "normal"; return <div key={index} className={`heat-cell ${level}`}><span>T{index + 1}</span><strong>{value == null ? "—" : `${value.toFixed(1)}°`}</strong><small>{value == null ? "Sem leitura" : level === "normal" ? "Normal" : level === "warning" ? "Atenção" : "Crítico"}</small></div>; })}</div></Panel><Panel title="Janela e cenário" kicker="CONTROLES DE DEMONSTRAÇÃO"><div className="segmented">{windows.map((item) => <button className={windowSeconds === item.value ? "active" : ""} key={item.value} onClick={() => setWindowSeconds(item.value)}>{item.label}</button>)}</div><label className="field"><span>Cenário do simulador</span><select onChange={(e) => applyScenario(e.target.value)} defaultValue="normal">{Object.entries(scenarioLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><p className="hint">Os cenários alteram a fonte de dados real do backend e podem gerar alertas e lacunas.</p></Panel></div>
  </>;
}
