import { Panel } from "./ui";

const metrics = [
  ["successful_fetches", "FETCH válidos"], ["fetch_timeouts", "Timeouts de FETCH"],
  ["consecutive_fetch_timeouts", "Timeouts consecutivos"], ["reconnect_count", "Reconexões"],
  ["average_fetch_interval_ms", "Intervalo médio entre tentativas (ms)"],
  ["average_successful_rx_interval_ms", "Intervalo médio entre respostas válidas (ms)"],
  ["maximum_gap_ms", "Maior intervalo sem resposta válida (ms)"],
  ["average_query_duration_ms", "Duração média da consulta (ms)"],
  ["last_successful_fetch_at", "Último FETCH válido"],
];
const seconds = (value?: number) => value == null ? "Aguardando leituras" : `${(value / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 2 })} s`;

export function AcquisitionDiagnostics({ devices }: { devices: any[] }) {
  return <Panel title="Cadência e recuperação das fontes" kicker="DIAGNÓSTICO SOMENTE LEITURA">
    <p className="hint">Estes dados vêm da aquisição em andamento. Nenhuma porta é aberta ou reiniciada ao consultar esta tela.</p>
    {!devices.length && <p>Conecte uma fonte em Tempo real para acompanhar a aquisição.</p>}
    {devices.map((device) => <div className="quality-source" key={device.device_id}>
      <strong>{device.device_name || `Equipamento ${device.device_id}`}</strong>
      <span>{device.connected ? "Este equipamento já está em aquisição pelo ThermoPower." : "Equipamento desconectado."}</span>
      <span>Intervalo configurado: {seconds(device.expected_interval_ms)} · Observado: {seconds(device.observed_interval_ms)}</span>
      {device.cadence_degraded && <strong className="warning-text">Frequência de leitura reduzida</strong>}
      {device.acquisition_diagnostics && <details><summary>Métricas técnicas e última falha</summary>
        <div className="technical-metrics">{metrics.map(([key, label]) => <div key={key}><span>{label}</span><strong>{typeof device.acquisition_diagnostics[key] === "number" ? device.acquisition_diagnostics[key].toLocaleString("pt-BR", { maximumFractionDigits: 2 }) : device.acquisition_diagnostics[key] ?? "—"}</strong></div>)}</div>
        {device.acquisition_diagnostics.last_failure && <div className="technical-metrics">{Object.entries(device.acquisition_diagnostics.last_failure).map(([key, value]) => <div key={key}><span>{key}</span><code>{String(value ?? "—")}</code></div>)}</div>}
      </details>}
    </div>)}
  </Panel>;
}
