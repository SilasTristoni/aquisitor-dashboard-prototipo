import type { ReactNode } from "react";
import { formatDate } from "../api";
import { Badge, Empty } from "./ui";

export const eventKinds: Record<string, string> = { stabilization: "Estabilização", shutdown: "Desligamento", restart: "Religamento", condition_change: "Mudança de condição", note: "Observação" };
export type ResultEvent = { timestamp: string; title: string; description?: string | null; kind?: string; creator_name?: string };

export function ResultEvents({ items, actions }: { items: ResultEvent[]; actions?: (index: number) => ReactNode }) {
  if (!items.length) return <Empty title="Nenhum evento registrado" text="Os eventos ajudam a contextualizar o resultado do ensaio." />;
  return <ol className="result-events">{items.map((item, index) => <li key={`${item.timestamp}-${index}`}>
    <div className="event-time"><time>{formatDate(item.timestamp)}</time><Badge>{eventKinds[item.kind ?? "note"] ?? "Observação"}</Badge></div>
    <div className="event-description"><strong>{item.title}</strong>{item.description && <p>{item.description}</p>}{item.creator_name && <small>Registrado por {item.creator_name}</small>}</div>
    {actions && <div className="action-bar">{actions(index)}</div>}
  </li>)}</ol>;
}

export function groupChartEvents(events: ResultEvent[], axisTime: (timestamp: string) => number, span: number) {
  const groups: { x: number; events: ResultEvent[] }[] = [];
  [...events].sort((a, b) => axisTime(a.timestamp) - axisTime(b.timestamp)).forEach((event) => {
    const x = axisTime(event.timestamp);
    const previous = groups.at(-1);
    if (previous && x - previous.x <= span * 0.035) previous.events.push(event);
    else groups.push({ x, events: [event] });
  });
  return groups;
}

export function EventMarkerLabel({ viewBox, events, index }: { viewBox?: { x?: number; y?: number }; events: ResultEvent[]; index: number }) {
  const text = events.map((event) => `${formatDate(event.timestamp)} · ${event.title}${event.description ? ` — ${event.description}` : ""}`).join("\n");
  return <g className="event-marker" transform={`translate(${viewBox?.x ?? 0},${(viewBox?.y ?? 0) + 14})`} tabIndex={0} role="img" aria-label={text}>
    <title>{text}</title><rect x={-14} y={-11} width={28} height={22} rx={6} /><text textAnchor="middle" dy=".35em">{events.length > 1 ? `+${events.length}` : `E${index + 1}`}</text>
  </g>;
}
