import { Check, ChevronLeft, ChevronRight, Database, HardDrive, ShieldCheck, Usb } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Badge, Empty, ErrorNotice, PageHeader, Panel, Spinner } from "../components/ui";
import type { Device } from "../types";

const steps = ["Boas-vindas", "Armazenamento", "Administrador", "Descoberta", "Associação", "Teste"];

export default function SetupWizardPage() {
  const { user } = useAuth();
  const [step, setStep] = useState(0);
  const [devices, setDevices] = useState<Device[]>([]);
  const [ports, setPorts] = useState<any[]>([]);
  const [deviceId, setDeviceId] = useState(0);
  const [port, setPort] = useState("");
  const [diagnostics, setDiagnostics] = useState<any>(null);
  const [test, setTest] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function refresh() {
    const [deviceRows, portRows, diagnostic] = await Promise.all([
      api<Device[]>("/devices"),
      api<any[]>("/hardware/discovery"),
      api<any>("/diagnostics"),
    ]);
    setDevices(deviceRows);
    setPorts(portRows);
    setDiagnostics(diagnostic);
    if (deviceRows[0]) setDeviceId((current) => current || deviceRows[0].id);
    if (portRows[0]) setPort((current) => current || portRows[0].port);
  }

  useEffect(() => { void refresh().catch((reason) => setError(reason.message)); }, []);

  async function createAdministrator(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true);
    try {
      await api("/users", {
        method: "POST",
        body: JSON.stringify({ name: data.get("name"), email: data.get("email"), password: data.get("password"), role: "admin" }),
      });
      setStep(3);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao criar administrador");
    } finally {
      setBusy(false);
    }
  }

  async function associate() {
    setBusy(true);
    try {
      await api("/hardware/discovery/associate", { method: "POST", body: JSON.stringify({ port, device_id: deviceId }) });
      await refresh();
      setStep(5);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao associar porta");
    } finally {
      setBusy(false);
    }
  }

  async function runTest() {
    setBusy(true);
    try {
      setTest(await api(`/devices/${deviceId}/test`, { method: "POST" }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha no teste");
    } finally {
      setBusy(false);
    }
  }

  function finish() {
    localStorage.setItem("thermopower.setup.completed", new Date().toISOString());
    window.location.assign("/");
  }

  return (
    <>
      <PageHeader eyebrow="PRIMEIRO USO" title="Configuração inicial" description="Prepare armazenamento, acesso local e aquisição. O simulador permanece disponível sem hardware." />
      {error && <ErrorNotice message={error} />}
      <ol className="wizard-steps">{steps.map((label, index) => <li className={index === step ? "active" : index < step ? "done" : ""} key={label}><span>{index < step ? <Check /> : index + 1}</span><small>{label}</small></li>)}</ol>
      <Panel className="wizard-panel">
        {step === 0 && <div className="wizard-copy"><ShieldCheck /><h2>Bem-vindo ao ThermoPower Monitor</h2><p>Este assistente valida o ambiente local e ajuda a associar portas USB. Nenhuma etapa declara os instrumentos físicos homologados.</p><button className="button primary" onClick={() => setStep(1)}>Começar <ChevronRight /></button></div>}
        {step === 1 && <div className="wizard-copy"><HardDrive /><h2>Armazenamento local</h2>{!diagnostics ? <Spinner /> : <><div className="metrics-grid four"><div><span>Banco</span><strong>{diagnostics.database_dialect}</strong></div><div><span>Espaço livre</span><strong>{(diagnostics.disk_free_bytes / 1_073_741_824).toFixed(1)} GB</strong></div><div><span>Backend</span><strong>{diagnostics.backend_online ? "Operacional" : "Falha"}</strong></div><div><span>Versão</span><strong>{diagnostics.system_version}</strong></div></div><p>No pacote Windows, banco, logs e relatórios ficam em %LOCALAPPDATA%\ThermoPower Monitor.</p></>}<button className="button primary" onClick={() => setStep(2)}>Continuar <ChevronRight /></button></div>}
        {step === 2 && <div className="wizard-copy"><Database /><h2>Administrador local</h2><p>Você está autenticado como <strong>{user?.email}</strong>. Pode manter este administrador ou criar outro acesso local.</p>{user?.role === "admin" && <form className="wizard-form" onSubmit={createAdministrator}><label className="field"><span>Nome</span><input name="name" minLength={2} /></label><label className="field"><span>E-mail</span><input name="email" type="email" /></label><label className="field"><span>Senha temporária</span><input name="password" type="password" minLength={10} /></label><button className="button secondary" disabled={busy}>Criar outro administrador</button></form>}<button className="button primary" onClick={() => setStep(3)}>Usar acesso atual <ChevronRight /></button></div>}
        {step === 3 && <div className="wizard-copy"><Usb /><h2>Descoberta USB / COM</h2>{!ports.length ? <Empty title="Nenhuma porta encontrada" text="Você pode concluir usando o simulador e voltar depois." /> : <div className="usb-grid">{ports.map((item) => <button className={`usb-choice ${port === item.port ? "selected" : ""}`} onClick={() => setPort(item.port)} key={item.port}><strong>{item.port}</strong><span>{item.product || item.description}</span><Badge tone={item.status === "available" ? "success" : "warning"}>{item.status}</Badge></button>)}</div>}<div className="wizard-actions"><button className="button secondary" onClick={() => void refresh()}>Atualizar</button><button className="button primary" onClick={() => setStep(4)}>Continuar <ChevronRight /></button></div></div>}
        {step === 4 && <div className="wizard-copy"><Usb /><h2>Associar equipamento e porta</h2><label className="field"><span>Equipamento</span><select value={deviceId} onChange={(event) => setDeviceId(Number(event.target.value))}>{devices.map((device) => <option value={device.id} key={device.id}>{device.name} · {device.protocol}</option>)}</select></label><label className="field"><span>Porta</span><select value={port} onChange={(event) => setPort(event.target.value)}><option value="">Sem porta · usar simulador</option>{ports.map((item) => <option value={item.port} key={item.port}>{item.port} · {item.description}</option>)}</select></label><p className="hint">A associação guarda os identificadores reais informados pelo Windows, mas não confirma o modelo nem o protocolo.</p><div className="wizard-actions"><button className="button secondary" onClick={() => setStep(5)}>Pular associação</button><button className="button primary" disabled={!port || !deviceId || busy} onClick={() => void associate()}>Associar <ChevronRight /></button></div></div>}
        {step === 5 && <div className="wizard-copy"><ShieldCheck /><h2>Teste final</h2><label className="field"><span>Equipamento</span><select value={deviceId} onChange={(event) => setDeviceId(Number(event.target.value))}>{devices.map((device) => <option value={device.id} key={device.id}>{device.name}</option>)}</select></label><button className="button secondary" disabled={!deviceId || busy} onClick={() => void runTest()}>Executar teste em etapas</button>{test && <div className="test-steps">{test.stages?.map((stage: any) => <div key={stage.key}><Badge tone={stage.status === "passed" ? "success" : stage.status === "failed" ? "danger" : "neutral"}>{stage.status}</Badge><span>{stage.label}</span></div>)}</div>}<p className="hint">Para aceitar sem hardware, selecione “Aquisitor simulado”. Instrumentos reais continuam pendentes de validação física.</p><button className="button primary" onClick={finish}>Concluir configuração <Check /></button></div>}
        {step > 0 && step < 5 && <button className="button ghost wizard-back" onClick={() => setStep((current) => current - 1)}><ChevronLeft /> Voltar</button>}
      </Panel>
    </>
  );
}
