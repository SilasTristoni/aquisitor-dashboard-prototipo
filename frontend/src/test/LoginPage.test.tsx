import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";
import { AuthProvider } from "../auth";
import LoginPage from "../pages/LoginPage";

const buildConfig = {
  version: "0.5.0-beta",
  environment: "windows-beta",
  virtual_lab: false,
  login_prefill: {
    enabled: true,
    email: "homologacao@demo.thermopower.com",
    password: "ThermoPower-HML@2026",
  },
};

test("preenche as credenciais válidas da build e autentica com HTTP 200", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce({ ok: true, status: 200, json: async () => buildConfig })
    .mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        access_token: "token-de-teste",
        user: {
          id: 1,
          name: "Homologação",
          email: buildConfig.login_prefill.email,
          role: "admin",
        },
      }),
    });
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter initialEntries={["/login"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><AuthProvider><Routes><Route path="/login" element={<LoginPage/>}/><Route path="/" element={<div>Dashboard autenticado</div>}/></Routes></AuthProvider></MemoryRouter>);

  expect(await screen.findByDisplayValue(buildConfig.login_prefill.email)).toBeInTheDocument();
  expect(screen.getByDisplayValue(buildConfig.login_prefill.password)).toBeInTheDocument();
  expect(screen.getByText(`ThermoPower Monitor · Versão ${buildConfig.version}`)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /Entrar no sistema/i }));

  expect(await screen.findByText("Dashboard autenticado")).toBeInTheDocument();
  expect(localStorage.getItem("thermopower.token")).toBe("token-de-teste");
  expect(fetchMock).toHaveBeenLastCalledWith(
    "/api/v1/auth/login",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        email: buildConfig.login_prefill.email,
        password: buildConfig.login_prefill.password,
      }),
    }),
  );
});

test("exibe falha de autenticação", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => buildConfig })
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: async () => ({ error: { message: "E-mail ou senha inválidos" } }),
      }),
  );
  render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><AuthProvider><LoginPage/></AuthProvider></MemoryRouter>);

  expect(await screen.findByDisplayValue(buildConfig.login_prefill.email)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /Entrar no sistema/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent("E-mail ou senha inválidos");
});
