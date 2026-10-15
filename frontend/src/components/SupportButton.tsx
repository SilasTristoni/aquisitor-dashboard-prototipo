import { useEffect, useRef, useState } from "react";
import { download } from "../api";

export function SupportButton({ sessionId, code, physical = false, label = "Exportar diagnóstico" }: {
  sessionId?: number; code?: string; physical?: boolean; label?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);
  async function exportPackage() {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true); setError("");
    const query = new URLSearchParams();
    if (sessionId) query.set("session_id", String(sessionId));
    if (code) query.set("correlation_id", code);
    const timer = window.setTimeout(() => controller.abort(new Error("O diagnóstico excedeu 20 segundos. Tente novamente ou utilize a coleta local.")), 20_000);
    const cancelled = new Promise<never>((_, reject) => {
      controller.signal.addEventListener("abort", () => reject(controller.signal.reason), { once: true });
    });
    try {
      await Promise.race([cancelled, download(`/support/${physical ? "physical-package" : "package"}?${query}`, `ThermoPower-Diagnostico-${new Date().toISOString().replace(/[:.]/g, "-")}.zip`, { signal: controller.signal, maxBytes: 24 * 1024 * 1024 })]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Não foi possível gerar o diagnóstico. Tente novamente.");
    } finally { window.clearTimeout(timer); active.current = null; setBusy(false); }
  }
  return <div><button className="button secondary" disabled={busy} onClick={() => void exportPackage()}>{busy ? "Preparando diagnóstico…" : label}</button>{error && <div role="alert"><p>{error}</p><p>Coleta alternativa no computador do ThermoPower: execute <code>scripts/export-local-diagnostic.ps1</code> conforme o guia de diagnóstico local. A coleta não inicia aquisição nem acessa equipamentos.</p></div>}</div>;
}
