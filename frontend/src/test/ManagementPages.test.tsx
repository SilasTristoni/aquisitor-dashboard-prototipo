import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { AuthProvider } from "../auth";
import { ChannelsPage, EventsPage } from "../pages/ManagementPages";

vi.mock("../api", async () => {
  const actual = await vi.importActual<any>("../api");
  return { ...actual, api: vi.fn(async (path: string) => {
    if (path === "/devices") return [{ id: 1, name: "Bancada", protocol: "simulator", connection_type: "simulator", baud_rate: 115200, active: true }];
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
