import { ReferenceLine } from "recharts";
import type { ChartGap } from "../utils/chartPresentation";
import { formatDate } from "../api";

export function ReadingGapMarkers({ gaps, axisTime }: { gaps: ChartGap[]; axisTime: (timestamp: string) => number }) {
  // Bound visual clutter. The complete gap metadata and curve breaks remain available.
  return <>{gaps.filter(gap => !gap.keys).slice(0, 12).flatMap((gap, index) => [
    <ReferenceLine key={`${index}-loss`} yAxisId={gap.source === "electrical" ? "power" : "temperature"} x={axisTime(gap.after)} stroke="#64748b" strokeOpacity={0.25} strokeDasharray="2 6" />,
    <ReferenceLine key={`${index}-return`} yAxisId={gap.source === "electrical" ? "power" : "temperature"} x={axisTime(gap.before)} stroke="#64748b" strokeOpacity={0.25} strokeDasharray="2 6" />,
  ])}</>;
}

export function ReadingGapDetails({ gaps }: { gaps: ChartGap[] }) {
  if (!gaps.length) return null;
  return <details className="chart-gap-details"><summary>{gaps.length} lacunas de leitura — ver intervalos</summary>
    <p className="hint">Ausência de dados não comprova desconexão. Os intervalos delimitam leituras, não o instante da falha. Nenhum zero foi acrescentado.</p>
    <ol>{gaps.map((gap, index) => <li key={index}>{gap.source === "electrical" ? "Potência" : "Temperatura"}{gap.keys ? ` (${gap.keys.join(", ")})` : ""}: {formatDate(gap.after)} até {formatDate(gap.before)}</li>)}</ol>
  </details>;
}
