import { render, screen } from "@testing-library/react";
import { ThermalPeak } from "../components/ThermalPeak";
import { mergeIndependentSeries, observedGaps } from "../utils/chartPresentation";
import { sourcePresentation } from "../utils/sourcePresentation";
import type { Reading, RuntimeStatus } from "../types";

const origin = "2026-10-16T12:00:00Z";
const at = (seconds: number) => new Date(Date.parse(origin) + seconds * 1000).toISOString();

test("lacuna elétrica mantém zero real, timestamps e a curva térmica independente", () => {
  const electrical = [0, 1, 2, 30].map(seconds => ({ timestamp: at(seconds), active_power_w: seconds }));
  const thermal = [{ timestamp: at(16), channel_25: 80 }];
  const snapshot = structuredClone(electrical);
  const gaps = observedGaps(electrical, "electrical");
  expect(gaps).toEqual([{ source: "electrical", after: at(2), before: at(30) }]);
  for (const mode of ["real", "synchronized"] as const) {
    const rows = mergeIndependentSeries(electrical, thermal, mode, origin, gaps);
    expect(rows.find(row => row.chartGap)).toMatchObject({ active_power_w: null, channel_25: 80 });
    expect(rows[0].active_power_w).toBe(0);
    expect(rows.filter(row => !row.chartGap).map(row => row.electricalTimestamp)).toEqual(electrical.map(point => point.timestamp));
  }
  expect(electrical).toEqual(snapshot);
});

test("lacuna de um termopar não apaga outro canal", () => {
  const rows = mergeIndependentSeries([], [{ timestamp: at(0), channel_25: 1, channel_29: 2 }, { timestamp: at(10), channel_25: null, channel_29: 4 }, { timestamp: at(20), channel_25: 3, channel_29: 6 }], "synchronized", origin, [{ source: "thermal", after: at(0), before: at(20), keys: ["channel_25"] }]);
  expect(rows[1]).toMatchObject({ channel_25: null, channel_29: 4 });
});

test("zero, pausa, desconexão, atraso e ausência de dados são estados distintos", () => {
  const status = { device_id: 1, connected: true, state: "reading", expected_interval_ms: 1000 } as RuntimeStatus;
  const reading = { timestamp: origin, power_w: 0 } as Reading;
  const now = Date.parse(origin) + 1000;
  expect(sourcePresentation(status, reading, false, now)).toMatchObject({ state: "Leitura recente", current: true });
  expect(sourcePresentation(status, reading, true, now)).toMatchObject({ state: "Sessão pausada", current: false });
  expect(sourcePresentation({ ...status, connected: false }, reading, false, now)).toMatchObject({ state: "Fonte desconectada", lastValidAt: origin, current: false });
  expect(sourcePresentation(status, reading, false, now + 30000).state).toBe("Sem leitura recente");
  expect(sourcePresentation(status, undefined, false, now).state).toBe("Sem dados");
  expect(reading.power_w).toBe(0);
});

test("pico informa canal, horário e as duas durações sem converter ausência para zero", () => {
  render(<ThermalPeak peak={{ label: "T29 — Carcaça", value_c: 80, timestamp: at(90), session_elapsed_seconds: 90, period_elapsed_seconds: 30 }} />);
  expect(screen.getByTestId("thermal-peak")).toHaveTextContent("T29 — Carcaça");
  expect(screen.getByTestId("thermal-peak")).toHaveTextContent("desde o início da sessão");
  expect(screen.getByTestId("thermal-peak")).toHaveTextContent("desde o início do período");
  expect(screen.getByTestId("thermal-peak")).toHaveTextContent("primeira ocorrência");
});
