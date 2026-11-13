import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { api } from "../api";
import RecoveryNotice from "../components/RecoveryNotice";

vi.mock("../api", async (original) => ({ ...await original<typeof import("../api")>(), api: vi.fn() }));
const session = { id: 71, name: "Ensaio sintético", reason: "unexpected_shutdown", started_at: "2026-11-11T08:00:00Z", last_sample_at: "2026-11-11T10:00:00Z", counts: { electrical: 7200, thermal: 1440 }, devices: [{ id: 2, name: "GPM" }, { id: 3, name: "AT4532" }] };

test("recovery preserves context, confirms before physical action, and reports partial success", async () => {
  let pending = true;
  vi.mocked(api).mockReset().mockImplementation(async (path, options) => {
    if (options?.method === "POST") { pending = false; return { unavailable_sources: [{ device_id: 3 }] }; }
    return path.includes("/health") ? { supervision_ready: true, storage: { state: "ok" }, write_faults: [] } : { items: pending ? [session] : [], total: pending ? 1 : 0, page: 1, pages: 1 };
  });
  render(<MemoryRouter><RecoveryNotice /></MemoryRouter>);
  expect(await screen.findByText("Ensaio interrompido encontrado")).toBeVisible();
  expect(screen.getByText(/7.200 leituras elétricas/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Retomar ensaio" }));
  expect(api).not.toHaveBeenCalledWith("/recovery/sessions/71", expect.anything());
  fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Confirmar" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Uma fonte permanece indisponível");
  expect(api).toHaveBeenCalledWith("/recovery/sessions/71", { method: "POST", body: JSON.stringify({ action: "resume" }) });
});

test("controlled shutdown, close confirmation, loading and failure retain recovery decision", async () => {
  let reject!: (reason: Error) => void;
  vi.mocked(api).mockReset().mockImplementation(async (path, options) => {
    if (options?.method === "POST") return new Promise((_, fail) => { reject = fail; });
    return path.includes("/health") ? { supervision_ready: true, storage: { state: "critical" }, write_faults: [] } : { items: [{ ...session, reason: "controlled_shutdown" }], total: 1, page: 1, pages: 1 };
  });
  render(<MemoryRouter><RecoveryNotice /></MemoryRouter>);
  expect(await screen.findByText("Ensaio suspenso ao fechar a aplicação")).toBeVisible();
  expect(screen.getByText("Verifique o armazenamento")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Encerrar como interrompido" }));
  fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancelar" }));
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Encerrar como interrompido" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));
  expect(await screen.findByRole("button", { name: "Processando…" })).toBeDisabled();
  reject(new Error("Banco indisponível"));
  await waitFor(() => expect(screen.getByText("Banco indisponível")).toBeVisible());
  expect(screen.getByRole("alertdialog")).toBeVisible();
});
