import { useEffect, useState } from "react";
import type { Reading, RuntimeStatus } from "../types";
import { emptySourceHistory, observeSource } from "../utils/sourceEvents";

export function useSourceHistory(key: string, status: RuntimeStatus | undefined, reading: Reading | undefined, paused: boolean, now: number, frozen: boolean) {
  const [state, setState] = useState(() => ({ key, history: emptySourceHistory() }));
  useEffect(() => {
    if (frozen) return;
    setState(previous => {
      const initial = previous.key === key ? previous.history : emptySourceHistory();
      const history = observeSource(initial, status, reading, paused, now);
      return previous.key === key && history === previous.history ? previous : { key, history };
    });
  }, [key, status, reading, paused, now, frozen]);
  return state.key === key ? state.history : emptySourceHistory();
}
