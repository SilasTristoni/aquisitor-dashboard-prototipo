export type TimeAxisMode = "synchronized" | "real";

export const POWER_COLOR = "#2563EB";

export const CHANNEL_COLORS = [
  "#D97706", "#16A34A", "#DC2626", "#7C3AED", "#0891B2", "#DB2777", "#4F46E5", "#65A30D",
  "#EA580C", "#0D9488", "#9333EA", "#E11D48", "#0284C7", "#CA8A04", "#475569", "#B45309",
];

// API dates from older SQLite builds are UTC even when the suffix was omitted.
export function parseUtcTimestamp(value: string): number {
  const normalized = value.trim();
  return Date.parse(/[zZ]$|[+-]\d{2}:?\d{2}$/.test(normalized) ? normalized : `${normalized}Z`);
}

export function formatMeasureAxis(value: number): string {
  return Number(value).toLocaleString("pt-BR", { maximumFractionDigits: 1 });
}

export function paddedDomain([minimum, maximum]: [number, number]): [number, number] {
  const margin = Math.max(Math.abs(maximum) * 0.08, (maximum - minimum) * 0.08, 0.5);
  return [minimum >= 0 ? 0 : minimum - margin, maximum + margin];
}

export function seriesPeak(rows: Array<Record<string, unknown>>, keys: string[]) {
  let peak: { axisValue: number; value: number; key: string } | undefined;
  for (const row of rows) for (const key of keys) {
    const value = row[key];
    if (typeof value === "number" && Number.isFinite(value) && (!peak || value > peak.value)) {
      peak = { axisValue: Number(row.axisValue), value, key };
    }
  }
  return peak;
}

type ChartPoint = Record<string, unknown> & { timestamp: string };

export function mergeIndependentSeries(
  electrical: ChartPoint[],
  thermal: ChartPoint[],
  mode: TimeAxisMode,
  sessionStartedAt?: string,
): Array<Record<string, unknown>> {
  const sessionOrigin = sessionStartedAt ? parseUtcTimestamp(sessionStartedAt) : Number.NaN;
  const validSessionOrigin = Number.isFinite(sessionOrigin) ? sessionOrigin : Math.min(
    ...[...electrical, ...thermal].map((point) => parseUtcTimestamp(point.timestamp)).filter(Number.isFinite),
  );
  const rows = new Map<number, Record<string, unknown>>();

  function add(points: ChartPoint[], source: "electrical" | "thermal") {
    for (const point of points) {
      const originalTime = parseUtcTimestamp(point.timestamp);
      if (!Number.isFinite(originalTime)) continue;
      if (Number.isFinite(validSessionOrigin) && originalTime < validSessionOrigin) continue;
      const axisValue = mode === "synchronized"
        ? (originalTime - validSessionOrigin) / 1000
        : originalTime;
      const current = rows.get(axisValue) ?? { axisValue };
      rows.set(axisValue, {
        ...current,
        ...point,
        axisValue,
        timestamp: point.timestamp,
        [`${source}Timestamp`]: point.timestamp,
      });
    }
  }

  add(electrical, "electrical");
  add(thermal, "thermal");
  return [...rows.values()].sort(
    (left, right) => Number(left.axisValue) - Number(right.axisValue),
  );
}

export function formatElapsedAxis(value: number): string {
  const total = Math.max(0, Math.round(value));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function formatTimeAxis(value: number, mode: TimeAxisMode): string {
  if (mode === "synchronized") return formatElapsedAxis(value);
  return new Date(value).toLocaleTimeString("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "America/Sao_Paulo",
  });
}
