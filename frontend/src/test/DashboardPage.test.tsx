import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { vi } from "vitest";
import DashboardPage from "../pages/DashboardPage";

vi.mock("recharts", () => {
  const Container = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  const Chart = () => <div data-testid="chart" />;
  const Primitive = () => null;
  return { Area: Primitive, AreaChart: Chart, CartesianGrid: Primitive, Line: Primitive, LineChart: Chart, ReferenceLine: Primitive, ResponsiveContainer: Container, Tooltip: Primitive, XAxis: Primitive, YAxis: Primitive };
});
vi.mock("../hooks/useLive", () => ({ useLive: () => ({ connection: "connected", lastAlert: null, setReadings: vi.fn(), readings: [{ timestamp: new Date().toISOString(), device_id: 1, session_id: 2, raw_power: 850000, raw_power_unit: "mW", power_w: 850, temperatures_c: [31,32,33,34,35,36,37,38], quality: "good" }] }) }));
vi.mock("../api", async () => {
  const actual = await vi.importActual<any>("../api");
  return { ...actual, api: vi.fn(async (path: string) => {
    if (path === "/devices") return [{ id: 1, name: "Aquisitor simulado", protocol: "simulator", connection_type: "simulator", baud_rate: 115200, active: true }];
    if (path.startsWith("/sessions")) return { items: [], page: 1, page_size: 10, total: 0, pages: 0 };
    if (path.includes("/status")) return { state: "connected", connected: true };
    return {};
  }) };
});

test("renderiza indicadores e os 16 canais do dashboard", async () => {
  render(<DashboardPage/>);
  expect(await screen.findByText("Aquisitor simulado")).toBeInTheDocument();
  expect(screen.getAllByText("850.0 W").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("T16")).toBeInTheDocument();
  expect(screen.getAllByText("Conectado").length).toBeGreaterThanOrEqual(1);
});
