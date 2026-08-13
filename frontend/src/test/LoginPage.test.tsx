import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";
import { AuthProvider } from "../auth";
import LoginPage from "../pages/LoginPage";

test("autentica o usuário e armazena o token", async () => {
  const fetchMock = vi.fn().mockImplementation((url: string) => Promise.resolve({
    ok: true,
    status: 200,
    json: async () => url.endsWith("/build-info")
      ? { demo_credentials: { email: "homologacao@demo.thermopower.com", password: "ThermoPower-HML@2026" } }
      : { access_token: "token-de-teste", user: { id: 1, name: "Admin", email: "homologacao@demo.thermopower.com", role: "admin" } },
  }));
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter initialEntries={["/login"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><AuthProvider><Routes><Route path="/login" element={<LoginPage/>}/><Route path="/" element={<div>Dashboard autenticado</div>}/></Routes></AuthProvider></MemoryRouter>);
  expect(screen.getByRole("heading", { name: "Bem-vindo de volta" })).toBeInTheDocument();
  expect(await screen.findByDisplayValue("homologacao@demo.thermopower.com")).toBeInTheDocument();
  expect(screen.getByDisplayValue("ThermoPower-HML@2026")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /Entrar no sistema/i }));
  expect(await screen.findByText("Dashboard autenticado")).toBeInTheDocument();
  expect(localStorage.getItem("thermopower.token")).toBe("token-de-teste");
  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
    email: "homologacao@demo.thermopower.com",
    password: "ThermoPower-HML@2026",
  });
});

test("exibe falha de autenticação", async () => {
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(
    url.endsWith("/build-info")
      ? { ok: true, status: 200, json: async () => ({ demo_credentials: { email: "admin@demo.thermopower.com", password: "ThermoPower@123" } }) }
      : { ok: false, status: 401, json: async () => ({ error: { message: "E-mail ou senha inválidos" } }) },
  )));
  render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><AuthProvider><LoginPage/></AuthProvider></MemoryRouter>);
  expect(await screen.findByDisplayValue("admin@demo.thermopower.com")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /Entrar no sistema/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent("E-mail ou senha inválidos");
});
