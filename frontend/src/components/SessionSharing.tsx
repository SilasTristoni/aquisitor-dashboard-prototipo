import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, formatDate } from "../api";
import { Badge, Empty, ErrorNotice, Pagination, Panel } from "./ui";
import { PortalConfiguration, type PortalStatus } from "./PortalConfiguration";

export function SessionSharing({ sessionId, channels, includePower = true, includeOpen = false }: { sessionId: number; channels?: number[]; includePower?: boolean; includeOpen?: boolean }) {
  const disclosure = useRef<HTMLDetailsElement>(null);
  const [createdId, setCreatedId] = useState<number | null>(null);
  const [result, setResult] = useState<any>(null);
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [links, setLinks] = useState<Record<number, string>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [portal, setPortal] = useState<PortalStatus | null>(null);
  const [destination, setDestination] = useState("portal");
  const publicationId = useRef(crypto.randomUUID());
  useEffect(() => { api<any>(`/sessions/${sessionId}/shares?page=${page}`).then((next) => { setResult(next); setLinks(Object.fromEntries(next.items.filter((item: any) => item.path).map((item: any) => [item.id, item.public_url || `${item.portal_origin || window.location.origin}${item.path}`]))); }).catch((reason) => setError(reason.message)); }, [sessionId, page, revision]);
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const values = new FormData(form);
    setBusy(true); setError(""); setMessage("");
    try {
      const created = await api<any>(`/sessions/${sessionId}/shares`, { method: "POST", signal: AbortSignal.timeout(60000), body: JSON.stringify({ publication_id: publicationId.current, channels: channels ?? null, include_power: includePower, include_open_channels: includeOpen, destination: values.get("destination"), password: values.get("password") || null, expires_in_days: Number(values.get("expiry")) || null, permissions: Object.fromEntries(["graphs", "pdf", "xlsx", "csv"].map((key) => [key, values.has(key)])) }) });
      setLinks((current) => ({ ...current, [created.id]: created.public_url || `${created.portal_origin || window.location.origin}${created.path}` }));
      publicationId.current = crypto.randomUUID();
      setCreatedId(created.id); if (disclosure.current) disclosure.current.open = false; setPage(1); setRevision((value) => value + 1); form.reset(); setMessage("Link criado. Use Copiar link para compartilhar o resultado.");
    } catch (reason) { setError((reason as Error).message); setRevision(value => value + 1); } finally { setBusy(false); }
  }
  async function revoke(id: number) {
    setBusy(true); setError("");
    try { await api(`/sessions/${sessionId}/shares/${id}`, { method: "DELETE", signal: AbortSignal.timeout(35000) }); setRevision((value) => value + 1); }
    catch (reason) { setError((reason as Error).message); } finally { setBusy(false); }
  }
  async function retry(id: number) {
    setBusy(true); setError("");
    try { await api(`/sessions/${sessionId}/shares/${id}/retry`, { method: "POST", signal: AbortSignal.timeout(35000) }); publicationId.current = crypto.randomUUID(); setMessage("Publicação confirmada. O link está disponível para copiar."); }
    catch (reason) { setError((reason as Error).message); } finally { setRevision(value => value + 1); setBusy(false); }
  }
  async function permissions(event: FormEvent<HTMLFormElement>, item: any) {
    event.preventDefault(); const values = new FormData(event.currentTarget);
    const desired = item.permission_update_pending?.permissions || Object.fromEntries(["graphs", "pdf", "xlsx", "csv"].map(key => [key, values.has(key)]));
    setBusy(true); setError("");
    try { await api(`/sessions/${sessionId}/shares/${item.id}/permissions`, { method: "PATCH", signal: AbortSignal.timeout(35000), body: JSON.stringify(desired) }); setMessage("Permissões sincronizadas."); }
    catch (reason) { setError((reason as Error).message); } finally { setRevision(value => value + 1); setBusy(false); }
  }
  async function copy(link: string) {
    try { await navigator.clipboard.writeText(link); setMessage("Link copiado."); }
    catch { setMessage("Selecione o campo do link e copie com Ctrl+C."); }
  }
  return <Panel title="Compartilhamentos" kicker="ACESSO AO RESULTADO">
    {error && <ErrorNotice message={error} />}{message && <p className="feedback-message" role="status">{message}</p>}
    <PortalConfiguration onStatus={setPortal} />
    <details ref={disclosure} className="disclosure-card"><summary className="button secondary">Compartilhar resultado</summary>
      <form className="compact-form" onSubmit={(event) => void create(event)}>
        <p className="hint">Compartilhe os canais selecionados e o período oficial salvo. O portal exige sessão finalizada e publica uma cópia independente dos resultados. Escolha o prazo e os arquivos disponíveis.</p>
        <div className="form-grid"><label className="field"><span>Destino do resultado</span><select name="destination" value={destination} onChange={event => setDestination(event.target.value)}><option value="local">Nesta instalação</option><option value="portal">Portal externo</option></select></label>
          <label className="field"><span>Senha opcional</span><input name="password" type="password" autoComplete="new-password" maxLength={72} placeholder="Sem senha" /></label>
          <label className="field"><span>Expiração</span><select name="expiry" defaultValue="7"><option value="1">24 h</option><option value="7">7 dias</option><option value="30">30 dias</option><option value="0">Sem expiração</option></select></label>
        </div>
        <fieldset className="control-group"><legend>Permissões do link</legend><div className="choice-row">{[["graphs", "Visualizar gráficos"], ["pdf", "PDF"], ["xlsx", "XLSX"], ["csv", "CSV"]].map(([key, label]) => <label className="choice-control" key={key}><input type="checkbox" name={key} defaultChecked={key === "graphs"} />{label}</label>)}</div></fieldset>
        <div className="action-bar"><button className="button primary" disabled={busy || (destination === "portal" && !portal?.configured)}>{destination === "portal" ? "Publicar e gerar link" : "Gerar link local"}</button><button type="button" className="button ghost" onClick={() => { if (disclosure.current) disclosure.current.open = false; }}>Cancelar</button></div>
      </form>
    </details>
    <div className="share-list">{result?.items.map((item: any) => <article className={`share-card ${createdId === item.id ? "highlighted" : ""}`} key={item.id}>
      <div className="section-heading"><strong>{createdId === item.id ? "Link criado" : "Link de consulta"}</strong><Badge tone={item.status === "active" ? "success" : "neutral"}>{{ active: "Ativo", expired: "Expirado", revoked: "Revogado", pending: "Publicação não confirmada" }[item.status as string]}</Badge>{item.has_password && <Badge>Com senha</Badge>}</div>
      <dl className="metadata-grid"><div><dt>Expiração</dt><dd>{item.expires_at ? formatDate(item.expires_at) : "Sem expiração"}</dd></div><div><dt>Acessos</dt><dd>{item.portal_origin ? "Registrados no portal" : item.access_count}</dd></div><div><dt>Último acesso</dt><dd>{formatDate(item.last_accessed_at)}</dd></div><div><dt>Criado por</dt><dd>{item.creator_name} · {formatDate(item.created_at)}</dd></div></dl>
      {(item.status === "active" || item.status === "pending") && <div className="action-bar share-link">{links[item.id] ? <><input aria-label="Link compartilhável" readOnly value={links[item.id]} onFocus={(event) => event.target.select()} /><button className="button secondary small" onClick={() => void copy(links[item.id])}>Copiar link</button></> : <p className="hint">Publicação sem confirmação. Reenvie a mesma cópia autorizada ou revogue o acesso.</p>}{item.status === "pending" && item.can_retry && <button className="button secondary small" disabled={busy} onClick={() => void retry(item.id)}>Reenviar publicação</button>}<button className="button danger-outline small" disabled={busy} onClick={() => void revoke(item.id)}>Revogar</button></div>}
      {item.status === "active" && item.portal_origin && <details><summary>Alterar permissões</summary><form key={`${revision}-${item.id}`} onSubmit={event => void permissions(event, item)}>
        <p className="hint">Somente permissões incluídas no snapshot original podem ser ativadas. Para acrescentar dados, publique outro resultado.</p>
        {item.permission_update_pending && <p role="alert">Alteração não confirmada. Reenvie para sincronizar. O portal pode já ter aplicado a alteração.</p>}
        <div className="choice-row">{[["graphs", "Gráficos"], ["pdf", "PDF"], ["xlsx", "XLSX"], ["csv", "CSV"]].map(([key, label]) => <label key={key}><input name={key} type="checkbox" disabled={busy || !!item.permission_update_pending || !item.allowed_permissions?.[key]} defaultChecked={(item.permission_update_pending?.permissions || item.permissions)[key]} />{label}</label>)}</div>
        <button className="button secondary small" disabled={busy}>{item.permission_update_pending ? "Reenviar alteração pendente" : "Sincronizar permissões"}</button>
      </form></details>}
    </article>)}</div>
    {result && !result.items.length && <Empty title="Nenhum compartilhamento ativo" text="Crie um link quando desejar disponibilizar este resultado." />}
    {result?.pages > 1 && <Pagination page={page} pages={result.pages} total={result.total} onChange={setPage} />}
    <p className="hint">Links desta instalação dependem deste computador. O portal exige hospedagem HTTPS configurada. Revogar no portal exige conexão; em caso de erro, tente novamente.</p>
  </Panel>;
}
