import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import Layout from "../components/Layout";

vi.mock("../auth", () => ({ useAuth: () => ({ user: { name: "Consulta", role: "viewer" }, logout: vi.fn() }) }));
vi.mock("../components/HelpMenu", () => ({ HelpMenu: () => null, FirstUseHint: () => null }));

test("viewer navega somente por resultados, sem configuração ou operação", () => {
  render(<MemoryRouter initialEntries={["/sessoes"]}><Layout /></MemoryRouter>);
  expect(screen.getByRole("link", { name: "Sessões" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Comparar sessões" })).toBeInTheDocument();
  for (const name of ["Tempo real", "Equipamentos", "Termopares", "Alertas", "Diagnóstico", "Usuários", "Importar arquivos", "Configuração inicial"]) expect(screen.queryByRole("link", { name })).not.toBeInTheDocument();
});
