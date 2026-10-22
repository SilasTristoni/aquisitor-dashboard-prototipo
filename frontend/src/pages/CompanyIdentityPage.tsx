import { useEffect, useState } from "react";
import { api } from "../api";
import { CompanyMark, type Identity } from "../components/CompanyIdentity";
import { PageHeader, Panel } from "../components/ui";

export default function CompanyIdentityPage() {
  const [identity, setIdentity] = useState<Identity>({ identity_id: null, company_name: "", laboratory: "", logo: null });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => { void api<Identity>("/company-identity").then(setIdentity).catch((error: Error) => setMessage(error.message)); }, []);
  async function update(path: string, options: RequestInit) {
    setBusy(true); setMessage("");
    try {
      const saved = await api<Identity>(`/company-identity${path}`, options);
      setIdentity(saved); setMessage("Identidade corporativa salva.");
      window.dispatchEvent(new Event("company-identity-changed"));
    } catch (error) { setMessage((error as Error).message); }
    finally { setBusy(false); }
  }
  return <>
    <PageHeader eyebrow="CONFIGURAÇÃO" title="Identidade corporativa" description="Identifique sua empresa nos cabeçalhos e relatórios PDF. A marca ThermoPower permanece visível." />
    <Panel title="Empresa e laboratório" className="company-identity-panel">
      <form className="company-settings" onSubmit={(event) => { event.preventDefault(); void update("", { method: "PUT", body: JSON.stringify({ company_name: identity.company_name, laboratory: identity.laboratory }) }); }}>
        <label>Nome da empresa<input maxLength={120} value={identity.company_name} onChange={(event) => setIdentity({ ...identity, company_name: event.target.value })} /></label>
        <label>Unidade ou laboratório (opcional)<input maxLength={120} value={identity.laboratory} onChange={(event) => setIdentity({ ...identity, laboratory: event.target.value })} /></label>
        <div className="action-bar company-save"><button className="button primary" disabled={busy}>Salvar identificação</button></div>
      </form>
      <section className="company-logo-section" aria-labelledby="company-logo-title">
      <h3 id="company-logo-title">Logotipo da empresa</h3>
      <p className="hint">Escolha uma imagem para identificar seus relatórios e cabeçalhos.</p>
      <label className="company-logo-upload">Logotipo PNG ou JPEG<input type="file" accept="image/png,image/jpeg" disabled={busy} onChange={(event) => {
        const file = event.target.files?.[0]; event.target.value = "";
        if (!file) return;
        if (file.size > 1024 * 1024) { setMessage("O logotipo deve ter até 1 MB."); return; }
        void update("/logo", { method: "PUT", body: file, headers: { "Content-Type": file.type } });
      }} /></label>
      <p className="hint">Até 1 MB; largura de 16 a 2048 px e altura de 16 a 1024 px. Utilize somente marcas cujo uso esteja autorizado.</p>
      {identity.logo && <button className="button" disabled={busy} onClick={() => void update("/logo", { method: "DELETE" })}>Remover logotipo</button>}
      </section>
      <div className="company-preview"><span className="eyebrow">PRÉVIA DA IDENTIFICAÇÃO</span>
      <CompanyMark identity={identity} />
      {!identity.company_name && <p className="hint">ThermoPower Monitor · Identidade neutra</p>}</div>
      <p className="hint">A inclusão no portal exige autorização em cada compartilhamento. CSV e XLSX mantêm sua estrutura. Sem empresa configurada, a apresentação permanece neutra.</p>
      {message && <p role="status">{message}</p>}
    </Panel>
  </>;
}
