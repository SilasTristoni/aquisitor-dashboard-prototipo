import { useEffect, useState } from "react";
import { api, formatDate } from "../api";
import { Badge, Empty, ErrorNotice, PageHeader, Pagination, Panel, Spinner } from "../components/ui";
import { SupportButton } from "../components/SupportButton";
import type { PageResult } from "../types";

const categories: Record<string, string> = { APPLICATION: "Aplicação", SESSION: "Sessão", ACQUISITION: "Aquisição", SERIAL: "Comunicação", SYNCHRONIZATION: "Sincronização", REPORT: "Relatório", EXPORT: "Exportação", DATABASE: "Banco de dados", AUTH: "Acesso", connection: "Conexão", disconnection: "Desconexão", session_start: "Início de sessão", read_error: "Falha de leitura" };

type EventRow = { id: number; timestamp: string; level: string; category: string; message: string; session_id?: number; device_id?: number; details?: Record<string, unknown> };

export default function EventsPage() {
  const [filters, setFilters] = useState({ start: "", end: "", level: "", category: "", session_id: "", device_id: "", error_code: "", search: "" });
  const [result, setResult] = useState<PageResult<EventRow> | null>(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");
  useEffect(() => {
    let current = true;
    const query = new URLSearchParams({ page: String(page), page_size: "40" });
    for (const [key, value] of Object.entries(filters)) if (value) query.set(key, key === "start" || key === "end" ? new Date(value).toISOString() : value);
    api<PageResult<EventRow>>(`/events?${query}`).then((data) => { if (current) { setResult(data); setError(""); } }).catch(() => { if (current) setError("Não foi possível consultar os eventos. Atualize os filtros e tente novamente."); });
    return () => { current = false; };
  }, [page, filters]);
  function change(key: keyof typeof filters, value: string) { setPage(1); setFilters((current) => ({ ...current, [key]: value })); }
  return <><PageHeader eyebrow="RASTREABILIDADE" title="Eventos e logs" description="Consulte o ocorrido e informe o código do erro ao suporte." />
    <Panel className="filter-panel"><div className="support-filters">
      {([['start', 'Período · início', 'datetime-local'], ['end', 'Período · fim', 'datetime-local'], ['session_id', 'Sessão', 'number'], ['device_id', 'Equipamento', 'number'], ['error_code', 'Código do erro', 'text'], ['search', 'Pesquisar mensagem', 'text']] as const).map(([key, label, type]) => <label className="field" key={key}>{label}<input type={type} min={type === "number" ? 1 : undefined} value={filters[key]} onChange={(event) => change(key, event.target.value)} /></label>)}
      <label className="field">Nível<select value={filters.level} onChange={(event) => change("level", event.target.value)}><option value="">Todos os níveis</option><option value="info">Informação</option><option value="warning">Atenção</option><option value="error">Erro</option></select></label>
      <label className="field">Categoria<select value={filters.category} onChange={(event) => change("category", event.target.value)}><option value="">Todas as categorias</option>{["APPLICATION", "SESSION", "ACQUISITION", "SERIAL", "SYNCHRONIZATION", "REPORT", "EXPORT", "DATABASE", "AUTH", "connection", "disconnection", "session_start", "read_error"].map((item) => <option key={item} value={item}>{categories[item]}</option>)}</select></label>
    </div></Panel>
    {error && <ErrorNotice message={error} />}
    <Panel>{!result ? <Spinner /> : !result.items.length ? <Empty /> : <div className="support-events">{result.items.map((event) => <article key={event.id}>
      <div><time>{formatDate(event.timestamp)}</time> <Badge tone={event.level === "error" ? "danger" : event.level === "warning" ? "warning" : "neutral"}>{event.category}</Badge></div>
      <strong>{event.message}</strong><p>{event.session_id ? `Sessão #${event.session_id} · ` : ""}{event.device_id ? `Equipamento #${event.device_id}` : "Sistema"}</p>
      {typeof event.details?.correlation_id === "string" && <p>Código: {event.details.correlation_id}</p>}
      {event.details && <details><summary>Mostrar detalhes técnicos</summary><pre>{JSON.stringify(event.details, null, 2)}</pre></details>}
      {event.level === "error" && <SupportButton sessionId={event.session_id} code={typeof event.details?.correlation_id === "string" ? event.details.correlation_id : undefined} />}
    </article>)}</div>}{result && <Pagination page={result.page} pages={result.pages} total={result.total} onChange={setPage} />}</Panel>
  </>;
}
