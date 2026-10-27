import { parseUtcTimestamp, type TimeAxisMode } from "./chartPresentation";

export type AvailabilityInterval = {
  start: string; confirmed_until: string; end: string | null;
  end_reason: string | null; source: "electrical"; evidence: "backend_observed_v1";
};

export type VisualSegment = { points: { x: number; y: number }[]; start: string; end: string };

// This is an overlay only. These points never enter chart rows, statistics or exports of samples.
export function availabilitySegments(intervals: AvailabilityInterval[], rows: Record<string, unknown>[],
  key: string, axis: (timestamp: string) => number, minimum = -Infinity, maximum = Infinity): VisualSegment[] {
  const samples = rows.filter(row => typeof row[key] === "number" && Number.isFinite(row[key]))
    .sort((a, b) => Number(a.axisValue) - Number(b.axisValue));
  return intervals.flatMap(interval => {
    if (interval.evidence !== "backend_observed_v1" || interval.source !== "electrical") return [];
    const start = axis(interval.start);
    const until = axis(interval.confirmed_until);
    const end = interval.end ? axis(interval.end) : until;
    if (![start, until, end].every(Number.isFinite) || end < start || until < start) return [];
    const finish = Math.min(end, until);
    if (finish < minimum || start > maximum) return [];
    const left = Math.max(start, minimum), right = Math.min(finish, maximum);
    const previous = samples.filter(row => Number(row.axisValue) <= start).at(-1);
    const resumed = interval.end_reason === "reading_resumed"
      ? samples.find(row => Number(row.axisValue) >= end) : undefined;
    const points = [{ x: left, y: 0 }, { x: right, y: 0 }];
    if (previous && Number(previous.axisValue) >= minimum && start >= minimum) {
      points.unshift({ x: Number(previous.axisValue), y: Number(previous[key]) });
    }
    // Only link to the recorded first valid recovery sample, never to an arbitrary later sample.
    if (resumed && Math.abs(Number(resumed.axisValue) - end) < 0.001 && end <= maximum) {
      points.push({ x: end, y: Number(resumed[key]) });
    }
    return [{ points, start: interval.start, end: interval.end ?? interval.confirmed_until }];
  });
}

export function availabilityAxis(mode: TimeAxisMode, origin: string) {
  return (timestamp: string) => mode === "real" ? parseUtcTimestamp(timestamp)
    : (parseUtcTimestamp(timestamp) - parseUtcTimestamp(origin)) / 1000;
}

export function availabilityDomain(rows: Record<string, unknown>[], segments: VisualSegment[]): [number, number] {
  const values = [...rows.map(row => Number(row.axisValue)), ...segments.flatMap(segment => segment.points.map(point => point.x))].filter(Number.isFinite);
  const min = values.length ? Math.min(...values) : 0;
  return [min, values.length ? Math.max(min + 0.001, ...values) : 1];
}

export function availabilityBreaks(rows: Record<string, unknown>[], intervals: AvailabilityInterval[], key: string, axis: (timestamp: string) => number) {
  const breaks = intervals.filter(item => item.evidence === "backend_observed_v1" && axis(item.confirmed_until) > axis(item.start))
    .map(item => ({ axisValue: (axis(item.start) + axis(item.confirmed_until)) / 2, [key]: null }));
  return [...rows, ...breaks].sort((a, b) => Number(a.axisValue) - Number(b.axisValue));
}
