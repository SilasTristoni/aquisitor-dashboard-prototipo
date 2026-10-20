import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import App from "../App";
import { api } from "../api";

const auth = vi.hoisted(() => ({ role: "admin" as string | null }));
vi.mock("../auth", () => ({ useAuth: () => ({ user: auth.role ? { name: "Synthetic user", role: auth.role } : null, loading: false, logout: vi.fn() }) }));
vi.mock("../api", () => ({ api: vi.fn() }));
vi.mock("../components/HelpMenu", () => ({ HelpMenu: () => null, FirstUseHint: () => null }));
vi.mock("../pages/DashboardPage", () => ({ default: () => <h1>Operação sintética</h1> }));
vi.mock("../pages/SessionsPage", () => ({ default: () => <h1>Sessões sintéticas</h1> }));
vi.mock("../pages/LoginPage", () => ({ default: () => <h1>Login sintético</h1> }));
const mockApi = vi.mocked(api);
const configured = { configured: true, url: "https://api.example.test", installation_id: "synthetic-lab", managed_by_environment: false, can_configure: true };
const secret = "synthetic-credential-for-ui-test-only";
const renderPage = (path = "/portal-externo") => render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>);

beforeEach(() => { auth.role = "admin"; mockApi.mockReset(); mockApi.mockResolvedValue(configured); });

test("administrador abre pelo menu sem consultar ou precisar de sessões", async () => {
  renderPage("/");
  fireEvent.click(await screen.findByRole("link", { name: "Portal externo" }));
  expect(await screen.findByRole("heading", { name: "Portal externo" })).toBeVisible();
  expect(await screen.findByLabelText("URL HTTPS da API do portal")).toBeVisible();
  expect(screen.getByLabelText("URL HTTPS da API do portal")).toHaveValue(configured.url);
  expect(screen.getByLabelText("Identificador da instalação")).toHaveValue(configured.installation_id);
  expect(screen.getByLabelText("Credencial da instalação")).toHaveAttribute("type", "password");
  expect(screen.getByLabelText("Credencial da instalação")).toHaveValue("");
  expect(screen.getByRole("status", { name: "Estado do portal" })).toHaveTextContent("Configurado");
  expect(mockApi.mock.calls.map(([path]) => path)).toEqual(["/results-portal/configuration"]);
});

test.each([["operator", "Operação sintética"], ["viewer", "Sessões sintéticas"], [null, "Login sintético"]])("bloqueia acesso direto para %s", async (role, heading) => {
  auth.role = role;
  renderPage();
  expect(await screen.findByRole("heading", { name: heading! })).toBeVisible();
  expect(screen.queryByRole("link", { name: "Portal externo" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Credencial da instalação")).not.toBeInTheDocument();
  expect(mockApi).not.toHaveBeenCalled();
});

test("salva, limpa credencial, testa conexão e invalida confirmação ao editar", async () => {
  mockApi.mockImplementation(async (_path, options) => options?.method ? configured : { ...configured, configured: false, url: "", installation_id: "" });
  renderPage();
  expect(await screen.findByRole("status", { name: "Estado do portal" })).toHaveTextContent("Não configurado");
  const check = screen.getByRole("button", { name: "Testar conexão com o portal" });
  expect(check).toBeDisabled();
  fireEvent.change(screen.getByLabelText("URL HTTPS da API do portal"), { target: { value: configured.url } });
  fireEvent.change(screen.getByLabelText("Identificador da instalação"), { target: { value: configured.installation_id } });
  const credential = screen.getByLabelText("Credencial da instalação");
  fireEvent.change(credential, { target: { value: secret } });
  fireEvent.click(screen.getByRole("button", { name: "Salvar configuração" }));
  await screen.findByText(/Configuração salva no cofre/);
  expect(credential).toHaveValue("");
  expect(screen.getByRole("status", { name: "Estado do portal" })).toHaveTextContent("Configurado");
  const saved = mockApi.mock.calls.find(([, options]) => options?.method === "PUT")!;
  expect(JSON.parse(saved[1]!.body as string)).toEqual({ url: configured.url, installation_id: configured.installation_id, credential: secret });
  fireEvent.click(check);
  await waitFor(() => expect(screen.getByRole("status", { name: "Estado do portal" })).toHaveTextContent("Conexão validada"));
  expect(mockApi).toHaveBeenCalledWith("/results-portal/check", expect.objectContaining({ method: "POST" }));
  expect(JSON.stringify(localStorage)).not.toContain(secret);
  expect(JSON.stringify(sessionStorage)).not.toContain(secret);
  fireEvent.change(screen.getByLabelText("URL HTTPS da API do portal"), { target: { value: "https://changed.example.test" } });
  expect(check).toBeDisabled();
  expect(screen.getByRole("status", { name: "Estado do portal" })).toHaveTextContent("Configurado");
});

test("erro de conexão é visível e permite nova tentativa", async () => {
  mockApi.mockImplementation(async (_path, options) => { if (options?.method === "POST") throw new Error("Portal indisponível"); return configured; });
  renderPage();
  const check = await screen.findByRole("button", { name: "Testar conexão com o portal" });
  fireEvent.click(check);
  expect(await screen.findByRole("alert")).toHaveTextContent("Portal indisponível");
  expect(screen.getByRole("status", { name: "Estado do portal" })).toHaveTextContent("Erro");
  expect(check).toBeEnabled();
  mockApi.mockResolvedValue(configured);
  fireEvent.click(check);
  await waitFor(() => expect(screen.getByRole("status", { name: "Estado do portal" })).toHaveTextContent("Conexão validada"));
});

test("falha ao salvar limpa o campo protegido e não valida conexão", async () => {
  mockApi.mockImplementation(async (_path, options) => { if (options?.method === "PUT") throw new Error("Não foi possível salvar"); return configured; });
  renderPage();
  const input = await screen.findByLabelText("Credencial da instalação");
  fireEvent.change(input, { target: { value: secret } });
  fireEvent.click(screen.getByRole("button", { name: "Salvar configuração" }));
  await screen.findByRole("alert");
  expect(input).toHaveValue("");
  expect(screen.getByRole("status", { name: "Estado do portal" })).toHaveTextContent("Erro");
});

test("configuração de ambiente mostra identificação sem campo de segredo ou salvar", async () => {
  mockApi.mockResolvedValue({ ...configured, managed_by_environment: true });
  renderPage();
  expect(await screen.findByText(`Identificador da instalação: ${configured.installation_id}`)).toBeVisible();
  expect(screen.queryByLabelText("Credencial da instalação")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Salvar configuração" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Testar conexão com o portal" })).toBeEnabled();
});
