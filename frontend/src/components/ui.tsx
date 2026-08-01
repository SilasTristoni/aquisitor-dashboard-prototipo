import type { ReactNode } from "react";

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description?: string; actions?: ReactNode }) {
  return <header className="page-header"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1>{description && <p className="subtitle">{description}</p>}</div>{actions && <div className="page-actions">{actions}</div>}</header>;
}

export function Panel({ title, kicker, actions, children, className = "" }: { title?: string; kicker?: string; actions?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`panel ${className}`}>{(title || actions) && <div className="panel-head"><div>{kicker && <p className="eyebrow">{kicker}</p>}{title && <h2>{title}</h2>}</div>{actions}</div>}{children}</section>;
}

export function Metric({ label, value, hint, tone = "default" }: { label: string; value: ReactNode; hint?: string; tone?: string }) {
  return <article className={`metric-card ${tone}`}><span>{label}</span><strong>{value}</strong>{hint && <small>{hint}</small>}</article>;
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: string }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

export function Empty({ title = "Nenhum registro encontrado", text }: { title?: string; text?: string }) {
  return <div className="empty"><span>◇</span><strong>{title}</strong>{text && <p>{text}</p>}</div>;
}

export function Spinner({ label = "Carregando" }: { label?: string }) {
  return <div className="spinner-wrap" role="status"><i className="spinner" /><span>{label}</span></div>;
}

export function ErrorNotice({ message, retry }: { message: string; retry?: () => void }) {
  return <div className="notice error" role="alert"><div><strong>Não foi possível concluir</strong><span>{message}</span></div>{retry && <button className="button ghost" onClick={retry}>Tentar novamente</button>}</div>;
}

export function Pagination({ page, pages, total, onChange }: { page: number; pages: number; total: number; onChange: (page: number) => void }) {
  return <div className="pagination"><span>{total.toLocaleString("pt-BR")} registros</span><div><button disabled={page <= 1} onClick={() => onChange(page - 1)}>Anterior</button><strong>{page} / {Math.max(1, pages)}</strong><button disabled={page >= pages} onClick={() => onChange(page + 1)}>Próxima</button></div></div>;
}
