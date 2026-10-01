import type { RuntimeStatus } from "../types";

export function hasSourceFailure(status?: RuntimeStatus): boolean {
  return Boolean(status?.persistent_failure || status?.last_error ||
    ["error", "recovering", "reconnecting", "interrupted"].includes(status?.state ?? ""));
}

export function CadenceNotice({ status }: { status?: RuntimeStatus }) {
  if (hasSourceFailure(status)) return <div className="notice warning" role="alert"><div><strong>Falha na aquisição térmica</strong><p>{(status?.last_error ? "A fonte informou um erro. Consulte a mensagem nos detalhes da fonte." : null) || (status?.state === "recovering" || status?.state === "reconnecting" ? "Reconexão em andamento. Há interrupção nas leituras." : "Leituras interrompidas. Verifique os detalhes de aquisição.")}</p></div></div>;
  if (!status?.cadence_degraded || !status.connected) return null;
  return <details className="quality-details"><summary>Integridade · cadência térmica reduzida</summary><p>Cadência térmica reduzida · As medições continuam válidas.</p><p className="hint">A frequência observada está abaixo da esperada. Os horários e as lacunas das leituras são preservados.</p></details>;
}
