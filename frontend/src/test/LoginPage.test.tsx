import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";
import { AuthProvider } from "../auth";
import LoginPage from "../pages/LoginPage";

test("autentica o usuário e armazena o token", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ access_token: "token-de-teste", user: { id: 1, name: "Admin", email: "admin@demo.thermopower.com", role: "admin" } }),
  }));
  render(<MemoryRouter initialEntries={["/login"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><AuthProvider><Routes><Route path="/login" element={<LoginPage/>}/><Route path="/" element={<div>Dashboard autenticado</div>}/></Routes></AuthProvider></MemoryRouter>);
  expect(screen.getByRole("heading", { name: "Bem-vindo de volta" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /Entrar no sistema/i }));
  expect(await screen.findByText("Dashboard autenticado")).toBeInTheDocument();
  expect(localStorage.getItem("thermopower.token")).toBe("token-de-teste");
});

test("exibe falha de autenticação", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({ error: { message: "E-mail ou senha inválidos" } }) }));
  render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><AuthProvider><LoginPage/></AuthProvider></MemoryRouter>);
  await userEvent.click(screen.getByRole("button", { name: /Entrar no sistema/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent("E-mail ou senha inválidos");
});
