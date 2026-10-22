import type { Reading, RuntimeStatus } from "../types";
import { parseUtcTimestamp } from "./chartPresentation";

export type SourceEvent = { at: number; kind: "disconnected" | "reconnected" | "paused" | "resumed"; lastValue: number | null; lastReadingAt: number };
export type SourceHistory = { events: SourceEvent[]; unavailable: boolean; paused: boolean };
export const emptySourceHistory = (): SourceHistory => ({ events: [], unavailable: false, paused: false });

// Pure presentation reducer: it never constructs Reading objects or writes to the API.
export function observeSource(previous: SourceHistory, status: RuntimeStatus | undefined, reading: Reading | undefined, paused: boolean, observedAt: number): SourceHistory {
  if (!status || !reading) return previous;
  const lastReadingAt = parseUtcTimestamp(reading.received_timestamp ?? reading.timestamp);
  if (!Number.isFinite(lastReadingAt)) return previous;
  const confirmed = status.connected === false || status.persistent_failure === true || status.state === "recovering";
  const events = [...previous.events];
  const append = (kind: SourceEvent["kind"], at: number) => events.push({ kind, at, lastValue: reading.power_w ?? null, lastReadingAt });
  if (paused !== previous.paused) append(paused ? "paused" : "resumed", observedAt);
  let unavailable = previous.unavailable;
  if (!paused && confirmed && !unavailable) {
    append("disconnected", Math.max(observedAt, lastReadingAt)); unavailable = true;
  } else if (!paused && !confirmed && unavailable && status.connected && status.reading !== false) {
    const lost = [...events].reverse().find(event => event.kind === "disconnected");
    if (lost && lastReadingAt > lost.at) { append("reconnected", lastReadingAt); unavailable = false; }
  }
  if (events.length === previous.events.length && paused === previous.paused) return previous;
  return { events: events.slice(-200), unavailable, paused };
}

export function visualPowerTransitions(events: SourceEvent[], now: number, axis: (time: number) => number) {
  return events.flatMap((event, index) => {
    if (event.kind !== "disconnected" || event.lastValue == null) return [];
    const end = events.slice(index + 1).find(item => item.kind === "reconnected" || item.kind === "paused")?.at ?? now;
    return [{ axisValue: axis(event.at), visualPower: event.lastValue },
      { axisValue: axis(event.at), visualPower: 0 },
      { axisValue: axis(Math.max(event.at, end)), visualPower: 0 },
      { axisValue: axis(Math.max(event.at, end)), visualPower: null }];
  });
}

export function splitAtSourceEvents<T extends Record<string, unknown>>(rows: T[], events: SourceEvent[], axis: (time: number) => number): T[][] {
  const boundaries = events.filter(event => event.kind === "disconnected" || event.kind === "paused").map(event => axis(event.at));
  const segments: T[][] = [];
  for (const row of rows) {
    const index = boundaries.filter(boundary => Number(row.axisValue) >= boundary).length;
    (segments[index] ??= []).push(row);
  }
  return segments.filter(Boolean);
}
