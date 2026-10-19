import { formatDate, formatDuration } from "../api";
import "./ThermalPeak.css";

export function ThermalPeak({ peak }: { peak?: { label: string; value_c: number; timestamp: string; session_elapsed_seconds: number; period_elapsed_seconds: number } | null }) {
  return <p className="hint thermal-peak" data-testid="thermal-peak">{peak ? <><strong>Tempo até a temperatura máxima:</strong> {peak.label} · {peak.value_c.toLocaleString("pt-BR")} °C · {formatDate(peak.timestamp)} · {formatDuration(peak.session_elapsed_seconds)} desde o início da sessão · {formatDuration(peak.period_elapsed_seconds)} desde o início do período. Empates: primeira ocorrência.</> : "Sem pico térmico válido nos canais selecionados."}</p>;
}
