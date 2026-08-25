import { describe, expect, test } from "vitest";
import type { Reading } from "../types";
import { buildCombinedView, numericStats } from "../utils/combinedReadings";

function electrical(timestamp: string, power: number): Reading {
  return { timestamp, device_id: 2, source_role: "electrical", raw_power: power, raw_power_unit: "W", power_w: power, temperatures_c: [], quality: "good" };
}

function thermal(timestamp: string, values: [number, number, number]): Reading {
  const channels = Array<number | null>(32).fill(null);
  channels[5] = values[0]; channels[8] = values[1]; channels[12] = values[2];
  return { timestamp, device_id: 1, source_role: "temperature", raw_power: null, raw_power_unit: "W", power_w: null, temperatures_c: channels, quality: "good" };
}

describe("aquisição combinada", () => {
  test("preserva os ciclos independentes e não duplica temperaturas", () => {
    const readings = [
      electrical("2026-08-17T12:00:00Z", 17.7),
      thermal("2026-08-17T12:00:00Z", [70.1, 69.9, 70.2]),
      electrical("2026-08-17T12:00:01Z", 17.8),
      electrical("2026-08-17T12:00:02Z", 17.9),
      thermal("2026-08-17T12:00:03Z", [69.8, 69.7, 69.9]),
    ];
    const view = buildCombinedView(readings);
    expect(view.electricalReadings).toHaveLength(3);
    expect(view.temperatureReadings).toHaveLength(2);
    expect(view.chartData).toHaveLength(4);
    expect(view.chartData.filter((row) => row.avgTemp != null)).toHaveLength(2);
    expect(view.latestElectrical?.timestamp).toBe("2026-08-17T12:00:02Z");
    expect(view.latestTemperature?.timestamp).toBe("2026-08-17T12:00:03Z");
    expect(numericStats([69.8, 69.7, 69.9]).avg).toBeCloseTo(69.8);
  });

  test("mantém a fonte restante quando a outra está indisponível", () => {
    expect(buildCombinedView([electrical("2026-08-17T12:00:00Z", 17.7)]).latestTemperature).toBeUndefined();
    expect(buildCombinedView([thermal("2026-08-17T12:00:00Z", [70.1, 69.9, 70.2])]).latestElectrical).toBeUndefined();
  });
});
