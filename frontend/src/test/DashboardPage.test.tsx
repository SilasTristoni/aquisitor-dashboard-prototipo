import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { vi } from "vitest";
import DashboardPage from "../pages/DashboardPage";

vi.mock("recharts", () => {
  const Container = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  const Chart = () => <div data-testid="chart" />;
  const Primitive = () => null;
  return { Area: Primitive, AreaChart: Chart, CartesianGrid: Primitive, Legend: Primitive, Line: Primitive, LineChart: Chart, ReferenceLine: Primitive, ResponsiveContainer: Container, Tooltip: Primitive, XAxis: Primitive, YAxis: Primitive };
});
const now = Date.now();
const temperatures = Array<number | null>(32).fill(null);
[21.79, 21.62, 21.38, 21.34, 21.57, 21.71, 21.90, 22.19].forEach((value, index) => { temperatures[index + 24] = value; });
vi.mock("../hooks/useLive", () => ({ useLive: () => ({ connection: "connected", lastAlert: null, setReadings: vi.fn(), readings: [
  { timestamp: new Date(now - 1000).toISOString(), device_id: 2, source_role: "electrical", raw_power: 17.688, raw_power_unit: "W", power_w: 17.688, temperatures_c: [], quality: "missing" },
  { timestamp: new Date(now - 1500).toISOString(), device_id: 1, source_role: "temperature", raw_power: null, raw_power_unit: "W", power_w: null, temperatures_c: temperatures, channel_quality: temperatures.map((value) => value == null ? "open_sensor" : "good"), quality: "good" },
] }) }));
vi.mock("../api", async () => {
  const actual = await vi.importActual<any>("../api");
  return { ...actual, api: vi.fn(async (path: string) => {
    if (path === "/devices") return [
      { id: 1, name: "AT4532 LAB", protocol: "at4532_serial", connection_type: "serial", baud_rate: 19200, active: true },
      { id: 2, name: "GPM-8213 GES913349", protocol: "gpm8213_serial", connection_type: "usb", baud_rate: 9600, active: true },
    ];
    if (path.startsWith("/sessions")) return { items: [], page: 1, page_size: 10, total: 0, pages: 0 };
    if (path.includes("/status")) return { state: "connected", connected: true };
    return {};
  }) };
});

test("combina potência do GPM e temperatura do AT sem fabricar zero", async () => {
  render(<DashboardPage/>);
  expect(await screen.findAllByText("AT4532 LAB")).not.toHaveLength(0);
  expect(screen.getAllByText("17.7 W").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("21.8°")).toBeInTheDocument();
  expect(screen.getByText("21.7 °C")).toBeInTheDocument();
  expect(screen.getByText("22.2 °C")).toBeInTheDocument();
  expect(screen.getByText("8 canais com leitura")).toBeInTheDocument();
  expect(screen.getAllByText("T32").length).toBeGreaterThanOrEqual(1);
  expect(screen.queryByText("0.0 °C")).not.toBeInTheDocument();
  expect(screen.getByText(/Atualização ao vivo conectada/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Início da sessão" })).toHaveClass("active");
  expect(screen.getByText("Sincronização: ativa")).toBeInTheDocument();
});
