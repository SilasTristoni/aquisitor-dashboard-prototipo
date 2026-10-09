import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";
import SessionDetailPage from "../pages/SessionDetailPage";

const authState = vi.hoisted(() => ({ role: "admin" }));
vi.mock("../auth", () => ({ useAuth: () => ({ user: { id: 1, role: authState.role } }) }));

const apiMock = vi.hoisted(() => vi.fn());
const downloadMock = vi.hoisted(() => vi.fn());

vi.mock("recharts", () => {
  const Container = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  const Chart = ({ children, onClick }: { children?: ReactNode; onClick?: (state: any, event?: { target: EventTarget | null }) => void }) => <div data-testid="period-chart" onClick={event => { if (event.target instanceof Element && event.target.closest(".recharts-brush")) onClick?.({ activeLabel: 0 }, event); }}>{children}<button onClick={() => onClick?.({ activeLabel: 60 })}>Marcar 1 minuto</button><button onClick={() => onClick?.({ activeLabel: 90 })}>Marcar 90 segundos</button></div>;
  const Brush = ({ onChange }: { onChange?: (range: { startIndex: number; endIndex: number }) => void }) => <div className="recharts-brush"><button onClick={() => onChange?.({ startIndex: 1, endIndex: 2 })}>Arrastar seleção</button></div>;
  const Primitive = () => null;
  return {
    Brush,
    CartesianGrid: Primitive,
    ComposedChart: Chart,
    Legend: Primitive,
    Line: Primitive, ReferenceDot: Primitive, ReferenceLine: Primitive, ReferenceArea: Primitive,
    ResponsiveContainer: Container,
    Tooltip: Primitive,
    XAxis: Primitive,
    YAxis: Primitive,
  };
});

