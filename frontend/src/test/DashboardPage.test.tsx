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
const now = Date.now();
const temperatures = Array<number | null>(32).fill(null);
[23.2, 23.7, 23.8, 26.5, 35.6, 28.1, 24.4, 21.9].forEach((value, index) => { temperatures[index + 24] = value; });
vi.mock("../hooks/useLive", () => ({ useLive: () => ({ connection: "connected", lastAlert: null, setReadings: vi.fn(), readings: [
  { timestamp: new Date(now - 2000).toISOString(), device_id: 2, source_role: "electrical", raw_power: 17.7, raw_power_unit: "W", power_w: 17.7, temperatures_c: [], quality: "good" },
  { timestamp: new Date(now - 1000).toISOString(), device_id: 2, source_role: "electrical", raw_power: 17.9, raw_power_unit: "W", power_w: 17.9, temperatures_c: [], quality: "good" },
  { timestamp: new Date(now - 1500).toISOString(), device_id: 1, source_role: "temperature", raw_power: null, raw_power_unit: "W", power_w: null, temperatures_c: temperatures, channel_quality: temperatures.map((value) => value == null ? "unknown_unavailable" : "good"), quality: "good" },
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
  expect(screen.getAllByText("17.9 W").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("23.2°")).toBeInTheDocument();
  expect(screen.getByText("35.6 °C")).toBeInTheDocument();
  expect(screen.getByText("CH32")).toBeInTheDocument();
  expect(screen.queryByText("0.0 °C")).not.toBeInTheDocument();
  expect(screen.getByText("WebSocket conectado")).toBeInTheDocument();
});
