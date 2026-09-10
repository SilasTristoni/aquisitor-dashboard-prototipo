import { render } from "@testing-library/react";
import { Line, LineChart, XAxis, YAxis } from "recharts";
import { describe, expect, test } from "vitest";
import type { Reading } from "../types";
import { buildCombinedView } from "../utils/combinedReadings";
import { paddedDomain, parseUtcTimestamp, seriesPeak } from "../utils/chartPresentation";

describe("relógio comum e linhas independentes", () => {
  test.each(["2026-09-09T19:00:00Z", "2026-09-09T16:00:00-03:00", "2026-09-09T19:00:00"])(
    "preserva 120 leituras por fonte com origem %s", (origin) => {
      const start = Date.parse("2026-09-09T19:00:00Z");
      const readings: Reading[] = Array.from({ length: 120 }, (_, i) => [
        { device_id: 1, source_role: "electrical" as const, timestamp: new Date(start + i * 1000).toISOString(), power_w: 180 - i, raw_power: 180 - i, raw_power_unit: "W", temperatures_c: [], quality: "good" },
        { device_id: 2, source_role: "temperature" as const, timestamp: "2026-09-09T15:00:00-03:00", received_timestamp: new Date(start + i * 1000 + 150).toISOString(), power_w: null, raw_power: null, raw_power_unit: "W", temperatures_c: [...Array<null>(24).fill(null), 22 + i / 2], quality: "good" },
      ]).flat();
      const view = buildCombinedView(readings, "synchronized", origin);
      expect(view.electricalReadings).toHaveLength(120);
      expect(view.temperatureReadings).toHaveLength(120);
      expect(view.chartData).toHaveLength(240);
      expect(view.chartData[0].axisValue).toBe(0);
      expect(view.chartData[1]).toMatchObject({ axisValue: 0.15, t25: 22 });
      expect(seriesPeak(view.chartData, ["power"])?.value).toBe(180);
      expect(parseUtcTimestamp(origin)).toBe(start);
      expect(new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", hour: "2-digit", hour12: false }).format(start)).toBe("16");
      const { container } = render(<LineChart width={800} height={350} data={view.chartData}>
        <XAxis dataKey="axisValue" type="number" /><YAxis />
        <Line data={view.chartData.filter((r) => r.electricalTimestamp)} dataKey="power" isAnimationActive={false} dot={false} />
        <Line data={view.chartData.filter((r) => r.thermalTimestamp)} dataKey="t25" isAnimationActive={false} dot={false} />
      </LineChart>);
      const paths = container.querySelectorAll("path.recharts-line-curve");
      expect(paths).toHaveLength(2);
      for (const path of paths) expect(path.getAttribute("d")?.match(/L/g)?.length).toBe(119);
    },
  );

  test("mantém o filtro anterior à sessão e ignora datas inválidas", () => {
    const readings: Reading[] = ["invalid", "2026-09-09T18:59:59Z", "2026-09-09T19:00:00Z"].map((timestamp) => ({ timestamp, device_id: 1, power_w: 20, raw_power: 20, raw_power_unit: "W", temperatures_c: [], quality: "good" }));
    expect(buildCombinedView(readings, "synchronized", "2026-09-09T19:00:00").chartData).toHaveLength(1);
    expect(paddedDomain([22, 180])).toEqual([0, 194.4]);
    expect(paddedDomain([-20, 30])[0]).toBeLessThan(-20);
  });
});
