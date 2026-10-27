import { useEffect, useState } from "react";
import { api } from "../api";
import type { AvailabilityInterval } from "../utils/availability";

export function useAvailability(sessionId?: number, frozen = false) {
  const [state, setState] = useState<{ id?: number; intervals: AvailabilityInterval[] }>({ intervals: [] });
  useEffect(() => {
    if (!sessionId || frozen) return;
    let active = true;
    const refresh = () => api<{ items: AvailabilityInterval[] }>(`/sessions/${sessionId}/availability?page_size=100`)
      .then(result => { if (active) setState({ id: sessionId, intervals: result.items ?? [] }); })
      .catch(() => { /* Keep only previously confirmed boundaries; never extend on request failure. */ });
    void refresh();
    const timer = window.setInterval(() => void refresh(), 1000);
    return () => { active = false; window.clearInterval(timer); };
  }, [sessionId, frozen]);
  return state.id === sessionId ? state.intervals : [];
}
