import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { api, ApiError, download, downloadWithBody } from "../api";
import { FirstUseHint, HelpMenu } from "../components/HelpMenu";
import { ErrorNotice } from "../components/ui";
import EventsPage from "../pages/EventsPage";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ...actual, api: vi.fn(), download: vi.fn() };
});

beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); });

test("erro mantém código, permite repetir e exporta diagnóstico contextual", async () => {
  const retry = vi.fn();
  const error = new ApiError("Não foi possível gerar o resumo executivo.", 500, "TP-EXP-A82F31");
  render(<ErrorNotice message={error.message} retry={retry} sessionId={16} />);
  expect(screen.getByRole("alert")).toHaveTextContent("TP-EXP-A82F31");
  expect(screen.getByText("Os dados da sessão permanecem salvos.")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));
  expect(retry).toHaveBeenCalledOnce();
  await userEvent.click(screen.getByRole("button", { name: "Exportar diagnóstico" }));
  expect(download).toHaveBeenCalledWith("/support/package?session_id=16&correlation_id=TP-EXP-A82F31", expect.stringContaining("ThermoPower-Diagnostico-"));
});

test("download preserva o identificador retornado pelo servidor", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { message: "Não foi possível gerar o resumo executivo.", correlation_id: "TP-EXP-A82F31" } }), { status: 500 })));
  try {
    await expect(downloadWithBody("/reports/period/executive.pdf", "report.pdf", {})).rejects.toMatchObject({ correlationId: "TP-EXP-A82F31" });
  } finally { vi.unstubAllGlobals(); }
});

test("ajuda oferece manual, identificação da build e orientação dispensável", async () => {
  vi.mocked(api).mockResolvedValue({ version: "0.6.5-client-preview", build: "abc123", environment: "client-preview", build_date: "2026-09-18T14:00:00Z" });
  const view = render(<><HelpMenu /><FirstUseHint /></>);
  await userEvent.click(screen.getByText("Ajuda"));
  await userEvent.click(screen.getByRole("button", { name: "Guia do usuário" }));
  expect(download).toHaveBeenCalledWith("/help/user-guide", "Manual do Usuário - ThermoPower Monitor.pdf");
  await userEvent.click(screen.getByRole("button", { name: "Sobre o ThermoPower" }));
  expect(await screen.findByRole("dialog")).toHaveTextContent("abc123");
  await userEvent.click(screen.getByRole("button", { name: "Fechar" }));
  await userEvent.click(screen.getByRole("button", { name: "Entendi, não mostrar novamente" }));
  view.unmount();
  render(<FirstUseHint />);
  expect(screen.queryByText("Seu ensaio em quatro passos")).not.toBeInTheDocument();
});

test("eventos filtram sessão e código e recolhem detalhes técnicos", async () => {
  vi.mocked(api).mockResolvedValue({ items: [{ id: 1, timestamp: "2026-09-18T14:00:00Z", level: "error", category: "EXPORT", message: "Não foi possível gerar o resumo executivo.", session_id: 16, details: { correlation_id: "TP-EXP-A82F31", exception_type: "RuntimeError" } }], page: 1, pages: 1, total: 1 });
  render(<EventsPage />);
  await screen.findByText("Não foi possível gerar o resumo executivo.");
  fireEvent.change(screen.getByLabelText("Sessão"), { target: { value: "16" } });
  fireEvent.change(screen.getByLabelText("Código do erro"), { target: { value: "TP-EXP-A82F31" } });
  await waitFor(() => expect(api).toHaveBeenLastCalledWith(expect.stringContaining("session_id=16&error_code=TP-EXP-A82F31")));
  expect(screen.getByText("Mostrar detalhes técnicos").closest("details")).not.toHaveAttribute("open");
});
