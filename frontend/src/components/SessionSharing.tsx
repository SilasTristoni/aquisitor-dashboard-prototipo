import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, formatDate } from "../api";
import { Badge, Empty, ErrorNotice, Pagination, Panel } from "./ui";

export function SessionSharing({ sessionId }: { sessionId: number }) {
  const disclosure = useRef<HTMLDetailsElement>(null);
  const [createdId, setCreatedId] = useState<number | null>(null);
  const [result, setResult] = useState<any>(null);
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [links, setLinks] = useState<Record<number, string>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => { api<any>(`/sessions/${sessionId}/shares?page=${page}`).then((next) => { setResult(next); setLinks((current) => ({ ...current, ...Object.fromEntries(next.items.filter((item: any) => item.path).map((item: any) => [item.id, `${window.location.origin}${item.path}`])) })); }).catch((reason) => setError(reason.message)); }, [sessionId, page, revision]);
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const values = new FormData(form);
    setBusy(true); setError(""); setMessage("");
    try {
      const created = await api<any>(`/sessions/${sessionId}/shares`, { method: "POST", body: JSON.stringify({ password: values.get("password") || null, expires_in_days: Number(values.get("expiry")) || null, permissions: Object.fromEntries(["graphs", "pdf", "xlsx", "csv"].map((key) => [key, values.has(key)])) }) });
      setLinks((current) => ({ ...current, [created.id]: `${window.location.origin}${created.path}` }));
      setCreatedId(created.id); if (disclosure.current) disclosure.current.open = false; setPage(1); setRevision((value) => value + 1); form.reset(); setMessage("Link criado. Use Copiar link para compartilhar o resultado.");
    } catch (reason) { setError((reason as Error).message); } finally { setBusy(false); }
  }
  async function revoke(id: number) {
    setBusy(true); setError("");
    try { await api(`/sessions/${sessionId}/shares/${id}`, { method: "DELETE" }); setRevision((value) => value + 1); }
    catch (reason) { setError((reason as Error).message); } finally { setBusy(false); }
  }
  async function copy(link: string) {
    try { await navigator.clipboard.writeText(link); setMessage("Link copiado."); }
    catch { setMessage("Selecione o campo do link e copie com Ctrl+C."); }
  }
  return <Panel title="Compartilhamentos" kicker="ACESSO AO RESULTADO">
    {error && <ErrorNotice message={error} />}{message && <p className="feedback-message" role="status">{message}</p>}
    <details ref={disclosure} className="disclosure-card"><summary className="button secondary">Compartilhar resultado</summary>
      <form className="compact-form" onSubmit={(event) => void create(event)}>
        <p className="hint">Crie um acesso de consulta a este ensaio. Escolha o prazo e os arquivos disponíveis.</p>
        <div className="form-grid">
          <label className="field"><span>Senha opcional</span><input name="password" type="password" autoComplete="new-password" maxLength={72} placeholder="Sem senha" /></label>
          <label className="field"><span>Expiração</span><select name="expiry" defaultValue="7"><option value="1">24 h</option><option value="7">7 dias</option><option value="30">30 dias</option><option value="0">Sem expiração</option></select></label>
        </div>
        <fieldset className="control-group"><legend>Permissões do link</legend><div className="choice-row">{[["graphs", "Visualizar gráficos"], ["pdf", "PDF"], ["xlsx", "XLSX"], ["csv", "CSV"]].map(([key, label]) => <label className="choice-control" key={key}><input type="checkbox" name={key} defaultChecked={key === "graphs"} />{label}</label>)}</div></fieldset>
        <div className="action-bar"><button className="button primary" disabled={busy}>Gerar link</button><button type="button" className="button ghost" onClick={() => { if (disclosure.current) disclosure.current.open = false; }}>Cancelar</button></div>
      </form>
    </details>
    <div className="share-list">{result?.items.map((item: any) => <article className={`share-card ${createdId === item.id ? "highlighted" : ""}`} key={item.id}>
      <div className="section-heading"><strong>{createdId === item.id ? "Link criado" : "Link de consulta"}</strong><Badge tone={item.status === "active" ? "success" : "neutral"}>{{ active: "Ativo", expired: "Expirado", revoked: "Revogado" }[item.status as string]}</Badge>{item.has_password && <Badge>Com senha</Badge>}</div>
      <dl className="metadata-grid"><div><dt>Expiração</dt><dd>{item.expires_at ? formatDate(item.expires_at) : "Sem expiração"}</dd></div><div><dt>Acessos</dt><dd>{item.access_count}</dd></div><div><dt>Último acesso</dt><dd>{formatDate(item.last_accessed_at)}</dd></div><div><dt>Criado por</dt><dd>{item.creator_name} · {formatDate(item.created_at)}</dd></div></dl>
      {item.status === "active" && <div className="action-bar share-link">{links[item.id] ? <><input aria-label="Link compartilhável" readOnly value={links[item.id]} onFocus={(event) => event.target.select()} /><button className="button secondary small" onClick={() => void copy(links[item.id])}>Copiar link</button></> : <p className="hint">Este link não pode ser recuperado. Crie outro acesso.</p>}<button className="button danger-outline small" disabled={busy} onClick={() => void revoke(item.id)}>Revogar</button></div>}
    </article>)}</div>
    {result && !result.items.length && <Empty title="Nenhum compartilhamento ativo" text="Crie um link quando desejar disponibilizar este resultado." />}
    {result?.pages > 1 && <Pagination page={page} pages={result.pages} total={result.total} onChange={setPage} />}
    <p className="hint">Em localhost, o link abre neste computador. Para compartilhar na rede, acesse o ThermoPower pelo endereço do servidor.</p>
  </Panel>;
}