test("preserva segundos, exige confirmação da estabilização e exporta somente a janela aplicada", async () => {
  apiMock.mockClear(); downloadMock.mockClear();
  const precise = { ...session, started_at: "2026-09-03T13:00:17.125Z", ended_at: "2026-09-03T13:03:42.250Z" };
  apiMock.mockImplementation((path: string) => Promise.resolve(
    path === "/sessions/42" ? precise : path === "/reports/period/preview" ? analysis : { items: [] },
  ));
  render(<MemoryRouter initialEntries={["/sessoes/42"]}><Routes><Route path="/sessoes/:id" element={<SessionDetailPage />} /></Routes></MemoryRouter>);
  await screen.findByRole("radio", { name: "Sessão completa" });
  const previews = () => apiMock.mock.calls.filter(([path]) => path === "/reports/period/preview");
  expect(JSON.parse(previews()[0][1].body)).toMatchObject({ start: precise.started_at, end: precise.ended_at });
  await userEvent.click(screen.getByRole("radio", { name: "Após estabilização sugerida" }));
  expect(previews()).toHaveLength(1);
  await userEvent.click(screen.getByRole("button", { name: "Usar este período" }));
  await waitFor(() => expect(previews()).toHaveLength(2));
  expect(JSON.parse(previews()[1][1].body)).toMatchObject({ start: analysis.statistics.temperature.stabilization.start, end: precise.ended_at });
  await userEvent.click(screen.getByRole("radio", { name: "Selecionar no gráfico" }));
  fireEvent.change(screen.getByLabelText("Início"), { target: { value: "2026-09-03T10:02:12" } });
  await userEvent.click(screen.getByText("Exportar", { exact: true }));
  await userEvent.click(screen.getByRole("button", { name: "XLSX técnico" }));
  expect(downloadMock.mock.calls.at(-1)?.[2]).toMatchObject({ start: analysis.statistics.temperature.stabilization.start, end: precise.ended_at });
  expect(previews()).toHaveLength(2);
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

test("abre período oficial salvo e viewer não recebe controles de edição", async () => {
  authState.role = "viewer";
  apiMock.mockClear();
  const official = { start: "2026-09-03T13:00:15.125Z", end: "2026-09-03T13:02:45.250Z", label: "Regime permanente" };
  apiMock.mockImplementation((path: string) => Promise.resolve(path === "/sessions/42" ? { ...session, analysis_period: official } : path === "/reports/period/preview" ? analysis : { items: [], total: 0 }));
  render(<MemoryRouter initialEntries={["/sessoes/42"]}><Routes><Route path="/sessoes/:id" element={<SessionDetailPage />} /></Routes></MemoryRouter>);
  await screen.findByText(/Período oficial:/);
  await waitFor(() => expect(apiMock.mock.calls.some(([path]) => path === "/reports/period/preview")).toBe(true));
  const preview = apiMock.mock.calls.find(([path]) => path === "/reports/period/preview");
  expect(JSON.parse(preview?.[1].body)).toMatchObject({ start: official.start, end: official.end });
  expect(screen.queryByLabelText("Nome do período oficial")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("radio", { name: "Selecionar no gráfico" }));
  expect(screen.getByLabelText("Início")).toHaveValue("2026-09-03T10:00:15.125");
  for (const name of ["Editar informações", "Salvar período aplicado como oficial", "Salvar evento", "Gerar link"]) expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("radio", { name: "Sessão completa" }));
  expect(screen.getByText(/Período oficial:/)).toBeInTheDocument();
  expect(apiMock.mock.calls.filter(([, options]) => options?.method === "PUT")).toHaveLength(0);
  authState.role = "admin";
});

test("dois cliques sincronizam campos e só recalculam após aplicar", async () => {
  apiMock.mockClear();
  apiMock.mockImplementation((path: string) => Promise.resolve(path === "/sessions/42" ? session : path === "/reports/period/preview" ? analysis : { items: [], total: 0 }));
  render(<MemoryRouter initialEntries={["/sessoes/42"]}><Routes><Route path="/sessoes/:id" element={<SessionDetailPage />} /></Routes></MemoryRouter>);
  await screen.findByRole("radio", { name: "Selecionar no gráfico" });
  await userEvent.click(screen.getByRole("radio", { name: "Selecionar no gráfico" }));
  await userEvent.click(screen.getByRole("button", { name: "Marcar 1 minuto" }));
  await userEvent.click(screen.getByRole("button", { name: "Marcar 90 segundos" }));
  expect(screen.getByLabelText("Início")).toHaveValue("2026-09-03T10:01");
  expect(screen.getByLabelText("Fim")).toHaveValue("2026-09-03T10:01:30.000");
  expect(apiMock.mock.calls.filter(([path]) => path === "/reports/period/preview")).toHaveLength(1);
  await userEvent.click(screen.getByRole("button", { name: "Aplicar período" }));
  await waitFor(() => expect(apiMock.mock.calls.filter(([path]) => path === "/reports/period/preview")).toHaveLength(2));
  const preview = apiMock.mock.calls.filter(([path]) => path === "/reports/period/preview").at(-1);
  expect(JSON.parse(preview?.[1].body)).toMatchObject({ start: "2026-09-03T10:01:00", end: "2026-09-03T10:01:30" });
});

test("clique propagado pelo Brush não sobrescreve o intervalo arrastado", async () => {
  apiMock.mockClear();
  const brushAnalysis = { ...analysis, series: [{ ...analysis.series[0], electrical: [
    analysis.series[0].electrical[0],
    { timestamp: "2026-09-03T13:01:00Z", active_power_w: 500 },
    analysis.series[0].electrical[1],
  ] }] };
  apiMock.mockImplementation((path: string) => Promise.resolve(path === "/sessions/42" ? session : path === "/reports/period/preview" ? brushAnalysis : { items: [], total: 0 }));
  render(<MemoryRouter initialEntries={["/sessoes/42"]}><Routes><Route path="/sessoes/:id" element={<SessionDetailPage />} /></Routes></MemoryRouter>);
  await userEvent.click(await screen.findByRole("radio", { name: "Selecionar no gráfico" }));
  await userEvent.click(screen.getByRole("button", { name: "Marcar 90 segundos" }));
  await userEvent.click(screen.getByRole("button", { name: "Arrastar seleção" }));
  expect(screen.getByLabelText("Início")).toHaveValue("2026-09-03T10:01");
  expect(screen.getByLabelText("Fim")).toHaveValue("2026-09-03T10:03");
  expect(screen.queryByText(/Início marcado/)).not.toBeInTheDocument();
  expect(apiMock.mock.calls.filter(([path]) => path === "/reports/period/preview")).toHaveLength(1);
  await userEvent.click(screen.getByRole("button", { name: "Aplicar período" }));
  await waitFor(() => expect(apiMock.mock.calls.filter(([path]) => path === "/reports/period/preview")).toHaveLength(2));
  expect(JSON.parse(apiMock.mock.calls.filter(([path]) => path === "/reports/period/preview").at(-1)?.[1].body)).toMatchObject({ start: "2026-09-03T10:01:00", end: "2026-09-03T10:03:00" });
});

test("cancelar seleção preserva KPIs; oficial fica recolhido e pode ser removido", async () => {
  authState.role = "admin";
  apiMock.mockClear();
  const official = { start: session.started_at, end: session.ended_at, label: "Regime permanente" };
  apiMock.mockImplementation((path: string) => Promise.resolve(path === "/sessions/42" ? { ...session, analysis_period: official } : path === "/reports/period/preview" ? analysis : { items: [], total: 0 }));
  render(<MemoryRouter initialEntries={["/sessoes/42"]}><Routes><Route path="/sessoes/:id" element={<SessionDetailPage />} /></Routes></MemoryRouter>);
  await screen.findByText(/Período oficial: Regime permanente/);
  expect(screen.queryByLabelText("Nome do período oficial")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("radio", { name: "Selecionar no gráfico" }));
  fireEvent.change(screen.getByLabelText("Início"), { target: { value: "2026-09-03T10:01:00" } });
  expect(screen.getByRole("button", { name: "Salvar como período oficial" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Cancelar seleção" }));
  expect(apiMock.mock.calls.filter(([path]) => path === "/reports/period/preview")).toHaveLength(1);
  await userEvent.click(screen.getByRole("button", { name: "Remover período oficial" }));
  await waitFor(() => expect(screen.queryByText(/Período oficial: Regime permanente/)).not.toBeInTheDocument());
  expect(apiMock).toHaveBeenCalledWith("/sessions/42/analysis-period", { method: "DELETE" });
});

test("recalcula a visão executiva da sessão para o período selecionado", async () => {
  apiMock.mockClear();
  apiMock.mockImplementation((path: string) => {
    if (path === "/sessions/42") return Promise.resolve(session);
    if (path === "/alerts?page_size=100") return Promise.resolve({ items: [] });
    if (path === "/reports/period/preview") return Promise.resolve(analysis);
    if ((path.includes("/annotations") || path.includes("/shares"))) return Promise.resolve({ items: [], total: 0 });
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
  await userEvent.click(screen.getByRole("radio", { name: "Após estabilização sugerida" }));
  expect(screen.getByText(/inclinação ≤ 0,2 °C\/min/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Início da sessão" })).toHaveClass("active");
  await waitFor(() => {
    const initialPreview = apiMock.mock.calls.find(([path]) => path === "/reports/period/preview");
    expect(JSON.parse(String(initialPreview?.[1]?.body))).toMatchObject({
      time_axis_mode: "synchronized",
    });
  });

  await userEvent.click(screen.getByRole("button", { name: "Horário real" }));
  await userEvent.click(screen.getByRole("radio", { name: "Selecionar no gráfico" }));
  await userEvent.click(screen.getByRole("button", { name: "Aplicar período" }));
  await waitFor(() => {
    const previewCalls = apiMock.mock.calls.filter(([path]) => path === "/reports/period/preview");
    expect(previewCalls.length).toBe(2);
    expect(JSON.parse(String(previewCalls.at(-1)?.[1]?.body))).toMatchObject({
      session_ids: [42],
      channels: null,
      include_open_channels: false,
      timezone: "America/Sao_Paulo",
      time_axis_mode: "real",
      start: "2026-09-03T10:00:00",
      end: "2026-09-03T10:03:00",
    });
  });
});
