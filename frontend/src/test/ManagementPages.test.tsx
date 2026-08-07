import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { AuthProvider } from "../auth";
import { ChannelsPage, EventsPage } from "../pages/ManagementPages";
import DevicesDiscoveryPage from "../pages/DevicesDiscoveryPage";

vi.mock("../api", async () => {
  const actual = await vi.importActual<any>("../api");
  return { ...actual, api: vi.fn(async (path: string) => {
    if (path === "/devices") return [{ id: 1, name: "Bancada", protocol: "simulator", connection_type: "simulator", baud_rate: 115200, active: true }];
    if (path === "/runtime") return { virtual_lab: true, version: "0.5.0-beta", banner: "LABORATÓRIO VIRTUAL" };
    if (path === "/hardware/discovery") return [{ source: "virtual", simulated: true, port: "COM90", product: "Virtual AT4532", status: "available", status_message: "Porta virtual disponível", association_status: "unassociated", suggested_device: "Virtual Applent AT4532", confidence: "high", validation_states: { identity_confirmed: false, protocol_validated: false, homologated: false } }];
    if (path === "/hardware/diagnostic/preview") return { consent: "Este pacote contém apenas informações técnicas dos dispositivos e do aplicativo.", snapshots: [], diffs: [], excluded: ["senhas"] };
    if (path.includes("/status")) return { connected: false };
    if (path.includes("/channels")) return Array.from({ length: 16 }, (_, index) => ({ id: index + 1, device_id: 1, channel: index + 1, name: `Sensor ${index + 1}`, enabled: index < 8, sensor_type: "K", unit: "°C", correction_offset: 0, warning_limit: 70, critical_limit: 80, color: "#3667E9" }));
    if (path.startsWith("/events")) return { items: [{ id: 1, timestamp: "2026-08-01T15:00:00Z", level: "info", category: "connection", message: "Equipamento conectado", device_id: 1 }], page: 1, page_size: 40, total: 1, pages: 1 };
    return [];
  }) };
});

test("lista os 16 canais configuráveis", async () => {
  render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><AuthProvider><ChannelsPage/></AuthProvider></MemoryRouter>);
  expect(await screen.findByText("Sensor 16")).toBeInTheDocument();
  expect(screen.getAllByText("80.0 °C")).toHaveLength(16);
});

test("apresenta eventos retornados pelos filtros", async () => {
  render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><AuthProvider><EventsPage/></AuthProvider></MemoryRouter>);
  expect(await screen.findByText("Equipamento conectado")).toBeInTheDocument();
  expect(screen.getByText("connection")).toBeInTheDocument();
});

test("distingue USB virtual, protocolo pendente e exibe laboratório somente no modo virtual", async () => {
  render(<MemoryRouter><AuthProvider><DevicesDiscoveryPage/></AuthProvider></MemoryRouter>);
  expect(await screen.findByText(/LABORATÓRIO VIRTUAL · VERSÃO 0\.5\.0-beta — dados simulados/i)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "USB detectados" }));
  expect(await screen.findByText("Virtual AT4532")).toBeInTheDocument();
  expect(screen.getByText("Simulado")).toBeInTheDocument();
  expect(screen.getByText("Protocolo não validado")).toBeInTheDocument();
  expect(screen.queryByText("Homologado")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Laboratório virtual" }));
  expect(await screen.findByText("Painel de plug / unplug")).toBeInTheDocument();
});

test("mostra prévia e exige consentimento para exportar diagnóstico", async () => {
  render(<MemoryRouter><AuthProvider><DevicesDiscoveryPage/></AuthProvider></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "Diagnóstico" }));
  fireEvent.click(screen.getByRole("button", { name: "Visualizar dados" }));
  expect(await screen.findAllByText(/Este pacote contém apenas informações técnicas/)).toHaveLength(2);
  expect(screen.getByRole("button", { name: /Exportar pacote/ })).toBeDisabled();
});
