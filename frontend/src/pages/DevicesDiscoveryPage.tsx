import {
  Cable,
  CirclePlus,
  FlaskConical,
  Link2,
  PlugZap,
  RefreshCw,
  Save,
  Server,
  Trash2,
  Usb,
} from "lucide-react";
import { type FormEvent, useCallback, useEffect, useState } from "react";
import { api, download, formatDate } from "../api";
import { useAuth } from "../auth";
import { Badge, Empty, ErrorNotice, PageHeader, Panel, Spinner } from "../components/ui";
import type { Device } from "../types";

type Discovery = {
  port: string;
  description?: string;
  manufacturer?: string;
  product?: string;
  serial_number?: string;
  vid?: number;
  pid?: number;
  hardware_id?: string;
  location?: string;
  association?: { device_id: number; device_name: string; matched_by: string };
  association_status: "associated" | "ambiguous" | "unassociated";
  status: "available" | "port_busy" | "unavailable" | "driver_missing";
  status_message: string;
  suggested_device?: string;
  suggested_protocol?: string;
  identification_status: string;
  confidence: "low" | "medium" | "high";
  driver_status: string;
  driver_message: string;
};

const statusLabel: Record<string, string> = {
  available: "Disponível",
  port_busy: "Porta ocupada",
  unavailable: "Indisponível",
  driver_missing: "Driver ausente",
};

