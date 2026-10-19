import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { ErrorNotice } from "./ui";

export type PortalStatus = { configured: boolean; url: string; installation_id: string; managed_by_environment: boolean; can_configure: boolean };

export function PortalConfiguration({ onStatus }: { onStatus: (status: PortalStatus) => void }) {
  const [status, setStatus] = useState<PortalStatus | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api<PortalStatus>("/results-portal/configuration").then(value => { setStatus(value); onStatus(value); }).catch(reason => setError(reason.message));
  }, [onStatus]);
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget; const values = new FormData(form);
    setBusy(true); setError(""); setMessage("");
    try {
      const value = await api<PortalStatus>("/results-portal/configuration", { method: "PUT", body: JSON.stringify({ url: values.get("url"), installation_id: values.get("installation_id"), credential: values.get("credential") }) });
      setStatus(value); onStatus(value); form.reset(); setMessage("Configuração salva no cofre do Windows. Teste a conexão.");
    } catch (reason) { setError((reason as Error).message); } finally { (form.elements.namedItem("credential") as HTMLInputElement).value = ""; setBusy(false); }
  }
  async function check() {
    setBusy(true); setError(""); setMessage("");
    try { await api("/results-portal/check", { method: "POST", signal: AbortSignal.timeout(35000) }); setMessage("Conexão HTTPS e credencial da instalação confirmadas."); }
    catch (reason) { setError((reason as Error).message); } finally { setBusy(false); }
  }
  return <div>
    {error && <ErrorNotice message={error} />}
    {message && <p role="status">{message}</p>}
    {status && !status.configured && <p className="notice warning">O compartilhamento externo depende da configuração do portal HTTPS pelo administrador. Os relatórios locais continuam disponíveis.</p>}
    {status?.can_configure && <details className="disclosure-card"><summary>Configuração administrativa do portal</summary>
      <p className="hint">Use a URL da API no Render e a credencial exclusiva desta instalação. A credencial é protegida pelo Gerenciador de Credenciais do usuário Windows que executa o ThermoPower.</p>
      {status.managed_by_environment ? <p>Configuração gerenciada pelo ambiente: {status.url}</p> : <form className="compact-form" onSubmit={event => void save(event)}>
        <label className="field"><span>URL HTTPS da API do portal</span><input name="url" type="url" defaultValue={status.url} required maxLength={512} placeholder="https://sua-api.onrender.com" /></label>
        <label className="field"><span>Identificador da instalação</span><input name="installation_id" defaultValue={status.installation_id} pattern="[a-zA-Z0-9_-]{1,64}" required /></label>
        <label className="field"><span>Credencial da instalação</span><input name="credential" type="password" autoComplete="new-password" required minLength={32} maxLength={256} /></label>
        <button className="button secondary" disabled={busy}>Salvar configuração</button>
      </form>}
      <button type="button" className="button secondary" disabled={busy || !status.configured} onClick={() => void check()}>Testar conexão com o portal</button>
    </details>}
  </div>;
}
