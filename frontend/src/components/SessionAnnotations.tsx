import { useEffect, useState, type FormEvent } from "react";
import { api, formatDate } from "../api";
import { useAuth } from "../auth";
import { ErrorNotice, Pagination, Panel } from "./ui";

export type Annotation = { id: number; timestamp: string; title: string; description?: string; kind: string; created_by: number; creator_name: string; created_at: string };
const kinds = { stabilization: "Estabilização", shutdown: "Desligamento", restart: "Religamento", condition_change: "Mudança de condição", note: "Observação livre" };
export function SessionAnnotations({ sessionId, initialTime, onChange }: { sessionId: number; initialTime: string; onChange: () => void }) {
  const { user } = useAuth();
  const [items, setItems] = useState<Annotation[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [editing, setEditing] = useState<Annotation | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => { api<any>(`/sessions/${sessionId}/annotations?page=${page}&page_size=20`).then((result) => { setItems(result.items); setTotal(result.total); }).catch((reason) => setError(reason.message)); }, [sessionId, page, revision]);
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const values = new FormData(form);
    setBusy(true); setError("");
    try {
      await api(`/sessions/${sessionId}/annotations${editing ? `/${editing.id}` : ""}`, { method: editing ? "PUT" : "POST", body: JSON.stringify({ timestamp: new Date(`${values.get("timestamp")}-03:00`).toISOString(), title: values.get("title"), description: values.get("description") || null, kind: values.get("kind") }) });
      setEditing(null); form.reset(); setRevision((value) => value + 1); onChange();
    } catch (reason) { setError((reason as Error).message); } finally { setBusy(false); }
  }
  async function remove(id: number) {
    setBusy(true);
    try { await api(`/sessions/${sessionId}/annotations/${id}`, { method: "DELETE" }); setRevision((value) => value + 1); onChange(); }
    catch (reason) { setError((reason as Error).message); } finally { setBusy(false); }
  }
  return <Panel title="Eventos do ensaio" kicker="ANOTAÇÕES MANUAIS">
    {error && <ErrorNotice message={error} />}
    {items.map((item) => <div key={item.id} className="detail-strip"><div><strong>{item.title}</strong><span>{formatDate(item.timestamp)} · {item.creator_name}</span><p>{item.description}</p></div>{user?.role !== "viewer" && (user?.role === "admin" || user?.id === item.created_by) && <div><button className="button ghost" disabled={busy} onClick={() => setEditing(item)}>Editar evento</button><button className="button ghost" disabled={busy} onClick={() => void remove(item.id)}>Remover evento</button></div>}</div>)}
    {total > 20 && <Pagination page={page} pages={Math.ceil(total / 20)} total={total} onChange={setPage} />}
    {user?.role !== "viewer" && <details open={editing ? true : undefined}><summary>{editing ? "Editar evento" : "Adicionar evento"}</summary><form key={editing?.id ?? "new"} onSubmit={(event) => void save(event)} className="form-grid">
      <label className="field"><span>Horário do evento (Brasília)</span><input name="timestamp" type="datetime-local" step="0.001" required defaultValue={editing ? new Date(new Date(editing.timestamp).getTime() - 10800000).toISOString().slice(0, 23) : initialTime} /></label>
      <label className="field"><span>Tipo de evento</span><select name="kind" defaultValue={editing?.kind ?? "note"}>{Object.entries(kinds).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label className="field"><span>Título do evento</span><input name="title" required maxLength={160} defaultValue={editing?.title} /></label>
      <label className="field"><span>Descrição do evento</span><textarea name="description" maxLength={2000} defaultValue={editing?.description} /></label>
      <button className="button secondary" disabled={busy}>Salvar evento</button>{editing && <button type="button" className="button ghost" onClick={() => setEditing(null)}>Cancelar edição</button>}
    </form></details>}
  </Panel>;
}
