import type { Reading } from "../types";

export type NumericStats = { min: number | null; max: number | null; avg: number | null };

export function numericStats(values: number[]): NumericStats {
  if (!values.length) return { min: null, max: null, avg: null };
  return {
    min: Math.min(...values),
    max: Math.max(...values),
    avg: values.reduce((sum, value) => sum + value, 0) / values.length,
  };
}

export function validTemperatures(reading?: Reading): number[] {
  return reading?.temperatures_c.filter((value): value is number => value != null) ?? [];
}

export function isElectricalReading(reading: Reading): boolean {
  return reading.source_role === "electrical" || reading.power_w != null;
}

export function isTemperatureReading(reading: Reading): boolean {
  return reading.source_role === "temperature" || reading.temperatures_c.length > 0;
}

export function buildCombinedView(readings: Reading[]) {
  const electricalReadings = readings.filter(isElectricalReading);
  const temperatureReadings = readings.filter(isTemperatureReading);
  const rows = new Map<string, Record<string, string | number | null>>();

  for (const reading of readings) {
    const timestamp = reading.timestamp;
    const row = rows.get(timestamp) ?? {
      timestamp,
      time: new Date(timestamp).toLocaleTimeString("pt-BR"),
    };
    if (isElectricalReading(reading)) row.power = reading.power_w;
    if (isTemperatureReading(reading)) {
      const values = validTemperatures(reading);
      row.avgTemp = numericStats(values).avg;
      reading.temperatures_c.forEach((value, index) => {
        row[`t${index + 1}`] = value;
      });
    }
    rows.set(timestamp, row);
  }

  return {
    electricalReadings,
    temperatureReadings,
    latestElectrical: electricalReadings.at(-1),
    latestTemperature: temperatureReadings.at(-1),
    chartData: [...rows.values()].sort(
      (left, right) =>
        new Date(String(left.timestamp)).getTime() - new Date(String(right.timestamp)).getTime(),
    ),
  };
}
