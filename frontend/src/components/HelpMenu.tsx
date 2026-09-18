import { useState } from "react";
import { api, download, formatDate } from "../api";
import { SupportButton } from "./SupportButton";

type BuildInfo = { version: string; build: string; environment: string; build_date: string | null };

export function HelpMenu() {
  const [about, setAbout] = useState<BuildInfo | null>(null);
  const [error, setError] = useState("");
  async function guide() {
    try { await download("/help/user-guide", "Manual do Usuário - ThermoPower Monitor.pdf"); }
    catch { setError("Não foi possível abrir o guia. Tente novamente ou consulte o suporte."); }
  }
  async function showAbout() {
    try { setAbout(await api<BuildInfo>("/build-info")); }
    catch { setError("Não foi possível consultar a versão. Tente novamente."); }
  }
  return <>
    <details className="help-menu"><summary className="button ghost">Ajuda</summary><div className="help-menu-content">
      <button className="button ghost" onClick={() => void guide()}>Guia do usuário</button>
      <button className="button ghost" onClick={() => void showAbout()}>Sobre o ThermoPower</button>
      <SupportButton />
      {error && <p role="alert">{error}</p>}
    </div></details>
    {about && <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="about-title"><h2 id="about-title">Sobre o ThermoPower</h2>
      <p>Versão: {about.version}</p><p>Build: {about.build}</p><p>Ambiente: {about.environment}</p><p>Data da build: {formatDate(about.build_date)}</p>
      <button autoFocus className="button secondary" onClick={() => setAbout(null)}>Fechar</button>
    </section></div>}
  </>;
}

export function FirstUseHint() {
  const [visible, setVisible] = useState(() => localStorage.getItem("thermopower.guide.dismissed") !== "true");
  if (!visible) return null;
  return <aside className="notice first-use-hint"><div><strong>Seu ensaio em quatro passos</strong><p>1. Conecte as fontes · 2. Inicie o ensaio · 3. Acompanhe os dados · 4. Finalize e gere o relatório</p><small>O guia completo está no menu Ajuda.</small></div><button className="button ghost" onClick={() => { localStorage.setItem("thermopower.guide.dismissed", "true"); setVisible(false); }}>Entendi, não mostrar novamente</button></aside>;
}
