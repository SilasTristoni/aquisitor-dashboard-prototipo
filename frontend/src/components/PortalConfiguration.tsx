import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { ErrorNotice, Spinner } from "./ui";

export type PortalStatus = { configured: boolean; url: string; installation_id: string; managed_by_environment: boolean; can_configure: boolean };

export function PortalConfiguration({ onStatus, expanded = false }: { onStatus?: (status: PortalStatus) => void; expanded?: boolean }) {
  const [status, setStatus] = useState<PortalStatus | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [validated, setValidated] = useState(false);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    api<PortalStatus>("/results-portal/configuration").then(value => { setStatus(value); onStatus?.(value); }).catch(reason => setError(reason.message));
  }, [onStatus]);
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget; const values = new FormData(form);
    setBusy(true); setError(""); setMessage(""); setValidated(false);
    try {
      const value = await api<PortalStatus>("/results-portal/configuration", { method: "PUT", body: JSON.stringify({ url: values.get("url"), installation_id: values.get("installation_id"), credential: values.get("credential") }) });
      setStatus(value); onStatus?.(value); setDirty(false); setMessage("Configuração salva no cofre do Windows. Teste a conexão.");
    } catch (reason) { setError((reason as Error).message); } finally { (form.elements.namedItem("credential") as HTMLInputElement).value = ""; setBusy(false); }
  }
  async function check() {
    setBusy(true); setError(""); setMessage(""); setValidated(false);
    try { await api("/results-portal/check", { method: "POST", signal: AbortSignal.timeout(35000) }); setValidated(true); setMessage("Conexão HTTPS e credencial da instalação confirmadas."); }
    catch (reason) { setError((reason as Error).message); } finally { setBusy(false); }
  }
  return <div>
    {!status && !error && <Spinner label="Carregando configuração do portal" />}
    {(status || error) && <p role="status" aria-label="Estado do portal">{error ? "Erro" : validated ? "Conexão validada" : status?.configured ? "Configurado" : "Não configurado"}</p>}
    {error && <ErrorNotice message={error} />}
    {message && <p role="status">{message}</p>}
    {status && !status.configured && <p className="notice warning">O compartilhamento externo depende da configuração do portal HTTPS pelo administrador. Os relatórios locais continuam disponíveis.</p>}
    {status?.can_configure && <details className="disclosure-card" open={expanded || undefined}><summary>Configuração administrativa do portal</summary>
      <p className="hint">Use a URL da API no Render e a credencial exclusiva desta instalação. A credencial é protegida pelo Gerenciador de Credenciais do usuário Windows que executa o ThermoPower.</p>
      {status.managed_by_environment ? <><p>Configuração gerenciada pelo ambiente: {status.url}</p><p>Identificador da instalação: {status.installation_id}</p></> : <form className="compact-form" onSubmit={event => void save(event)} onChange={() => { setDirty(true); setValidated(false); setMessage(""); }}>
        <label className="field"><span>URL HTTPS da API do portal</span><input name="url" type="url" defaultValue={status.url} disabled={busy} required maxLength={512} placeholder="https://sua-api.onrender.com" /></label>
        <label className="field"><span>Identificador da instalação</span><input name="installation_id" defaultValue={status.installation_id} disabled={busy} pattern="[a-zA-Z0-9_-]{1,64}" required /></label>
        <label className="field"><span>Credencial da instalação</span><input name="credential" type="password" autoComplete="new-password" disabled={busy} required minLength={32} maxLength={256} /></label>
        <p className="hint">Credenciais armazenadas nunca são exibidas. Para salvar, informe a credencial desta instalação novamente.</p>
        <button className="button secondary" disabled={busy}>Salvar configuração</button>
      </form>}
      {dirty && <p className="hint">Salve as alterações antes de testar a conexão.</p>}
      <button type="button" className="button secondary" disabled={busy || !status.configured || dirty} onClick={() => void check()}>Testar conexão com o portal</button>
    </details>}
  </div>;
}
