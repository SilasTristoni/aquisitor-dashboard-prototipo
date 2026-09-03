import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import DashboardPage from "../pages/DashboardPage";

const apiMock = vi.hoisted(() => vi.fn());
const liveState = vi.hoisted(() => ({ readings: [] as Array<Record<string, unknown>> }));

vi.mock("recharts", () => {
  const Container = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  const Chart = () => <div data-testid="chart" />;
  const Primitive = () => null;
  return {
    CartesianGrid: Primitive,
    Legend: Primitive,
    Line: Primitive,
    LineChart: Chart,
    ResponsiveContainer: Container,
    Tooltip: Primitive,
    XAxis: Primitive,
    YAxis: Primitive,
  };
});

vi.mock("../hooks/useLive", () => ({
  useLive: () => ({
    connection: "connected",
    lastAlert: null,
    readings: liveState.readings,
    setReadings: vi.fn(),
  }),
}));

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ...actual, api: apiMock };
});

const devices = [
  {
    id: 1,
    name: "AT4532 LAB",
    protocol: "at4532_serial",
    connection_type: "serial",
    baud_rate: 19200,
    active: true,
  },
  {
    id: 2,
    name: "GPM-8213 GES913349",
    protocol: "gpm8213_serial",
    connection_type: "usb",
    baud_rate: 9600,
    active: true,
  },
];

type FailedRole = "electrical" | "thermal";

function source(deviceId: number, success: boolean, error: string | null) {
  return {
    device_id: deviceId,
    requested: true,
    success,
    status: success ? "connected" : "error",
    error,
    runtime_status: success
      ? { device_id: deviceId, state: "connected", connected: true }
      : null,
  };
}

function physicalReadings() {
  const timestamp = new Date().toISOString();
  return [
    {
      timestamp,
      received_timestamp: timestamp,
      device_id: 2,
      source_role: "electrical",
      raw_power: 17.688,
      raw_power_unit: "W",
      power_w: 17.688,
      temperatures_c: [],
      quality: "missing",
    },
    {
      timestamp,
      received_timestamp: timestamp,
      device_id: 1,
      source_role: "temperature",
      raw_power: null,
      raw_power_unit: "W",
      power_w: null,
      temperatures_c: [
        ...Array.from({ length: 24 }, () => null),
        21.79, 21.62, 21.38, 21.34, 21.57, 21.71, 21.9, 22.19,
      ],
      channel_quality: [
        ...Array.from({ length: 24 }, () => "open_sensor"),
        ...Array.from({ length: 8 }, () => "good"),
      ],
      quality: "good",
    },
  ];
}

function installApi(failedRole: FailedRole) {
  const failedId = failedRole === "thermal" ? 1 : 2;
  const error = failedRole === "thermal"
    ? "AT4532 fixture connection failed"
    : "GPM-8213 fixture connection failed";
  let attempted = false;

  apiMock.mockImplementation(async (path: string, options?: RequestInit) => {
    if (path === "/devices") return devices;
    if (path === "/sessions" && options?.method === "POST") {
      attempted = true;
      const healthyId = failedRole === "thermal" ? 2 : 1;
      return {
        id: 55,
        device_id: healthyId,
        status: "running",
        started_at: new Date().toISOString(),
        devices: [{
          role: failedRole === "thermal" ? "electrical" : "temperature",
          device: devices.find((device) => device.id === healthyId),
        }],
        connection: {
          electrical: source(2, failedRole !== "electrical", failedRole === "electrical" ? error : null),
          thermal: source(1, failedRole !== "thermal", failedRole === "thermal" ? error : null),
          overall: "partial",
        },
      };
    }
    if (path.startsWith("/sessions")) {
      return { items: [], page: 1, page_size: 10, total: 0, pages: 0 };
    }
    if (path === "/devices/connect-sources") {
      attempted = true;
      return {
        electrical: source(2, failedRole !== "electrical", failedRole === "electrical" ? error : null),
        thermal: source(1, failedRole !== "thermal", failedRole === "thermal" ? error : null),
        overall: "partial",
      };
    }
    if (path.includes("/status")) {
      const deviceId = Number(path.split("/")[2]);
      if (attempted && deviceId === failedId) {
        return { device_id: deviceId, state: "error", connected: false, last_error: error };
      }
      return attempted
        ? { device_id: deviceId, state: "connected", connected: true }
        : { device_id: deviceId, state: "disconnected", connected: false };
    }
    return {};
  });

  return error;
}

