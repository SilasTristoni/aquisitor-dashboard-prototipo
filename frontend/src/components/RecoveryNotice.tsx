import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, formatDate } from "../api";
import { ErrorNotice, Pagination } from "./ui";
import "./RecoveryNotice.css";

type RecoverableSession = {
  id: number; name: string; reason: string; started_at: string;
  last_sample_at: string | null; counts: { electrical: number; thermal: number };
  devices: { id: number; name: string }[];
};
type RecoveryPage = { items: RecoverableSession[]; page: number; pages: number; total: number };
type RecoveryHealth = { supervision_ready: boolean; storage: { state: string }; write_faults: { device_id: number; message: string }[] };

export default function RecoveryNotice() {
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<RecoveryPage>();
  const [health, setHealth] = useState<RecoveryHealth>();
  const [choice, setChoice] = useState<{ session: RecoverableSession; action: "resume" | "close" }>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const refresh = useCallback(async () => {
    const [sessions, status] = await Promise.all([
      api<RecoveryPage>(`/recovery/sessions?page=${page}&page_size=5`), api<RecoveryHealth>("/recovery/health"),
    ]);
    setResult(sessions); setHealth(status); setError("");
  }, [page]);
  useEffect(() => {
    let mounted = true;
    const load = () => void refresh().catch((e: Error) => { if (mounted) setError(e.message); });
    load();
    const timer = window.setInterval(load, 15000);
    return () => { mounted = false; window.clearInterval(timer); };
  }, [refresh]);
  async function decide() {
    if (!choice) return;
    setBusy(true); setError("");
    try {
      const outcome = await api<{ unavailable_sources: unknown[] }>(`/recovery/sessions/${choice.session.id}`, {
        method: "POST", body: JSON.stringify({ action: choice.action }),
      });
      setMessage(choice.action === "close" ? "Ensaio encerrado como interrompido. Histórico preservado." :
        `Ensaio retomado com o mesmo identificador.${outcome.unavailable_sources.length ? " Uma fonte permanece indisponível; a outra continua adquirindo." : ""}`);
      setChoice(undefined); await refresh();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  const storageWarning = health && (!health.supervision_ready || ["warning", "critical", "unavailable"].includes(health.storage?.state) || health.write_faults?.length > 0);
  if (!error && !result?.total && !message && !storageWarning) return null;
  return <section className="recovery-notice" aria-label="Recuperação de ensaios">
    {error && <ErrorNotice message={error} retry={() => void refresh().catch((e: Error) => setError(e.message))} />}
    {message && <p role="status">{message} <Link to="/">Abrir tempo real</Link></p>}
    {storageWarning && <div className="notice warning" role="alert"><strong>Verifique o armazenamento</strong><p>{health?.supervision_ready ? "Espaço baixo ou gravação indisponível. Verifique o disco antes de continuar. Não encerre o aplicativo enquanto houver amostras pendentes em memória." : "Supervisão indisponível. A aquisição foi pausada; verifique o banco e reinicie a aplicação."}</p>{health?.write_faults?.map((fault) => <p key={fault.device_id}>{fault.message}</p>)}</div>}
    {!!result?.total && <details open><summary><strong>{result.total} ensaio(s) aguardando recuperação</strong></summary>
      {result.items.map((session) => <article key={session.id} className="recovery-session">
        <div><h3>{session.reason === "controlled_shutdown" ? "Ensaio suspenso ao fechar a aplicação" : "Ensaio interrompido encontrado"}</h3>
          <Link to={`/sessoes/${session.id}`}>{session.name} · #{session.id}</Link>
          <p>Início: {formatDate(session.started_at)} · Última leitura confirmada: {session.last_sample_at ? formatDate(session.last_sample_at) : "Nenhuma"}</p>
          <p>{session.counts.electrical.toLocaleString("pt-BR")} leituras elétricas e {session.counts.thermal.toLocaleString("pt-BR")} térmicas preservadas.</p>
          <p>Fontes: {session.devices.map((device) => device.name).join(" · ")}</p>
          <p>O intervalo desde a última leitura permanece sem dados confirmados. Retomar mantém o histórico e reconecta as fontes disponíveis.</p>
        </div><div className="recovery-actions"><button className="button primary" disabled={busy} onClick={() => setChoice({ session, action: "resume" })}>Retomar ensaio</button><button className="button secondary" disabled={busy} onClick={() => setChoice({ session, action: "close" })}>Encerrar como interrompido</button></div>
      </article>)}
      {result.pages > 1 && <Pagination {...result} onChange={setPage} />}
    </details>}
    {choice && <div className="notice warning" role="alertdialog" aria-label="Confirmar recuperação" aria-busy={busy}>
      <p>{choice.action === "resume" ? `Reconectar as fontes disponíveis e continuar ${choice.session.name}?` : `Encerrar definitivamente ${choice.session.name}, preservando todas as medições?`}</p>
      <div className="recovery-actions"><button className="button primary" disabled={busy} onClick={() => void decide()}>{busy ? "Processando…" : "Confirmar"}</button><button className="button ghost" disabled={busy} onClick={() => setChoice(undefined)}>Cancelar</button></div>
    </div>}
  </section>;
}
