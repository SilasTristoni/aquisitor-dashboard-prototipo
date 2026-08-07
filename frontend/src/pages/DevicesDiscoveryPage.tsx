import {
  CirclePlus,
  Download,
  FlaskConical,
  Link2,
  PlugZap,
  RefreshCw,
  Save,
  Server,
  Trash2,
  Usb,
} from "lucide-react";
import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { api, downloadWithBody, formatDate } from "../api";
import { useAuth } from "../auth";
import { Badge, Empty, ErrorNotice, PageHeader, Panel, Spinner } from "../components/ui";
import type { Device } from "../types";

type Discovery = {
  source: "real" | "virtual";
  simulated: boolean;
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
  confidence: "low" | "medium" | "high";
  validation_states: Record<string, boolean>;
};

type Runtime = { virtual_lab: boolean; banner?: string; version: string };
type DiagnosticPreview = {
  consent: string;
  snapshots: Array<{ id: string; name: string; captured_at: string; serial_ports: Discovery[] }>;
  diffs: Array<{
    added_ports: Discovery[];
    removed_ports: Discovery[];
    changed_devices: unknown[];
    port_changes_by_serial: unknown[];
  }>;
  excluded: string[];
};

const statusLabel: Record<string, string> = {
  available: "Disponível",
  port_busy: "Porta ocupada",
  unavailable: "Indisponível",
  driver_missing: "Driver ausente",
};

function ValidationBadges({ item }: { item: Discovery }) {
  return (
    <div className="badge-row">
      {item.simulated ? (
        <Badge tone="primary">Simulado</Badge>
      ) : (
        <Badge tone="primary">Detectado pelo Windows</Badge>
      )}
      {item.suggested_device && <Badge tone="warning">Modelo sugerido</Badge>}
      {item.validation_states.identity_confirmed && <Badge tone="success">Identidade confirmada</Badge>}
      {!item.validation_states.protocol_validated && <Badge tone="warning">Protocolo não validado</Badge>}
      {item.validation_states.homologated && <Badge tone="success">Homologado</Badge>}
    </div>
  );
}

