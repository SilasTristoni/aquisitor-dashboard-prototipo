import type { Reading } from "../types";
import { mergeIndependentSeries, type TimeAxisMode } from "./chartPresentation";

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

export function buildCombinedView(
  readings: Reading[],
  timeAxisMode: TimeAxisMode = "synchronized",
  sessionStartedAt?: string,
) {
  const byTimestamp = (left: Reading, right: Reading) =>
    Date.parse(left.timestamp) - Date.parse(right.timestamp);
  const electricalReadings = readings.filter(isElectricalReading).sort(byTimestamp);
  const temperatureReadings = readings.filter(isTemperatureReading).sort(byTimestamp);
  const electricalPoints = electricalReadings.map((reading) => ({
    timestamp: reading.timestamp,
    power: reading.power_w,
  }));
  const thermalPoints = temperatureReadings.map((reading) => {
    const row: Record<string, string | number | null> & { timestamp: string } = {
      timestamp: reading.timestamp,
      avgTemp: numericStats(validTemperatures(reading)).avg,
    };
    reading.temperatures_c.forEach((value, index) => {
      row[`t${index + 1}`] = value;
    });
    return row;
  });

  return {
    electricalReadings,
    temperatureReadings,
    latestElectrical: electricalReadings.at(-1),
    latestTemperature: temperatureReadings.at(-1),
    chartData: mergeIndependentSeries(
      electricalPoints, thermalPoints, timeAxisMode, sessionStartedAt,
    ),
  };
}
