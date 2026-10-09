import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { SessionSharing } from "../components/SessionSharing";
import { SessionAnnotations } from "../components/SessionAnnotations";
import { groupChartEvents, ResultEvents } from "../components/ResultEvents";

const mocks = vi.hoisted(() => ({ api: vi.fn(), user: { role: "operator", id: 2 } }));
vi.mock("../api", async () => ({ ...await vi.importActual("../api"), api: mocks.api }));
vi.mock("../auth", () => ({ useAuth: () => ({ user: mocks.user }) }));

test("compartilhamento começa compacto, agrupa permissões e permite copiar e revogar", async () => {
  const item = { id: 7, path: "/compartilhado#abc", status: "active", access_count: 0, creator_name: "Operador" };
  let created = false;
  mocks.api.mockImplementation((_path: string, options?: RequestInit) => {
    if (options?.method === "POST") { created = true; return Promise.resolve(item); }
    if (options?.method === "DELETE") { item.status = "revoked"; return Promise.resolve(); }
    return Promise.resolve({ items: created ? [item] : [] });
  });
  render(<SessionSharing sessionId={13} />);
  await screen.findByText("Nenhum compartilhamento ativo");
  expect(screen.getByRole("button", { name: "Gerar link" })).not.toBeVisible();
  await userEvent.click(screen.getByText("Compartilhar resultado", { exact: true }));
  const group = screen.getByRole("group", { name: "Permissões do link" });
  expect(within(group).getAllByRole("checkbox")).toHaveLength(4);
  await userEvent.click(screen.getByRole("checkbox", { name: "PDF" }));
  await userEvent.click(screen.getByRole("button", { name: "Gerar link" }));
  await screen.findByText("Link criado", { exact: true });
  const request = mocks.api.mock.calls.find(([, options]) => options?.method === "POST");
  expect(JSON.parse(request?.[1].body).permissions).toEqual({ graphs: true, pdf: true, xlsx: false, csv: false });
  expect(screen.getByRole("button", { name: "Copiar link" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Gerar link" })).not.toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Revogar" }));
  await screen.findByText("Revogado");
});

test("eventos mostram tipo, autor e ações apenas do operador autor", async () => {
  const items = [1, 2].map((id) => ({ id, created_by: id, timestamp: "2026-09-08T13:10:00Z", title: `Evento ${id}`, kind: "shutdown", description: "Descrição longa do ensaio", creator_name: `Autor ${id}` }));
  mocks.api.mockReset(); mocks.api.mockResolvedValue({ items, total: 2 });
  render(<SessionAnnotations sessionId={13} initialTime="2026-09-08T10:10:00" onChange={vi.fn()} />);
  await screen.findByText("Evento 2");
  expect(screen.getAllByText("Desligamento")).toHaveLength(3); // two rows and editor option
  expect(screen.getByText("Registrado por Autor 1")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Editar evento" })).toHaveLength(1);
  await userEvent.click(screen.getByRole("button", { name: "Editar evento" }));
  fireEvent.change(screen.getByLabelText("Título do evento"), { target: { value: "Revisado" } });
  await userEvent.click(screen.getByRole("button", { name: "Salvar evento" }));
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/sessions/13/annotations/2", expect.objectContaining({ method: "PUT" })));
});

test("eventos próximos são agrupados e preservam todas as descrições", () => {
  const items = [10, 11, 90].map((second) => ({ timestamp: String(second), title: `Evento ${second}` }));
  const groups = groupChartEvents(items, Number, 100);
  expect(groups.map((group) => group.events.length)).toEqual([2, 1]);
  render(<ResultEvents items={[]} />);
  expect(screen.getByText("Nenhum evento registrado")).toBeInTheDocument();
});