beforeEach(() => {
  apiMock.mockReset();
  liveState.readings = [];
});

describe("conexão parcial da dashboard", () => {
  test.each([
    ["thermal", "AT4532 LAB"],
    ["electrical", "GPM-8213 GES913349"],
  ] as const)("mantém a fonte saudável quando %s falha", async (failedRole, failedDevice) => {
    const error = installApi(failedRole);
    render(<DashboardPage />);

    expect(await screen.findAllByText(failedDevice)).not.toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: /Conectar fontes/i }));

    expect(await screen.findByText("Uma fonte falhou; a outra permanece disponível.")).toBeInTheDocument();
    expect(await screen.findByText(error)).toBeInTheDocument();
    await waitFor(() => {
      const connectCall = apiMock.mock.calls.find(([path]) => path === "/devices/connect-sources");
      expect(connectCall).toBeTruthy();
      expect(JSON.parse(String(connectCall?.[1]?.body))).toEqual({
        electrical_device_id: 2,
        thermal_device_id: 1,
      });
    });
    const failedCard = screen.getAllByText(failedDevice)
      .map((element) => element.closest(".source-status"))
      .find(Boolean) as HTMLElement | undefined;
    const healthyDevice = failedRole === "thermal" ? devices[1].name : devices[0].name;
    const healthyCard = screen.getAllByText(healthyDevice)
      .map((element) => element.closest(".source-status"))
      .find(Boolean) as HTMLElement | undefined;
    expect(failedCard).toBeTruthy();
    expect(healthyCard).toBeTruthy();
    expect(within(failedCard!).getByText(/Falha nesta fonte/)).toBeInTheDocument();
    expect(within(healthyCard!).getByText(/^Conectado ·/)).toBeInTheDocument();
  });

  test.each([
    ["thermal", "17.7 W"],
    ["electrical", "21.7 °C"],
  ] as const)("inicia sessão com o ID e a leitura da fonte sobrevivente quando %s falha", async (failedRole, visibleValue) => {
    const error = installApi(failedRole);
    liveState.readings = physicalReadings();
    render(<DashboardPage />);

    expect(await screen.findAllByText("AT4532 LAB")).not.toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: /Iniciar sessão/i }));

    expect(await screen.findByText("Sessão iniciada com a fonte disponível; a outra apresentou falha.")).toBeInTheDocument();
    expect(await screen.findByText(error)).toBeInTheDocument();
    expect(screen.getByText("Em execução")).toBeInTheDocument();
    expect(screen.getAllByText(visibleValue).length).toBeGreaterThan(0);
    const startCall = apiMock.mock.calls.find(
      ([path, options]) => path === "/sessions" && options?.method === "POST",
    );
    expect(startCall).toBeTruthy();
    expect(JSON.parse(String(startCall?.[1]?.body))).toMatchObject({
      electrical_device_id: 2,
      temperature_device_id: 1,
    });
  });

  test("não exibe falha quando somente uma fonte foi solicitada", async () => {
    let connected = false;
    apiMock.mockImplementation(async (path: string, options?: RequestInit) => {
      if (path === "/devices") return devices;
      if (path.startsWith("/sessions")) return { items: [], page: 1, page_size: 10, total: 0, pages: 0 };
      if (path === "/devices/connect-sources") {
        connected = true;
        return {
          electrical: source(2, true, null),
          thermal: {
            device_id: null,
            requested: false,
            success: false,
            status: "not_requested",
            error: null,
            runtime_status: null,
          },
          overall: "partial",
        };
      }
      if (path.includes("/status")) {
        const deviceId = Number(path.split("/")[2]);
        return { device_id: deviceId, state: connected && deviceId === 2 ? "connected" : "disconnected", connected: connected && deviceId === 2 };
      }
      expect(options).toBeDefined();
      return {};
    });
    render(<DashboardPage />);

    await screen.findAllByText("AT4532 LAB");
    fireEvent.change(screen.getByLabelText("Fonte térmica"), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: /Conectar fontes/i }));

    await waitFor(() => expect(apiMock).toHaveBeenCalledWith(
      "/devices/connect-sources",
      expect.objectContaining({ method: "POST" }),
    ));
    expect(screen.queryByText("Uma fonte falhou; a outra permanece disponível.")).not.toBeInTheDocument();
  });
});
