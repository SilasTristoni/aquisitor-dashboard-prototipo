import { useState } from "react";
import { download } from "../api";

export function SupportButton({ sessionId, code, label = "Exportar diagnóstico" }: {
  sessionId?: number; code?: string; label?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function exportPackage() {
    setBusy(true); setError("");
    const query = new URLSearchParams();
    if (sessionId) query.set("session_id", String(sessionId));
    if (code) query.set("correlation_id", code);
    try {
      await download(`/support/package?${query}`, `ThermoPower-Diagnostico-${new Date().toISOString().replace(/[:.]/g, "-")}.zip`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Não foi possível gerar o diagnóstico. Tente novamente.");
    } finally { setBusy(false); }
  }
  return <div><button className="button secondary" disabled={busy} onClick={() => void exportPackage()}>{busy ? "Preparando diagnóstico…" : label}</button>{error && <p role="alert">{error}</p>}</div>;
}
