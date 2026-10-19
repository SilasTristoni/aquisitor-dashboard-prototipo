import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { api } from "../api";
import { SessionSharing } from "../components/SessionSharing";
import { PortalConfiguration } from "../components/PortalConfiguration";

vi.mock("../api", () => ({ api: vi.fn(), formatDate: (value: string) => value || "—" }));
const mockApi = vi.mocked(api);
const configured = { configured: true, url: "https://api.example.test", installation_id: "lab-a", managed_by_environment: false, can_configure: false };
const link = "https://viewer.example.test/compartilhado#synthetic-token";
const item = { id: 1, path: "/compartilhado#synthetic-token", public_url: link, status: "active", portal_origin: configured.url, permissions: { graphs: true, csv: true }, allowed_permissions: { graphs: true, csv: true } };

beforeEach(() => { mockApi.mockReset(); });

test("publica filtros explícitos e mostra o link HTTPS retornado pelo portal", async () => {
  let published = false;
  mockApi.mockImplementation(async (path, options) => {
    if (path === "/results-portal/configuration") return configured;
    if (options?.method === "POST") { published = true; return item; }
    return { items: published ? [item] : [], pages: 1 };
  });
  render(<SessionSharing sessionId={42} channels={[25, 32]} includePower={false} />);
  const publish = await screen.findByRole("button", { name: "Publicar e gerar link" });
  await waitFor(() => expect(publish).toBeEnabled());
  fireEvent.click(screen.getByText("Compartilhar resultado"));
  fireEvent.click(publish);
  await waitFor(() => expect(screen.getByLabelText("Link compartilhável")).toHaveValue(link));
  const request = mockApi.mock.calls.find(([, options]) => options?.method === "POST")!;
  expect(request[0]).toBe("/sessions/42/shares");
  const body = JSON.parse(request[1]!.body as string);
  expect(body).toMatchObject({ destination: "portal", channels: [25, 32], include_power: false, permissions: { graphs: true, pdf: false, csv: false } });
  expect(body.publication_id).toMatch(/^[a-f0-9-]{36}$/);
});

test("portal sem configuração explica dependência e permite link local", async () => {
  mockApi.mockImplementation(async path => path === "/results-portal/configuration" ? { ...configured, configured: false } : { items: [], pages: 1 });
  render(<SessionSharing sessionId={42} />);
  expect(await screen.findByText(/Os relatórios locais continuam disponíveis/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Publicar e gerar link" })).toBeDisabled();
  fireEvent.click(screen.getByText("Compartilhar resultado"));
  fireEvent.change(screen.getByLabelText("Destino do resultado"), { target: { value: "local" } });
  expect(screen.getByRole("button", { name: "Gerar link local" })).toBeEnabled();
});

test("publicação incerta reenvia o registro existente somente após ação explícita", async () => {
  let complete = false;
  mockApi.mockImplementation(async (path, options) => {
    if (path === "/results-portal/configuration") return configured;
    if (options?.method === "POST") { complete = true; return item; }
    return { items: [complete ? item : { ...item, status: "pending", path: null, public_url: null, can_retry: true }], pages: 1 };
  });
  render(<SessionSharing sessionId={42} />);
  const retry = await screen.findByRole("button", { name: "Reenviar publicação" });
  expect(mockApi.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(0);
  expect(screen.queryByRole("button", { name: "Copiar link" })).not.toBeInTheDocument();
  fireEvent.click(retry);
  await screen.findByRole("button", { name: "Copiar link" });
  expect(mockApi.mock.calls.find(([, options]) => options?.method === "POST")?.[0]).toBe("/sessions/42/shares/1/retry");
});

test("alteração incerta reenvia a mesma política e não oferece downloads ausentes", async () => {
  const desired = { graphs: false, csv: false, pdf: false, xlsx: false };
  mockApi.mockImplementation(async path => path === "/results-portal/configuration" ? configured : { items: [{ ...item, permission_update_pending: { revision: 1, permissions: desired } }], pages: 1 });
  render(<SessionSharing sessionId={42} />);
  fireEvent.click(await screen.findByText("Alterar permissões"));
  const submit = screen.getByRole("button", { name: "Reenviar alteração pendente" });
  expect(screen.getAllByLabelText("PDF").at(-1)).toBeDisabled();
  fireEvent.click(submit);
  await waitFor(() => expect(mockApi.mock.calls.some(([, options]) => options?.method === "PATCH")).toBe(true));
  expect(JSON.parse(mockApi.mock.calls.find(([, options]) => options?.method === "PATCH")![1]!.body as string)).toEqual(desired);
});

test("administrador salva credencial sem mantê-la em armazenamento do navegador", async () => {
  const onStatus = vi.fn();
  mockApi.mockResolvedValue({ ...configured, can_configure: true });
  render(<PortalConfiguration onStatus={onStatus} />);
  fireEvent.click(await screen.findByText("Configuração administrativa do portal"));
  const input = screen.getByLabelText("Credencial da instalação");
  fireEvent.change(input, { target: { value: "synthetic-secret-12345678901234567890" } });
  fireEvent.click(screen.getByRole("button", { name: "Salvar configuração" }));
  await screen.findByText(/Configuração salva no cofre do Windows/);
  expect(input).toHaveValue("");
  expect(localStorage.length).toBe(0);
});
