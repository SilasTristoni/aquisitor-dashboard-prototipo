import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";
import SharedSessionPage from "../pages/SharedSessionPage";

afterEach(() => { vi.unstubAllGlobals(); window.location.hash = ""; });

test("página pública pede senha fora da URL e mostra só downloads autorizados", async () => {
  window.location.hash = "a".repeat(43);
  const fetchMock = vi.fn().mockResolvedValueOnce({ ok: false, status: 401, json: async () => ({ error: { message: "Informe a senha correta do compartilhamento" } }) }).mockResolvedValueOnce({ ok: true, json: async () => ({ name: "Resultado compartilhado", metadata: { product: "Forno" }, official: true, analysis_label: "Estabilizado", period: { start: "2026-01-15T13:00:00Z", end: "2026-01-15T13:01:00Z" }, permissions: { graphs: false, pdf: true, xlsx: false, csv: false }, statistics: { electrical: { active_power_w: { mean: 100, max: 200 }, energy_wh: 2 }, temperature: { max: 40 }, general: { analyzed_period_seconds: 60 } }, series: [], annotations: [] }) });
  vi.stubGlobal("fetch", fetchMock);
  render(<SharedSessionPage />);
  await screen.findByLabelText("Senha do compartilhamento");
  await userEvent.type(screen.getByLabelText("Senha do compartilhamento"), "secret");
  await userEvent.click(screen.getByRole("button", { name: "Abrir resultado" }));
  await screen.findByRole("heading", { name: "Resultado compartilhado" });
  expect(screen.getByRole("button", { name: "Baixar PDF" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Baixar XLSX" })).not.toBeInTheDocument();
  expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  expect(screen.queryByText("Iniciar ensaio")).not.toBeInTheDocument();
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/public/shares/access");
  expect(JSON.parse(fetchMock.mock.calls[1][1].body).password).toBe("secret");
  expect(fetchMock.mock.calls[1][1].headers.Authorization).toBeUndefined();
  expect(window.location.href).not.toContain("secret");
});
