import { emptySourceHistory, observeSource, splitAtSourceEvents, visualPowerTransitions } from "../utils/sourceEvents";
import type { Reading, RuntimeStatus } from "../types";

const reading = { timestamp: new Date(10000).toISOString(), power_w: 1200, temperatures_c: [45] } as Reading;
const online = { connected: true, state: "connected", reading: true } as RuntimeStatus;

test("confirmed disconnect has separate visual zero; inputs remain physical samples", () => {
  const snapshot = structuredClone(reading);
  const lost = observeSource(emptySourceHistory(), { ...online, connected: false }, reading, false, 15000);
  expect(lost.unavailable).toBe(true);
  const rows = visualPowerTransitions(lost.events, 20000, time => time);
  expect(rows.map(row => row.visualPower)).toEqual([1200, 0, 0, null]);
  expect(reading).toEqual(snapshot);
  expect(lost.events[0].lastReadingAt).toBe(10000);
  const stale = observeSource(lost, online, reading, false, 21000);
  expect(stale.unavailable).toBe(true);
  const recovered = observeSource(stale, online, { ...reading, timestamp: new Date(22000).toISOString() }, false, 23000);
  expect(recovered.unavailable).toBe(false);
  expect(recovered.events.at(-1)?.at).toBe(22000);
  expect(splitAtSourceEvents([{ axisValue: 10000, power: 1200 }, { axisValue: 22000, power: 1250 }], recovered.events, time => time)).toHaveLength(2);
});

test("latency, temporary error and real zero do not cause artificial disconnect", () => {
  for (const status of [online, { ...online, state: "degraded", last_error: "timeout" }]) {
    const history = observeSource(emptySourceHistory(), status, { ...reading, power_w: 0 }, false, 999999);
    expect(history.events).toEqual([]);
    expect(visualPowerTransitions(history.events, 999999, time => time)).toEqual([]);
  }
});

test("pause is an event and never a zero; thermal source has no visual power", () => {
  const paused = observeSource(emptySourceHistory(), { ...online, connected: false }, reading, true, 15000);
  expect(paused.events.map(event => event.kind)).toEqual(["paused"]);
  expect(visualPowerTransitions(paused.events, 20000, time => time)).toEqual([]);
  const thermal = observeSource(emptySourceHistory(), { ...online, connected: false }, { ...reading, power_w: null }, false, 15000);
  expect(visualPowerTransitions(thermal.events, 20000, time => time)).toEqual([]);
});
