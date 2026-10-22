import type { Reading, RuntimeStatus } from "../types";
import { parseUtcTimestamp } from "./chartPresentation";

export function sourcePresentation(status: RuntimeStatus | undefined, reading: Reading | undefined, paused: boolean, now: number) {
  const lastValidAt = reading?.received_timestamp ?? reading?.timestamp;
  const age = lastValidAt ? now - parseUtcTimestamp(lastValidAt) : Infinity;
  const recent = age >= -1000 && age <= Math.max(10000, (status?.expected_interval_ms ?? 1000) * 3);
  const failed = Boolean(status?.persistent_failure || status?.last_error || ["error", "recovering", "degraded"].includes(status?.state ?? ""));
  const state = paused ? "Sessão pausada" : !status?.connected ? "Fonte desconectada" : failed ? "Comunicação indisponível" : !lastValidAt ? "Sem dados" : !recent ? "Sem leitura recente" : "Leitura recente";
  return { state, lastValidAt, recent, current: !paused && !failed && Boolean(status?.connected) && recent };
}