export default function DevicesDiscoveryPage() {
  const { user } = useAuth();
  const [devices, setDevices] = useState<Device[]>([]);
  const [discoveries, setDiscoveries] = useState<Discovery[]>([]);
  const [statuses, setStatuses] = useState<Record<number, any>>({});
  const [test, setTest] = useState<any>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [loadingDiscovery, setLoadingDiscovery] = useState(false);
  const [error, setError] = useState("");
  const [diagnostic, setDiagnostic] = useState<any>(null);
  const [diagnosticSession, setDiagnosticSession] = useState("");
  const [diagnosticDataBits, setDiagnosticDataBits] = useState("");
  const [diagnosticParity, setDiagnosticParity] = useState("");
  const [diagnosticStopBits, setDiagnosticStopBits] = useState("");
  const [useEngineeringAssumption, setUseEngineeringAssumption] = useState(false);

  const confirmedSerialParameters = Boolean(
    diagnosticDataBits && diagnosticParity && diagnosticStopBits,
  );

  const loadDevices = useCallback(async () => {
    try {
      const rows = await api<Device[]>("/devices");
      setDevices(rows);
      rows.forEach((device) => {
        void api<any>(`/devices/${device.id}/status`).then((status) =>
          setStatuses((current) => ({ ...current, [device.id]: status })),
        );
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao consultar equipamentos");
    }
  }, []);

  const discover = useCallback(async () => {
    setLoadingDiscovery(true);
    try {
      setDiscoveries(await api<Discovery[]>("/hardware/discovery"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha na descoberta USB");
    } finally {
      setLoadingDiscovery(false);
    }
  }, []);

  useEffect(() => {
    void loadDevices();
    void discover();
    const polling = window.setInterval(() => void discover(), 20_000);
    return () => window.clearInterval(polling);
  }, [discover, loadDevices]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      await api("/devices", {
        method: "POST",
        body: JSON.stringify({
          name: data.get("name"),
          manufacturer: data.get("manufacturer") || null,
          model: data.get("model") || null,
          serial_number: data.get("serial") || null,
          connection_type: data.get("connection"),
          protocol: data.get("protocol"),
          port: data.get("port") || null,
          baud_rate: data.get("baud") ? Number(data.get("baud")) : null,
          active: true,
          metadata: {},
          serial_settings: {
            data_bits: data.get("data_bits") ? Number(data.get("data_bits")) : null,
            parity: data.get("parity") || null,
            stop_bits: data.get("stop_bits") ? Number(data.get("stop_bits")) : null,
            timeout_s: data.get("timeout") ? Number(data.get("timeout")) : null,
            read_timeout_s: data.get("read_timeout") ? Number(data.get("read_timeout")) : null,
            line_terminator: data.get("terminator") || null,
            framing: data.get("framing") || null,
          },
        }),
      });
      setShowCreate(false);
      await loadDevices();
      await discover();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao salvar equipamento");
    }
  }

  async function associate(port: string, deviceId: number) {
    if (!deviceId) return;
    try {
      await api("/hardware/discovery/associate", {
        method: "POST",
        body: JSON.stringify({ port, device_id: deviceId }),
      });
      await Promise.all([loadDevices(), discover()]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao associar porta");
    }
  }

  async function testConnection(device: Device, mode: "identity" | "read" | "full") {
    const isAt4532 = device.protocol === "at4532_serial";
    const isPhysicalVendor = isAt4532 || device.protocol === "gpm8213_serial";
    if (!isPhysicalVendor) {
      setTest({ loading: true });
      try {
        setTest(await api(`/devices/${device.id}/test`, { method: "POST" }));
      } catch (reason) {
        setTest({ error: reason instanceof Error ? reason.message : "Falha no diagnóstico" });
      }
      return;
    }
    const source = isAt4532
      ? "AT45xx User's Guide, seções 9.1/9.5.3/9.5.5"
      : "GPM-8213 User Manual, Remote Control/NUMeric Commands";
    const command = mode === "identity"
      ? "*IDN?"
      : isAt4532
        ? "*IDN? + SYST:UNIT CEL + FETCH?"
        : "*IDN? + NUMBER 8/NUMBER? + ITEM1..8 + HEADER? + VALUE?";
    const confirmed = window.confirm(
      `Teste de Protocolo Documentado\n\nEquipamento: ${device.name}\nPorta: ${device.port ?? "não associada"}\nParâmetros: 8-N-1, sem flow control\nFonte: ${source}\nComando/finalidade: ${command}\n\nSerão enviados somente comandos documentados oficialmente pelo fabricante. Confirmar TX?`,
    );
    if (!confirmed) return;
    setTest({ loading: true });
    try {
      setTest(await api(`/devices/${device.id}/protocol-probe`, {
        method: "POST",
        body: JSON.stringify({ mode, operator_confirmed: true }),
      }));
    } catch (reason) {
      setTest({ error: reason instanceof Error ? reason.message : "Falha no diagnóstico" });
    }
  }

  async function toggleConnection(device: Device) {
    try {
      const connected = statuses[device.id]?.connected;
      await api(`/devices/${device.id}/${connected ? "disconnect" : "connect"}`, {
        method: "POST",
      });
      await loadDevices();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha de comunicação");
    }
  }

  async function removeDevice(device: Device) {
    if (!window.confirm(`Remover o equipamento "${device.name}"?`)) return;
    try {
      await api(`/devices/${device.id}`, { method: "DELETE" });
      await Promise.all([loadDevices(), discover()]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao remover equipamento");
    }
  }

  async function openDiagnostic(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const dataBits = useEngineeringAssumption ? null : diagnosticDataBits;
    const parity = useEngineeringAssumption ? null : diagnosticParity;
    const stopBits = useEngineeringAssumption ? null : diagnosticStopBits;
    setDiagnostic({ loading: true });
    try {
      const result = await api<any>("/hardware/serial-diagnostic/open", {
        method: "POST",
        body: JSON.stringify({
          port: data.get("diagnostic_port"),
          baud_rate: Number(data.get("diagnostic_baud")),
          data_bits: dataBits ? Number(dataBits) : null,
          parity: parity || null,
          stop_bits: stopBits ? Number(stopBits) : null,
          timeout_s: Number(data.get("diagnostic_timeout")),
          read_timeout_s: Number(data.get("diagnostic_read_timeout")),
          line_terminator: data.get("diagnostic_terminator") || null,
          framing: data.get("diagnostic_framing") || null,
          use_engineering_assumption_8n1: useEngineeringAssumption,
        }),
      });
      setDiagnosticSession(result.session_id);
      setDiagnostic(result);
    } catch (reason) {
      setDiagnostic({ error: reason instanceof Error ? reason.message : "Falha ao abrir porta" });
    }
  }

  async function readDiagnostic() {
    try {
      setDiagnostic(await api("/hardware/serial-diagnostic/read", {
        method: "POST",
        body: JSON.stringify({ session_id: diagnosticSession, max_bytes: 4096 }),
      }));
    } catch (reason) {
      setDiagnostic({ error: reason instanceof Error ? reason.message : "Falha ao ler bytes" });
    }
  }

  async function closeDiagnostic() {
    try {
      setDiagnostic(await api("/hardware/serial-diagnostic/close", {
        method: "POST",
        body: JSON.stringify({ session_id: diagnosticSession }),
      }));
      setDiagnosticSession("");
    } catch (reason) {
      setDiagnostic({ error: reason instanceof Error ? reason.message : "Falha ao fechar porta" });
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="INTEGRAÇÃO DE HARDWARE"
        title="Equipamentos e portas USB"
        description="Descubra portas do Windows, associe equipamentos e teste a comunicação em etapas."
        actions={
          user?.role === "admin" && (
            <button className="button primary" onClick={() => setShowCreate(true)}>
              <CirclePlus /> Novo equipamento
            </button>
          )
        }
      />
      {error && <ErrorNotice message={error} />}
      <Panel
        title="Descoberta USB / COM"
        kicker="PORTAS ENUMERADAS PELO SISTEMA"
        actions={
          <button className="button secondary" disabled={loadingDiscovery} onClick={discover}>
            <RefreshCw className={loadingDiscovery ? "spin" : ""} /> Atualizar
          </button>
        }
      >
        <p className="hint">
          A descoberta não envia comandos. Sugestões de modelo são apenas possibilidades e a
          validação física continua pendente.
        </p>
        {loadingDiscovery && !discoveries.length ? (
          <Spinner label="Consultando portas do Windows" />
        ) : !discoveries.length ? (
          <Empty
            title="Nenhuma porta COM detectada"
            text="Conecte o cabo USB e verifique o driver no Gerenciador de Dispositivos."
          />
        ) : (
          <div className="usb-grid">
            {discoveries.map((item) => (
              <article className="usb-card" key={item.port}>
                <div className="device-card-top">
                  <span className="device-icon connected"><Usb /></span>
                  <Badge tone={item.status === "available" ? "success" : "warning"}>
                    {statusLabel[item.status] ?? item.status}
                  </Badge>
                </div>
                <h3>{item.port}</h3>
                <p>{item.product || item.description || "Dispositivo serial sem descrição"}</p>
                <dl className="usb-details">
                  <div><dt>Fabricante</dt><dd>{item.manufacturer || "Não informado"}</dd></div>
                  <div><dt>VID / PID</dt><dd>{item.vid != null && item.pid != null ? `${item.vid.toString(16).padStart(4, "0")} / ${item.pid.toString(16).padStart(4, "0")}` : "Não informado"}</dd></div>
                  <div><dt>Série USB</dt><dd>{item.serial_number || "Não informada"}</dd></div>
                  <div><dt>Localização</dt><dd>{item.location || "Não informada"}</dd></div>
                </dl>
                <p className="hint">{item.status_message} {item.driver_message}</p>
                {item.suggested_device && (
                  <div className="association-note">
                    <Badge tone="warning">Confiança {item.confidence}</Badge>
                    <span>{item.suggested_device} · não confirmado</span>
                  </div>
                )}
                {item.association_status === "ambiguous" && (
                  <div className="association-note identity-ambiguous">
                    <strong>Identidade ambígua</strong>
                    <span>VID/PID identifica apenas o conversor. Confirme manualmente esta porta.</span>
                  </div>
                )}
                {item.association ? (
                  <div className="association-note"><Link2 /><span>Associada a <strong>{item.association.device_name}</strong> por {item.association.matched_by}</span></div>
                ) : user?.role !== "viewer" ? (
                  <label className="field compact">
                    <span>Associar equipamento</span>
                    <select defaultValue="" onChange={(event) => void associate(item.port, Number(event.target.value))}>
                      <option value="">Selecionar…</option>
                      {devices.map((device) => <option value={device.id} key={device.id}>{device.name}</option>)}
                    </select>
                  </label>
                ) : null}
              </article>
            ))}
          </div>
        )}
      </Panel>

      {user?.role === "admin" && (
        <Panel title="Diagnóstico serial avançado" kicker="READ-ONLY · NENHUM COMANDO É ENVIADO">
          <div className="safety-notice">Informe os parâmetros observados no software ou manual. Campos desconhecidos não são preenchidos automaticamente. Feche Instrument V1.8.7 ou Power Meter Series se estiverem usando a porta.</div>
          <form className="serial-diagnostic-form" onSubmit={openDiagnostic}>
            <label className="field"><span>Porta</span><select name="diagnostic_port" required defaultValue=""><option value="">Selecionar…</option>{discoveries.map((item) => <option key={item.port} value={item.port}>{item.port} · {item.description}</option>)}</select></label>
            <label className="field"><span>Baud rate</span><input name="diagnostic_baud" type="number" min="300" required placeholder="AT4532: 19200" /></label>
            <div className="serial-diagnostic-mode"><strong>Modo A — Parâmetros confirmados</strong><span>Selecione os três valores somente se foram confirmados no instrumento, software ou manual.</span></div>
            <label className="field"><span>Data bits</span><select name="diagnostic_data_bits" value={diagnosticDataBits} disabled={useEngineeringAssumption} onChange={(event) => setDiagnosticDataBits(event.target.value)}><option value="">Não confirmado</option>{[5, 6, 7, 8].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
            <label className="field"><span>Parity</span><select name="diagnostic_parity" value={diagnosticParity} disabled={useEngineeringAssumption} onChange={(event) => setDiagnosticParity(event.target.value)}><option value="">Não confirmada</option><option value="N">None (N)</option><option value="E">Even (E)</option><option value="O">Odd (O)</option><option value="M">Mark (M)</option><option value="S">Space (S)</option></select></label>
            <label className="field"><span>Stop bits</span><select name="diagnostic_stop_bits" value={diagnosticStopBits} disabled={useEngineeringAssumption} onChange={(event) => setDiagnosticStopBits(event.target.value)}><option value="">Não confirmado</option><option value="1">1</option><option value="1.5">1,5</option><option value="2">2</option></select></label>
            <label className="field"><span>Timeout do diagnóstico (s)</span><input name="diagnostic_timeout" type="number" step="0.05" min="0.05" max="30" required /><small>Não é o intervalo de aquisição do AT4532.</small></label>
            <label className="field"><span>Read timeout do diagnóstico (s)</span><input name="diagnostic_read_timeout" type="number" step="0.05" min="0.05" max="30" required /><small>Não altera o intervalo esperado de 3 s.</small></label>
            <label className="field"><span>Terminador informado</span><input name="diagnostic_terminator" placeholder="Opcional; apenas registro" /></label>
            <label className="field"><span>Framing informado</span><input name="diagnostic_framing" placeholder="Opcional; não interpretado" /></label>
            <label className="serial-diagnostic-assumption"><input type="checkbox" checked={useEngineeringAssumption} onChange={(event) => setUseEngineeringAssumption(event.target.checked)} /><span><strong>Modo B — Teste exploratório com padrão serial</strong>Usar 8 data bits, sem paridade e 1 stop bit apenas como hipótese técnica</span></label>
            {useEngineeringAssumption && <div className="safety-notice danger">8-N-1 NÃO FOI CONFIRMADO PARA ESTE INSTRUMENTO.</div>}
            <button className="button primary" disabled={Boolean(diagnosticSession) || (!confirmedSerialParameters && !useEngineeringAssumption)}>Abrir porta em modo read-only</button>
          </form>
          {diagnostic?.loading && <Spinner label="Abrindo porta serial" />}
          {diagnostic?.error && <ErrorNotice message={diagnostic.error} />}
          {diagnostic && !diagnostic.loading && !diagnostic.error && (
            <div className="serial-diagnostic-result">
              <div className="inline-actions"><Badge tone={diagnostic.port_open ? "success" : "neutral"}>{diagnostic.port_open ? "Porta aberta" : "Porta fechada"}</Badge><span>{diagnostic.bytes_received ?? 0} byte(s) · {diagnostic.elapsed_ms ?? 0} ms</span>{diagnostic.timeout && <Badge tone="warning">Timeout sem dados</Badge>}</div>
              {diagnostic.parameters_source && <div className="serial-parameter-source"><strong>Origem dos parâmetros:</strong> {diagnostic.parameters_source === "engineering_assumption" ? "Hipótese de engenharia" : "Confirmados pelo usuário"} · validação física: {diagnostic.physical_validation}{diagnostic.parameters && <span> · {diagnostic.parameters.data_bits}-{diagnostic.parameters.parity}-{diagnostic.parameters.stop_bits}</span>}</div>}
              {diagnostic.parameters_source === "engineering_assumption" && <div className="safety-notice danger">8-N-1 NÃO FOI CONFIRMADO PARA ESTE INSTRUMENTO. Estes valores não foram salvos como configuração homologada.</div>}
              <div className="serial-raw-grid"><div><strong>HEX</strong><pre>{diagnostic.raw_hex || "Nenhum byte recebido"}</pre></div><div><strong>ASCII seguro</strong><pre>{diagnostic.raw_ascii || "Nenhum byte recebido"}</pre></div></div>
              {diagnostic.errors?.map((item: any) => <ErrorNotice key={item.code} message={`${item.code}: ${item.message}`} />)}
              <div className="inline-actions">{diagnosticSession && <><button className="button secondary" onClick={() => void readDiagnostic()}>Ler até 4096 bytes</button><button className="button ghost" onClick={() => void closeDiagnostic()}>Fechar porta</button></>}</div>
            </div>
          )}
        </Panel>
      )}

      <div className="device-grid">
        {devices.map((device) => {
          const status = statuses[device.id] ?? { connected: false };
          return (
            <Panel key={device.id} className="device-card">
              <div className="device-card-top">
                <span className={`device-icon ${status.connected ? "connected" : ""}`}><Server /></span>
                <Badge tone={status.connected ? "success" : "neutral"}>{status.connected ? "Conectado" : "Desconectado"}</Badge>
              </div>
              <h2>{device.name}</h2>
              <p>{device.manufacturer || "Fabricante não informado"} · {device.model || "Modelo não informado"}</p>
              <div className="device-specs">
                <div><span>PROTOCOLO</span><strong>{device.protocol}</strong></div>
                <div><span>PORTA</span><strong>{device.port || "Virtual"}</strong></div>
                <div><span>BAUD RATE</span><strong>{device.baud_rate?.toLocaleString("pt-BR") || "Não confirmado"}</strong></div>
                <div><span>ÚLTIMA CONEXÃO</span><strong>{formatDate(device.last_connected_at)}</strong></div>
              </div>
              <div className="device-actions">
                {device.protocol === "at4532_serial" || device.protocol === "gpm8213_serial" ? <>
                  <button className="button secondary" onClick={() => void testConnection(device, "identity")}><FlaskConical /> Testar identificação</button>
                  <button className="button secondary" onClick={() => void testConnection(device, "read")}><FlaskConical /> Testar leitura</button>
                  <button className="button secondary" onClick={() => void testConnection(device, "full")}><FlaskConical /> Executar teste completo</button>
                </> : <button className="button secondary" onClick={() => void testConnection(device, "full")}><FlaskConical /> Testar em etapas</button>}
                {user?.role !== "viewer" && <button className="button ghost" onClick={() => void toggleConnection(device)}><PlugZap /> {status.connected ? "Desconectar" : "Conectar"}</button>}
                {user?.role === "admin" && <button className="button ghost danger" onClick={() => void removeDevice(device)}><Trash2 /> Remover</button>}
              </div>
            </Panel>
          );
        })}
      </div>

      {test && (
        <Panel title="Diagnóstico de comunicação" kicker="TESTE EM ETAPAS" actions={<button className="icon-button" onClick={() => setTest(null)}>×</button>}>
          {test.loading ? <Spinner label="Abrindo porta e aguardando dados" /> : test.error ? <ErrorNotice message={test.error} /> : (
            <>
              <div className="test-steps">
                {test.stages?.map((stage: any) => (
                  <div key={stage.key}>
                    <Badge tone={stage.status === "passed" ? "success" : stage.status === "warning" ? "warning" : stage.status === "failed" ? "danger" : "neutral"}>{stage.status === "passed" ? "OK" : stage.status === "warning" ? "ATENÇÃO" : stage.status === "failed" ? "Falha" : "Não executado"}</Badge>
                    <span>{stage.label}</span><small>{stage.message}</small>
                  </div>
                ))}
              </div>
              <div className="safety-notice">Serão enviados somente comandos documentados oficialmente pelo fabricante. Validação física permanece pendente até a resposta do instrumento real.</div>
              {test.transactions?.map((transaction: any, index: number) => (
                <div className="serial-diagnostic-result" key={`${transaction.command_name}-${index}`}>
                  <div className="inline-actions"><Badge tone={transaction.error ? "danger" : "success"}>vendor_documented</Badge><strong>{transaction.command_name}</strong><span>{transaction.elapsed_ms} ms · {transaction.bytes_received} byte(s) · {transaction.observed_terminator ?? "terminador não observado"} · {transaction.frame_count ?? 0} frame(s)</span></div>
                  <p className="hint">Fonte: {transaction.source} · {transaction.section}</p>
                  <div className="serial-raw-grid"><div><strong>TX ASCII · {transaction.timestamp_tx}</strong><pre>{transaction.tx_ascii}</pre><strong>TX HEX</strong><pre>{transaction.tx_hex}</pre></div><div><strong>RX ASCII · {transaction.timestamp_rx}</strong><pre>{transaction.rx_ascii || (transaction.error ? "Nenhum byte recebido" : "Sem resposta esperada")}</pre><strong>RX HEX</strong><pre>{transaction.rx_hex || "—"}</pre></div></div>
                  {transaction.error && <ErrorNotice message={`${transaction.error.code}: ${transaction.error.message}`} />}
                  {transaction.parsed?.parsed_values && <div className="serial-diagnostic-result">
                    <strong>Comparação GPM-8213 / PowerMeterSeries</strong>
                    <p className="hint">NUMBER solicitado/reportado: {transaction.parsed.number_requested} / {transaction.parsed.number_reported}</p>
                    <p className="hint">HEADER solicitado: {transaction.parsed.headers_requested?.join(", ")}</p>
                    <p className="hint">HEADER reportado: {transaction.parsed.headers_reported?.join(", ")}</p>
                    <div className="device-meta">{Object.entries(transaction.parsed.parsed_values).map(([label, value]) => <div key={label}><span>{label}</span><strong>{value == null ? "NAN / indisponível" : String(value)}</strong></div>)}</div>
                    <strong>Valores raw por HEADER reportado</strong><pre>{JSON.stringify(transaction.parsed.raw_values, null, 2)}</pre>
                  </div>}
                  {transaction.parsed?.valid_channel_results && <div className="serial-diagnostic-result">
                    <strong>Leitura AT4532 por canal</strong>
                    <p className="hint">Canais solicitados/recebidos: {transaction.parsed.channel_count_requested} / {transaction.parsed.channel_count_received} · válidos: {transaction.parsed.valid_channels} · indisponíveis: {transaction.parsed.unavailable_channels}</p>
                    <div className="device-meta">{Object.entries(transaction.parsed.valid_channel_results).map(([channel, result]: [string, any]) => <div key={channel}><span>{channel}</span><strong>{result.temperature_c == null ? `Indisponível (${result.raw_token ?? "sem token"})` : `${result.temperature_c} °C`}</strong><small>{result.quality}</small></div>)}</div>
                    {transaction.parsed.unknown_tokens?.length > 0 && <><strong>Tokens ainda não documentados</strong><pre>{JSON.stringify(transaction.parsed.unknown_tokens, null, 2)}</pre></>}
                  </div>}
                  {transaction.parsed?.channels && <div className="serial-diagnostic-result"><strong>CH01–CH32 · valor, qualidade e token raw</strong><div className="device-meta">{transaction.parsed.channels.map((channel: any) => <div key={channel.channel}><span>{channel.channel}</span><strong>{channel.temperature_c == null ? "—" : `${channel.temperature_c} °C`}</strong><small>{channel.quality} · raw: {channel.raw_token ?? "não recebido"}</small></div>)}</div></div>}
                  {transaction.parsed && Object.keys(transaction.parsed).length > 0 && <div><strong>Parser / resultado normalizado</strong><pre>{JSON.stringify(transaction.parsed, null, 2)}</pre></div>}
                </div>
              ))}
              {test.device_id && <button className="button secondary" onClick={() => void download(`/devices/${test.device_id}/diagnostic-export`, `ThermoPower-diagnostic-${test.device_id}.zip`)}>Exportar diagnóstico completo</button>}
              <p className="hint">Resultado automatizado; homologação física: pendente.</p>
            </>
          )}
        </Panel>
      )}

      {showCreate && (
        <div className="modal-backdrop" onMouseDown={() => setShowCreate(false)}>
          <form className="modal" onSubmit={create} onMouseDown={(event) => event.stopPropagation()}>
            <div className="modal-head"><div><p className="eyebrow">CADASTRO</p><h2>Novo equipamento</h2></div><button type="button" onClick={() => setShowCreate(false)}>×</button></div>
            <div className="form-grid">
              <label className="field"><span>Nome</span><input name="name" required /></label>
              <label className="field"><span>Fabricante</span><input name="manufacturer" /></label>
              <label className="field"><span>Modelo</span><input name="model" /></label>
              <label className="field"><span>Número de série</span><input name="serial" /></label>
              <label className="field"><span>Conexão</span><select name="connection"><option value="simulator">Simulador</option><option value="serial">Serial / USB</option></select></label>
              <label className="field"><span>Protocolo</span><select name="protocol"><option value="simulator">Simulador</option><option value="at4532_serial">AT4532 (pendente de homologação)</option><option value="gpm8213_serial">GPM-8213 (pendente de homologação)</option><option value="serial_json">Serial JSON</option><option value="serial_csv">Serial CSV (não homologado)</option></select></label>
              <label className="field"><span>Porta detectada</span><select name="port"><option value="">Virtual / selecionar depois</option>{discoveries.map((item) => <option key={item.port} value={item.port}>{item.port} · {item.description}</option>)}</select></label>
              <label className="field"><span>Baud rate</span><select name="baud" defaultValue=""><option value="">Não confirmado (AT4532 usa 19200)</option><option>9600</option><option>19200</option><option>57600</option><option>115200</option></select></label>
              <label className="field"><span>Data bits</span><select name="data_bits" defaultValue=""><option value="">Não confirmado</option>{[5, 6, 7, 8].map((value) => <option key={value}>{value}</option>)}</select></label>
              <label className="field"><span>Parity</span><select name="parity" defaultValue=""><option value="">Não confirmada</option><option value="N">N</option><option value="E">E</option><option value="O">O</option><option value="M">M</option><option value="S">S</option></select></label>
              <label className="field"><span>Stop bits</span><select name="stop_bits" defaultValue=""><option value="">Não confirmado</option><option value="1">1</option><option value="1.5">1,5</option><option value="2">2</option></select></label>
              <label className="field"><span>Timeout (s)</span><input name="timeout" type="number" min="0.05" max="30" step="0.05" /></label>
              <label className="field"><span>Read timeout (s)</span><input name="read_timeout" type="number" min="0.05" max="30" step="0.05" /></label>
              <label className="field"><span>Terminador</span><input name="terminator" placeholder="Não confirmado" /></label>
              <label className="field"><span>Framing</span><input name="framing" placeholder="Não confirmado" /></label>
            </div>
            <p className="hint"><Cable /> A seleção da porta não confirma o protocolo do instrumento.</p>
            <div className="modal-actions"><button type="button" className="button ghost" onClick={() => setShowCreate(false)}>Cancelar</button><button className="button primary"><Save /> Salvar</button></div>
          </form>
        </div>
      )}
    </>
  );
}
