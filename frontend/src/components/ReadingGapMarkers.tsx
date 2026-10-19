import { ReferenceLine } from "recharts";
import type { ChartGap } from "../utils/chartPresentation";

export function ReadingGapMarkers({ gaps, axisTime }: { gaps: ChartGap[]; axisTime: (timestamp: string) => number }) {
  // Bound visual clutter. The complete gap metadata and curve breaks remain available.
  return <>{gaps.filter(gap => !gap.keys).slice(0, 12).flatMap((gap, index) => [
    <ReferenceLine key={`${index}-loss`} yAxisId={gap.source === "electrical" ? "power" : "temperature"} x={axisTime(gap.after)} stroke="#64748b" strokeOpacity={0.45} strokeDasharray="2 6" label={{ value: `Lacuna ${gap.source === "electrical" ? "elétrica" : "térmica"}`, position: "insideTopLeft", fontSize: 9 }} />,
    <ReferenceLine key={`${index}-return`} yAxisId={gap.source === "electrical" ? "power" : "temperature"} x={axisTime(gap.before)} stroke="#64748b" strokeOpacity={0.45} strokeDasharray="2 6" label={{ value: "Retorno de leituras", position: "insideBottomRight", fontSize: 9 }} />,
  ])}</>;
}
