import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";
import SessionDetailPage from "../pages/SessionDetailPage";

const apiMock = vi.hoisted(() => vi.fn());
const downloadMock = vi.hoisted(() => vi.fn());

vi.mock("recharts", () => {
  const Container = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  const Chart = ({ children }: { children?: ReactNode }) => <div data-testid="period-chart">{children}</div>;
  const Primitive = () => null;
  return {
    Brush: Primitive,
    CartesianGrid: Primitive,
    ComposedChart: Chart,
    Legend: Primitive,
    Line: Primitive,
    ResponsiveContainer: Container,
    Tooltip: Primitive,
    XAxis: Primitive,
    YAxis: Primitive,
  };
});

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ...actual, api: apiMock, downloadWithBody: downloadMock };
});

const session = {
  id: 42,
  name: "Ensaio combinado Britânia",
  description: "Validação térmica e elétrica",
  notes: null,
  metadata: { product: "Forno elétrico", model: "BFE50" },
  status: "finished",
  started_at: "2026-09-03T13:00:00Z",
  ended_at: "2026-09-03T13:03:00Z",
  sync_tolerance_ms: 1500,
  statistics: { duration_seconds: 180 },
  operator: { id: 1, name: "Administrador Demo", email: "admin@thermopower.com.br" },
  device: { id: 1, name: "AT4532" },
  devices: [
    { role: "temperature", device: { id: 1, name: "AT4532", manufacturer: "Applent", model: "AT4532", serial_number: "AT-01", port: "COM5", baud_rate: 19200 } },
    { role: "electrical", device: { id: 2, name: "GPM-8213", manufacturer: "GW Instek", model: "GPM-8213", serial_number: "GPM-01", port: "COM4", baud_rate: 9600 } },
  ],
  channels: [
    { channel: 25, name: "Saída de ar", enabled: true },
    { channel: 26, name: "Carcaça superior", enabled: true },
  ],
};

const analysis = {
  selected_channels: [25, 26],
  channel_labels: { "25": "T25 — Saída de ar", "26": "T26 — Carcaça superior" },
  statistics: {
    general: { full_session_duration_seconds: 180, analyzed_period_seconds: 180, gap_count: 0, electrical_sample_count: 8, temperature_sample_count: 8 },
    electrical: { energy_wh: 24.5, active_power_w: { mean: 480.25, max: 780, min: 180, p95: 780 } },
    temperature: {
      max: 60.7,
      critical_channel_label: "T25 — Saída de ar",
      critical_value_c: 60.7,
      critical_timestamp: "2026-09-03T13:03:00Z",
      maximum_delta_t: { value_c: 10.35, cold_channel: 26, hot_channel: 25 },
      greatest_heating_rate: { channel: 25, value_c_per_minute: 0.23 },
      stabilization: { suggested: true, start: "2026-09-03T13:01:00Z" },
    },
    channels: [
      { channel: 25, friendly_name: "Saída de ar", count: 8, mean: 60.35, min: 60, max: 60.7, range: 0.7, standard_deviation: 0.23, p95: 60.66 },
      { channel: 26, friendly_name: "Carcaça superior", count: 8, mean: 50.18, min: 50, max: 50.35, range: 0.35, standard_deviation: 0.11, p95: 50.33 },
    ],
  },
  series: [{
    session_id: 42,
    session_name: "Ensaio combinado Britânia",
    electrical: [
      { timestamp: "2026-09-03T13:00:00Z", active_power_w: 780 },
      { timestamp: "2026-09-03T13:03:00Z", active_power_w: 180 },
    ],
    temperatures: [
      { timestamp: "2026-09-03T13:00:00Z", channel_25: 60, channel_26: 50 },
      { timestamp: "2026-09-03T13:03:00Z", channel_25: 60.7, channel_26: 50.35 },
    ],
  }],
};

test("recalcula a visão executiva da sessão para o período selecionado", async () => {
  apiMock.mockImplementation((path: string) => {
    if (path === "/sessions/42") return Promise.resolve(session);
    if (path === "/alerts?page_size=100") return Promise.resolve({ items: [] });
    if (path === "/reports/period/preview") return Promise.resolve(analysis);
    throw new Error(`Rota não simulada: ${path}`);
  });
  render(
    <MemoryRouter initialEntries={["/sessoes/42"]}>
      <Routes><Route path="/sessoes/:id" element={<SessionDetailPage />} /></Routes>
    </MemoryRouter>,
  );

  expect(await screen.findByRole("heading", { name: "Ensaio combinado Britânia" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Temperatura + potência" })).toBeInTheDocument();
  expect(screen.getAllByText("480,25 W").length).toBeGreaterThan(0);
  expect(screen.getAllByText("60,70 °C").length).toBeGreaterThan(0);
  expect(screen.getAllByText("T25 — Saída de ar").length).toBeGreaterThan(0);
  expect(screen.getByText("Operador não informado", { exact: false })).toBeInTheDocument();
  expect(screen.getByText(/inclinação ≤ 0,2 °C\/min/i)).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "Aplicar período" }));
  await waitFor(() => {
    const previewCalls = apiMock.mock.calls.filter(([path]) => path === "/reports/period/preview");
    expect(previewCalls.length).toBe(2);
    expect(JSON.parse(String(previewCalls.at(-1)?.[1]?.body))).toMatchObject({
      session_ids: [42],
      channels: null,
      include_open_channels: false,
      timezone: "America/Sao_Paulo",
      start: "2026-09-03T10:00",
      end: "2026-09-03T10:03",
    });
  });
});
