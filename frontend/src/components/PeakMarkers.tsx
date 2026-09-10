import { ReferenceDot } from "recharts";
import { POWER_COLOR, seriesPeak } from "../utils/chartPresentation";

export function PeakMarkers({ rows, powerKey, channels }: {
  rows: Array<Record<string, unknown>>; powerKey: string; channels: string[];
}) {
  const power = seriesPeak(rows, [powerKey]);
  const thermal = seriesPeak(rows, channels);
  return <>
    {power && <ReferenceDot yAxisId="power" x={power.axisValue} y={power.value} r={4} fill={POWER_COLOR} label={{ value: "Pico de potência", position: "insideTopLeft", fontSize: 10 }} />}
    {thermal && <ReferenceDot yAxisId="temperature" x={thermal.axisValue} y={thermal.value} r={4} fill="#D97706" label={{ value: `Máx. T${thermal.key.replace(/\D/g, "")}`, position: "insideTopRight", fontSize: 10 }} />}
  </>;
}
