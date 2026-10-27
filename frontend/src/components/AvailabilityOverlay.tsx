import { ReferenceLine } from "recharts";
import { formatDate } from "../api";
import type { AvailabilityInterval, VisualSegment } from "../utils/availability";

export function AvailabilityOverlay({ segments, hidden = false }: { segments: VisualSegment[]; hidden?: boolean }) {
  if (hidden) return null;
  return <>{segments.flatMap((segment, index) => segment.points.slice(1).map((point, part) =>
    <ReferenceLine key={`${index}-${part}`} className="availability-reference" yAxisId="power"
      segment={[segment.points[part], point]} stroke="#64748b" strokeWidth={2.5} strokeDasharray="6 4" />))}</>;
}

export function AvailabilityDetails({ intervals }: { intervals: AvailabilityInterval[] }) {
  return <div className="availability-details">
    <p className="hint">{intervals.length
      ? "Traço cinza até 0 W: indisponibilidade confirmada do GPM, sem medição. O retorno liga à primeira leitura real. Não altera médias, energia, picos ou amostras exportadas."
      : "Sem intervalos confirmados de desconexão neste período. Lacunas antigas ou de origem desconhecida não são convertidas em 0 W."}</p>
    {intervals.length > 0 && <details><summary>{intervals.length} intervalos confirmados — ver detalhes</summary>
      <ol>{intervals.map((item, index) => <li key={index}>{formatDate(item.start)} até {formatDate(item.end ?? item.confirmed_until)} · {item.end_reason === "reading_resumed" ? "retorno com leitura válida" : item.end_reason === "paused" ? "referência encerrada antes da pausa" : "limitado à última confirmação observada"}</li>)}</ol>
    </details>}
  </div>;
}
