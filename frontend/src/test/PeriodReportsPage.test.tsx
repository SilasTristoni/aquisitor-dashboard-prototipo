import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import PeriodReportsPage from "../pages/PeriodReportsPage";

const session = {
  id: 7,
  name: "Ensaio térmico",
  status: "finished",
  device_id: 2,
  device_name: "Simulador",
  operator: "Operador",
  started_at: "2026-01-01T10:00:00Z",
  duration_seconds: 60,
  sample_count: 20,
  alert_count: 0,
};

function response(payload: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: async () => payload });
}

test("gera prévia por período e mantém abas de sessão e histórico", async () => {
  const fetchMock = vi.fn((...request: [RequestInfo | URL, RequestInit?]) => {
    const [input] = request;
    const url = String(input);
    if (url.includes("/sessions")) return response({ items: [session], page: 1, page_size: 100, total: 1, pages: 1 });
    if (url.includes("/devices")) return response([{ id: 2, name: "Simulador", connection_type: "simulator", protocol: "simulator", baud_rate: 115200, active: true }]);
    if (url.endsWith("/reports")) return response([]);
    if (url.includes("/reports/period/preview")) return response({
      period: { start: "2026-01-01T10:00:00Z", end: "2026-01-01T11:00:00Z", timezone: "America/Sao_Paulo" },
      sessions: [{ id: 7, name: "Ensaio térmico", electrical_samples: 2, temperature_samples: 2 }],
      statistics: { general: { session_count: 1, electrical_sample_count: 2, temperature_sample_count: 2, alert_count: 0, gap_count: 0, coverage_seconds: 60 }, electrical: { energy_wh: 1.25, active_power_w: { mean: 75, max: 100 } } },
      selected_channels: [1],
      series: [{ session_id: 7, session_name: "Ensaio térmico", electrical: [{ timestamp: "2026-01-01T10:00:00Z", active_power_w: 50 }], temperatures: [{ timestamp: "2026-01-01T10:00:00Z", channel_1: 30 }] }],
      warnings: ["As sessões são apresentadas como segmentos independentes."],
    });
    throw new Error(`URL não simulada: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter><PeriodReportsPage /></MemoryRouter>);

  expect(await screen.findByRole("heading", { name: "Central de relatórios" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Por período" })).toHaveClass("active");
  await userEvent.click(screen.getByRole("button", { name: /Gerar prévia/i }));
  expect(await screen.findByText("Ensaio térmico", { selector: "h3" })).toBeInTheDocument();
  expect(screen.getByText("1.250 Wh")).toBeInTheDocument();
  const previewCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/reports/period/preview"));
  expect(previewCall?.[1]).toMatchObject({ method: "POST" });
  expect(JSON.parse(String(previewCall?.[1]?.body))).toMatchObject({ timezone: "America/Sao_Paulo", channels: [1, 2, 3, 4, 5, 6, 7, 8] });

  await userEvent.click(screen.getByRole("button", { name: "Por sessão" }));
  expect(screen.getByText("COMPATIBILIDADE PRESERVADA")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Histórico" }));
  expect(screen.getByText("ARQUIVOS RECENTES")).toBeInTheDocument();
});
