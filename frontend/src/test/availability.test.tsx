import { render } from "@testing-library/react";
import { Line, LineChart, XAxis, YAxis } from "recharts";
import { AvailabilityOverlay } from "../components/AvailabilityOverlay";
import { availabilityAxis, availabilitySegments, availabilityBreaks, availabilityDomain, type AvailabilityInterval } from "../utils/availability";

const at = (second: number) => new Date(Date.UTC(2026, 9, 27, 12) + second * 1000).toISOString();
const intervals: AvailabilityInterval[] = [10, 40].map(start => ({ start: at(start), end: at(start + 10), confirmed_until: at(start + 10), end_reason: "reading_resumed", source: "electrical", evidence: "backend_observed_v1" }));

test("two confirmed outages render separate zero overlays and reconnect to real samples", () => {
  const rows = [0, 5, 9, 20, 39, 50, 60].map(time => ({ axisValue: time, power: time === 5 ? 0 : 100 + time, t1: 25 + time }));
  const original = structuredClone(rows);
  const axis = availabilityAxis("synchronized", at(0));
  const segments = availabilitySegments(intervals, rows, "power", axis);
  expect(segments[0].points).toEqual([{ x: 9, y: 109 }, { x: 10, y: 0 }, { x: 20, y: 0 }, { x: 20, y: 120 }]);
  const chart = availabilityBreaks(rows, intervals, "power", axis);
  const { container } = render(<LineChart width={800} height={350} data={chart}>
    <XAxis dataKey="axisValue" type="number" domain={availabilityDomain(rows, segments)} /><YAxis yAxisId="power" />
    <Line dataKey="power" yAxisId="power" connectNulls={false} isAnimationActive={false} />
    <AvailabilityOverlay segments={segments} />
  </LineChart>);
  expect(container.querySelectorAll(".availability-reference").length).toBe(6);
  expect(rows).toEqual(original);
  expect(chart.filter(row => row.power === 0)).toHaveLength(1);
  expect(chart.filter(row => row.power === null)).toHaveLength(2);
  expect(segments[1].points.at(-1)).toEqual({ x: 50, y: 150 });
});

test("old sessions, pauses and unknown intervals cannot create recovery or temperature zeros", () => {
  const axis = availabilityAxis("real", "");
  expect(availabilitySegments([], [], "active_power_w", axis)).toEqual([]);
  const rows = [{ axisValue: Date.parse(at(9)), power: 10, t1: null }, { axisValue: Date.parse(at(20)), power: 20, t1: 45 }];
  const paused = [{ ...intervals[0], end_reason: "paused" }];
  const segments = availabilitySegments(paused, rows, "power", axis);
  expect(segments[0].points).toHaveLength(3);
  expect(rows[0].t1).toBeNull();
  const clipped = availabilitySegments(intervals, rows, "power", axis, Date.parse(at(12)), Date.parse(at(18)));
  expect(clipped[0].points).toEqual([{ x: Date.parse(at(12)), y: 0 }, { x: Date.parse(at(18)), y: 0 }]);
});
