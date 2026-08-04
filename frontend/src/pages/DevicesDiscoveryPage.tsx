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
import { api, formatDate } from "../api";
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
          baud_rate: Number(data.get("baud")),
          active: true,
          metadata: {},
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

  async function testConnection(id: number) {
    setTest({ loading: true });
    try {
      setTest(await api(`/devices/${id}/test`, { method: "POST" }));
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
                <div><span>BAUD RATE</span><strong>{device.baud_rate.toLocaleString("pt-BR")}</strong></div>
                <div><span>ÚLTIMA CONEXÃO</span><strong>{formatDate(device.last_connected_at)}</strong></div>
              </div>
              <div className="device-actions">
                <button className="button secondary" onClick={() => void testConnection(device.id)}><FlaskConical /> Testar em etapas</button>
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
                    <Badge tone={stage.status === "passed" ? "success" : stage.status === "failed" ? "danger" : "neutral"}>{stage.status === "passed" ? "OK" : stage.status === "failed" ? "Falha" : "Não executado"}</Badge>
                    <span>{stage.label}</span><small>{stage.message}</small>
                  </div>
                ))}
              </div>
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
              <label className="field"><span>Baud rate</span><select name="baud" defaultValue="115200"><option>9600</option><option>19200</option><option>57600</option><option>115200</option></select></label>
            </div>
            <p className="hint"><Cable /> A seleção da porta não confirma o protocolo do instrumento.</p>
            <div className="modal-actions"><button type="button" className="button ghost" onClick={() => setShowCreate(false)}>Cancelar</button><button className="button primary"><Save /> Salvar</button></div>
          </form>
        </div>
      )}
    </>
  );
}
