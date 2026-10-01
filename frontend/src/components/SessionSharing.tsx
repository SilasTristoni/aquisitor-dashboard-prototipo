import { useEffect, useState, type FormEvent } from "react";
import { api, formatDate } from "../api";
import { ErrorNotice, Pagination, Panel } from "./ui";

export function SessionSharing({ sessionId }: { sessionId: number }) {
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
      setPage(1); setRevision((value) => value + 1); form.reset(); setMessage("Link criado. Use Copiar link para compartilhar o resultado.");
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
  return <Panel title="Compartilhar resultado" kicker="SOMENTE LEITURA">
    {error && <ErrorNotice message={error} />}{message && <p role="status">{message}</p>}
    <p className="hint">O destinatário acessa somente este ensaio. Em instalação local (127.0.0.1), o link funciona apenas neste computador. Para outros computadores, use o endereço acessível do servidor na rede.</p>
    <details><summary>Criar novo compartilhamento</summary><form className="form-grid" onSubmit={(event) => void create(event)}>
      <label className="field"><span>Senha opcional</span><input name="password" type="password" autoComplete="new-password" maxLength={72} /></label>
      <label className="field"><span>Expiração</span><select name="expiry" defaultValue="7"><option value="1">24 h</option><option value="7">7 dias</option><option value="30">30 dias</option><option value="0">Sem expiração</option></select></label>
      <fieldset><legend>Permissões do link</legend>{[["graphs", "Visualizar gráficos"], ["pdf", "Baixar PDF"], ["xlsx", "Baixar XLSX"], ["csv", "Baixar CSV"]].map(([key, label]) => <label key={key}><input type="checkbox" name={key} defaultChecked={key === "graphs"} /> {label} </label>)}</fieldset>
      <button className="button primary" disabled={busy}>Gerar link</button>
    </form></details>
    <div className="table-scroll"><table><thead><tr><th>Criado por</th><th>Criação</th><th>Expiração</th><th>Último acesso</th><th>Acessos</th><th>Status</th><th>Ações</th></tr></thead><tbody>{result?.items.map((item: any) => <tr key={item.id}><td>{item.creator_name}</td><td>{formatDate(item.created_at)}</td><td>{item.expires_at ? formatDate(item.expires_at) : "Sem expiração"}</td><td>{formatDate(item.last_accessed_at)}</td><td>{item.access_count}</td><td>{{ active: "Ativo", expired: "Expirado", revoked: "Revogado" }[item.status as string]}{item.has_password && " · Com senha"}</td><td>{item.status === "active" && <>{links[item.id] ? <><input aria-label="Link compartilhável" readOnly value={links[item.id]} onFocus={(event) => event.target.select()} /><button className="button ghost small" onClick={() => void copy(links[item.id])}>Copiar link</button></> : <small>Chave do servidor alterada. Crie outro link.</small>}<button className="button ghost small" disabled={busy} onClick={() => void revoke(item.id)}>Revogar</button></>}</td></tr>)}</tbody></table></div>
    {result?.pages > 1 && <Pagination page={page} pages={result.pages} total={result.total} onChange={setPage} />}
    <p className="hint">Os links podem ser copiados enquanto estiverem ativos. A senha nunca é exibida novamente.</p>
  </Panel>;
}
