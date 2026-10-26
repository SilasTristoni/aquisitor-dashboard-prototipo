import { render } from "@testing-library/react";
import { Line, LineChart, XAxis, YAxis } from "recharts";
import { chartSeriesRows, mergeIndependentSeries } from "../utils/chartPresentation";
import { groupChartEvents } from "../components/ResultEvents";

const at = (second: number) => new Date(Date.UTC(2026, 9, 26) + second * 1000).toISOString();

test("a gap in one channel cannot fragment valid consecutive readings of another", () => {
  const thermal = [0, 1, 2, 3].map(i => ({ timestamp: at(i), channel_1: i === 1 ? null : i, channel_2: 25 + i }));
  const electrical = [0, 1, 2, 3].map(i => ({ timestamp: at(i + 0.1), active_power_w: i === 1 ? 0 : 120 }));
  const original = structuredClone({ thermal, electrical });
  const rows = mergeIndependentSeries(electrical, thermal, "synchronized", at(0), [{ source: "thermal", after: at(0), before: at(3), keys: ["channel_1"] }]);
  const { container } = render(<LineChart width={800} height={350} data={rows}>
    <XAxis dataKey="axisValue" type="number" /><YAxis />
    <Line data={chartSeriesRows(rows, "channel_2")} dataKey="channel_2" isAnimationActive={false} dot={false} />
    <Line data={chartSeriesRows(rows, "active_power_w")} dataKey="active_power_w" isAnimationActive={false} dot={false} />
  </LineChart>);
  for (const path of container.querySelectorAll("path.recharts-line-curve")) {
    expect(path.getAttribute("d")?.match(/M/g)).toHaveLength(1);
    expect(path.getAttribute("d")?.match(/L/g)).toHaveLength(3);
  }
  expect(chartSeriesRows(rows, "channel_1").some(row => row.channel_1 === null)).toBe(true);
  expect(chartSeriesRows(rows, "active_power_w").map(row => row.active_power_w)).toEqual([120, 0, 120, 120]);
  expect({ thermal, electrical }).toEqual(original);
});

test("dense events remain individually accessible while markers have room on mobile", () => {
  const events = Array.from({ length: 100 }, (_, i) => ({ timestamp: at(i), title: `Evento ${i}` }));
  const groups = groupChartEvents(events, value => Date.parse(value), 100000);
  expect(groups.length).toBeLessThanOrEqual(7);
  expect(groups.flatMap(group => group.events)).toEqual(events);
  for (let i = 1; i < groups.length; i++) expect(groups[i].x - groups[i - 1].x).toBeGreaterThan(16000);
});
