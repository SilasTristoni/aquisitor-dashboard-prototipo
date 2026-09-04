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

  test("mantém o aquecimento físico no CH29 sem deslocamento na série da dashboard", () => {
    const timestamps = [
      "2026-08-25T19:35:12Z",
      "2026-08-25T19:35:15Z",
      "2026-08-25T19:35:18Z",
    ];
    const readings = [21.5, 25, 29].map((channel29, index): Reading => {
      const channels = Array<number | null>(32).fill(null);
      channels[27] = 21.34;
      channels[28] = channel29;
      channels[29] = 21.71;
      return {
        timestamp: timestamps[index],
        device_id: 1,
        source_role: "temperature",
        raw_power: null,
        raw_power_unit: "W",
        power_w: null,
        temperatures_c: channels,
        quality: "good",
      };
    });

    const view = buildCombinedView(readings);
    expect(view.temperatureReadings.map((reading) => reading.temperatures_c[28])).toEqual([
      21.5,
      25,
      29,
    ]);
    expect(view.chartData.map((row) => row.t29)).toEqual([21.5, 25, 29]);
    expect(view.chartData.map((row) => row.t28)).toEqual([21.34, 21.34, 21.34]);
    expect(view.chartData.map((row) => row.t30)).toEqual([21.71, 21.71, 21.71]);
    expect(view.chartData.map((row) => row.timestamp)).toEqual(timestamps);
  });

  test("usa o início real comum da sessão sem deslocar cada fonte", () => {
    const electricalReadings = [0, 1, 2, 3].map((seconds) =>
      electrical(`2026-09-03T14:00:0${seconds}Z`, 100 + seconds),
    );
    const thermalReadings = [0, 3, 6, 9].map((seconds) =>
      thermal(`2026-09-03T14:03:0${seconds}Z`, [50 + seconds, 49, 48]),
    );

    const synchronized = buildCombinedView(
      [...electricalReadings, ...thermalReadings],
      "synchronized",
      "2026-09-03T14:00:00Z",
    );
    const real = buildCombinedView(
      [...electricalReadings, ...thermalReadings], "real", "2026-09-03T14:00:00Z",
    );

    expect(synchronized.electricalReadings).toHaveLength(4);
    expect(synchronized.temperatureReadings).toHaveLength(4);
    expect(synchronized.chartData.find((row) => row.power != null)?.axisValue).toBe(0);
    expect(synchronized.chartData.find((row) => row.t6 != null)?.axisValue).toBe(180);
    expect(
      Number(real.chartData.find((row) => row.t6 != null)?.axisValue)
      - Number(real.chartData.find((row) => row.power != null)?.axisValue),
    ).toBe(180_000);
    expect(synchronized.electricalReadings.map((reading) => reading.timestamp)).toEqual(
      electricalReadings.map((reading) => reading.timestamp),
    );
    expect(synchronized.temperatureReadings.map((reading) => reading.timestamp)).toEqual(
      thermalReadings.map((reading) => reading.timestamp),
    );
    expect(numericStats(synchronized.electricalReadings.map((reading) => reading.power_w!))).toEqual(
      numericStats(real.electricalReadings.map((reading) => reading.power_w!)),
    );
  });

  test("exclui leituras anteriores ao início comum da sessão", () => {
    const view = buildCombinedView([
      electrical("2026-09-03T13:59:59Z", 90),
      electrical("2026-09-03T14:00:00Z", 100),
      thermal("2026-09-03T14:00:00.350Z", [50, 49, 48]),
    ], "synchronized", "2026-09-03T14:00:00Z");

    expect(view.chartData).toHaveLength(2);
    expect(view.chartData.some((row) => row.power === 90)).toBe(false);
    expect(view.chartData.map((row) => row.axisValue)).toEqual([0, 0.35]);
  });
});