export default function DevicesDiscoveryPage() {
  const { user } = useAuth();
  const [runtime, setRuntime] = useState<Runtime | null>(null);
  const [tab, setTab] = useState("devices");
  const [devices, setDevices] = useState<Device[]>([]);
  const [discoveries, setDiscoveries] = useState<Discovery[]>([]);
  const [statuses, setStatuses] = useState<Record<number, any>>({});
  const [preview, setPreview] = useState<DiagnosticPreview | null>(null);
  const [snapshotName, setSnapshotName] = useState("Captura sem equipamentos");
  const [consent, setConsent] = useState(false);
  const [test, setTest] = useState<any>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [loadingDiscovery, setLoadingDiscovery] = useState(false);
  const [error, setError] = useState("");

  const loadDevices = useCallback(async () => {
    const rows = await api<Device[]>("/devices");
    setDevices(rows);
    const results = await Promise.all(
      rows.map(async (device) => [device.id, await api(`/devices/${device.id}/status`)] as const),
    );
    setStatuses(Object.fromEntries(results));
  }, []);

  const discover = useCallback(async () => {
    if (document.visibilityState === "hidden") return;
    setLoadingDiscovery(true);
    try {
      setDiscoveries(await api<Discovery[]>("/hardware/discovery"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha na descoberta USB");
    } finally {
      setLoadingDiscovery(false);
    }
  }, []);

  const loadPreview = useCallback(async () => {
    setPreview(await api<DiagnosticPreview>("/hardware/diagnostic/preview"));
  }, []);

  useEffect(() => {
    void Promise.all([loadDevices(), discover(), api<Runtime>("/runtime").then(setRuntime)]).catch(
      (reason) => setError(reason instanceof Error ? reason.message : "Falha ao carregar a tela"),
    );
  }, [discover, loadDevices]);

  useEffect(() => {
    if (tab !== "usb") return;
    const polling = window.setInterval(() => void discover(), 4_000);
    const resume = () => document.visibilityState === "visible" && void discover();
    document.addEventListener("visibilitychange", resume);
    return () => {
      window.clearInterval(polling);
      document.removeEventListener("visibilitychange", resume);
    };
  }, [discover, tab]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
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
          baud_rate: Number(data.get("baud")),
          active: true,
          metadata: {},
        }),
      });
      setShowCreate(false);
      await loadDevices();
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

  async function toggleConnection(device: Device) {
    try {
      await api(`/devices/${device.id}/${statuses[device.id]?.connected ? "disconnect" : "connect"}`, {
        method: "POST",
      });
      await loadDevices();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha de comunicação");
    }
  }

  async function captureSnapshot() {
    try {
      await api("/hardware/diagnostic/snapshots", {
        method: "POST",
        body: JSON.stringify({ name: snapshotName }),
      });
      await loadPreview();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao capturar diagnóstico");
    }
  }

  async function plug(profile: "at4532" | "gpm8213", port: string) {
    try {
      await api("/lab/usb/plug", { method: "POST", body: JSON.stringify({ profile, port }) });
      await discover();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha no laboratório virtual");
    }
  }

  const latestDiff = preview?.diffs.at(-1);
  const tabs = useMemo(
    () => [
      ["devices", "Equipamentos cadastrados"],
      ["usb", "USB detectados"],
      ["diagnostic", "Diagnóstico"],
      ...(runtime?.virtual_lab ? [["lab", "Laboratório virtual"]] : []),
    ],
    [runtime?.virtual_lab],
  );

  return (
    <>
      {runtime?.virtual_lab && (
        <div className="virtual-lab-banner">LABORATÓRIO VIRTUAL · VERSÃO {runtime.version} — dados simulados e isolados</div>
      )}
      <PageHeader
        eyebrow="INTEGRAÇÃO DE HARDWARE"
        title="Equipamentos"
        description="Descoberta segura, associação, diagnóstico físico e laboratório claramente separados."
        actions={
          user?.role === "admin" && (
            <button className="button primary" onClick={() => setShowCreate(true)}>
              <CirclePlus /> Novo equipamento
            </button>
          )
        }
      />
      {error && <ErrorNotice message={error} />}
      <div className="section-tabs" role="tablist">
        {tabs.map(([key, label]) => (
          <button key={key} className={tab === key ? "active" : ""} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </div>

      {tab === "devices" && (
        <div className="device-grid">
          {devices.map((device) => {
            const status = statuses[device.id] ?? { connected: false };
            const simulated = device.protocol.startsWith("virtual_") || device.metadata?.simulated;
            return (
              <Panel key={device.id} className="device-card">
                <div className="device-card-top">
                  <span className={`device-icon ${status.connected ? "connected" : ""}`}><Server /></span>
                  <div className="badge-row">
                    {simulated && <Badge tone="primary">Simulado</Badge>}
                    <Badge tone={status.connected ? "success" : "neutral"}>{status.connected ? "Conectado" : "Desconectado"}</Badge>
                  </div>
                </div>
                <h2>{device.name}</h2>
                <p>{device.manufacturer || "Fabricante não informado"} · {device.model || "Modelo não informado"}</p>
                <div className="device-specs">
                  <div><span>PROTOCOLO</span><strong>{device.protocol}</strong></div>
                  <div><span>PORTA</span><strong>{device.port || "Não associada"}</strong></div>
                  <div><span>ÚLTIMA CONEXÃO</span><strong>{formatDate(device.last_connected_at)}</strong></div>
                </div>
                <div className="device-actions">
                  <button className="button secondary" onClick={async () => setTest(await api(`/devices/${device.id}/test`, { method: "POST" }))}><FlaskConical /> Testar em etapas</button>
                  {user?.role !== "viewer" && <button className="button ghost" onClick={() => void toggleConnection(device)}><PlugZap /> {status.connected ? "Desconectar" : "Conectar"}</button>}
                  {user?.role === "admin" && <button className="button ghost danger" onClick={async () => { if (confirm(`Remover ${device.name}?`)) { await api(`/devices/${device.id}`, { method: "DELETE" }); await loadDevices(); } }}><Trash2 /> Remover</button>}
                </div>
              </Panel>
            );
          })}
        </div>
      )}

      {tab === "usb" && (
        <Panel
          title="USB / COM enumerados"
          kicker={runtime?.virtual_lab ? "ORIGEM: LABORATÓRIO VIRTUAL" : "ORIGEM: WINDOWS E PYSERIAL"}
          actions={<button className="button secondary" onClick={discover}><RefreshCw className={loadingDiscovery ? "spin" : ""} /> Atualizar dispositivos</button>}
        >
          <div className="safety-notice">A detecção confirma somente que o Windows enumerou um dispositivo. Não confirma a leitura ou homologação do instrumento.</div>
          {loadingDiscovery && !discoveries.length ? <Spinner /> : !discoveries.length ? <Empty title="Nenhum equipamento detectado" /> : (
            <div className="usb-grid">
              {discoveries.map((item) => (
                <article className={`usb-card ${item.simulated ? "simulated" : ""}`} key={`${item.source}-${item.port}`}>
                  <div className="device-card-top"><span className="device-icon connected"><Usb /></span><Badge tone={item.status === "available" ? "success" : "warning"}>{statusLabel[item.status]}</Badge></div>
                  <h3>{item.port}</h3><p>{item.product || item.description || "Dispositivo sem descrição"}</p>
                  <ValidationBadges item={item} />
                  <dl className="usb-details">
                    <div><dt>Origem</dt><dd>{item.simulated ? "Virtual" : "Real"}</dd></div>
                    <div><dt>VID / PID</dt><dd>{item.vid != null && item.pid != null ? `${item.vid.toString(16).padStart(4, "0")} / ${item.pid.toString(16).padStart(4, "0")}` : "Não informado"}</dd></div>
                    <div><dt>Série</dt><dd>{item.serial_number || "Não informada"}</dd></div>
                    <div><dt>Localização</dt><dd>{item.location || "Não informada"}</dd></div>
                  </dl>
                  <p className="hint">{item.status_message}</p>
                  {item.association ? <div className="association-note"><Link2 /><span>Associada a <strong>{item.association.device_name}</strong></span></div> : user?.role !== "viewer" && (
                    <label className="field compact"><span>Associar equipamento</span><select defaultValue="" onChange={(event) => void associate(item.port, Number(event.target.value))}><option value="">Selecionar…</option>{devices.map((device) => <option value={device.id} key={device.id}>{device.name}</option>)}</select></label>
                  )}
                </article>
              ))}
            </div>
          )}
        </Panel>
      )}

      {tab === "diagnostic" && (
        <Panel title="Diagnóstico de equipamentos USB" kicker="SOMENTE LEITURA — NENHUM BYTE É ENVIADO">
          <div className="safety-notice">Capture primeiro sem equipamentos e repita após cada conexão. O diagnóstico pode abrir e fechar uma COM, mas não transmite comandos.</div>
          <div className="inline-actions"><input value={snapshotName} onChange={(event) => setSnapshotName(event.target.value)} /><button className="button primary" onClick={() => void captureSnapshot()}>Capturar estado atual</button><button className="button secondary" onClick={() => void loadPreview()}>Visualizar dados</button></div>
          {preview && <div className="diagnostic-preview"><h3>Dados que serão exportados</h3><p>{preview.consent}</p><p>{preview.snapshots.length} captura(s) · {latestDiff?.added_ports.length ?? 0} porta(s) adicionada(s) · {latestDiff?.removed_ports.length ?? 0} removida(s)</p><ul>{preview.snapshots.map((snapshot) => <li key={snapshot.id}>{snapshot.name} — {formatDate(snapshot.captured_at)} — {snapshot.serial_ports.length} porta(s)</li>)}</ul><p className="hint">Excluído: {preview.excluded.join(", ")}.</p><label className="consent"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} /> {preview.consent}</label><button className="button primary" disabled={!consent} onClick={() => void downloadWithBody("/hardware/diagnostic/export", `ThermoPower-Diagnostico-${new Date().toISOString().slice(0, 16).replace(/[T:]/g, "-")}.zip`, { consent: true })}><Download /> Exportar pacote para suporte</button></div>}
        </Panel>
      )}

      {tab === "lab" && runtime?.virtual_lab && (
        <Panel title="Painel de plug / unplug" kicker="SIMULAÇÃO ISOLADA">
          <div className="safety-notice virtual">Tudo nesta aba é simulado. Porta virtual, VID/PID e leitura virtual não homologam o aparelho físico.</div>
          <div className="lab-controls"><button className="button primary" onClick={() => void plug("at4532", "COM90")}>Conectar AT4532 · COM90</button><button className="button primary" onClick={() => void plug("gpm8213", "COM91")}>Conectar GPM-8213 · COM91</button>{discoveries.map((item) => <div className="lab-device-row" key={item.port}><strong>{item.port} · {item.product}</strong><button className="button ghost" onClick={async () => { await api("/lab/usb/set-busy", { method: "POST", body: JSON.stringify({ port: item.port, enabled: item.status !== "port_busy" }) }); await discover(); }}>Alternar porta ocupada</button><button className="button ghost" onClick={async () => { await api("/lab/usb/set-driver-missing", { method: "POST", body: JSON.stringify({ port: item.port, enabled: item.status !== "driver_missing" }) }); await discover(); }}>Alternar driver</button><button className="button ghost danger" onClick={async () => { await api("/lab/usb/unplug", { method: "POST", body: JSON.stringify({ port: item.port }) }); await discover(); }}>Remover</button></div>)}</div>
          <button className="button secondary" onClick={async () => { await api("/lab/usb/reset", { method: "POST" }); await discover(); }}>Reset completo do laboratório</button>
        </Panel>
      )}

      {test && <Panel title="Resultado do teste" actions={<button onClick={() => setTest(null)}>×</button>}><p>Porta: {test.port_open ? "aberta" : "falha"} · dados: {test.data_received ? "recebidos" : "não recebidos"}</p><Badge tone="warning">Homologação física pendente</Badge></Panel>}
      {showCreate && <div className="modal-backdrop" onMouseDown={() => setShowCreate(false)}><form className="modal" onSubmit={create} onMouseDown={(event) => event.stopPropagation()}><div className="modal-head"><div><p className="eyebrow">CADASTRO</p><h2>Novo equipamento</h2></div><button type="button" onClick={() => setShowCreate(false)}>×</button></div><div className="form-grid"><label className="field"><span>Nome</span><input name="name" required /></label><label className="field"><span>Fabricante</span><input name="manufacturer" /></label><label className="field"><span>Modelo</span><input name="model" /></label><label className="field"><span>Número de série</span><input name="serial" /></label><label className="field"><span>Conexão</span><select name="connection"><option value="simulator">Simulador</option><option value="serial">Serial / USB</option></select></label><label className="field"><span>Protocolo</span><select name="protocol"><option value="simulator">Simulador</option><option value="at4532_serial">AT4532 — protocolo pendente</option><option value="gpm8213_serial">GPM-8213 — protocolo pendente</option></select></label><label className="field"><span>Porta</span><input name="port" placeholder="COM3" /></label><label className="field"><span>Baud rate</span><input name="baud" type="number" defaultValue="115200" /></label></div><p className="hint">A associação da porta não confirma identidade nem protocolo.</p><div className="modal-actions"><button type="button" className="button ghost" onClick={() => setShowCreate(false)}>Cancelar</button><button className="button primary"><Save /> Salvar</button></div></form></div>}
    </>
  );
}
