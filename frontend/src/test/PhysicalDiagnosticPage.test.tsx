import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { api } from "../api";
import { AuthProvider } from "../auth";
import DevicesDiscoveryPage from "../pages/DevicesDiscoveryPage";

vi.mock("../api", async () => {
  const actual = await vi.importActual<any>("../api");
  return {
    ...actual,
    api: vi.fn(async (path: string) => {
      if (path === "/auth/me") {
        return { id: 1, name: "Admin", email: "admin@example.com", role: "admin" };
      }
      if (path === "/devices") {
        return [{ id: 1, name: "AT4532", protocol: "at4532_serial", connection_type: "serial", port: "COM5", baud_rate: 19200, active: true }];
      }
      if (path.includes("/status")) return { connected: false };
      if (path === "/hardware/discovery") {
        return [{
          port: "COM2",
          description: "USB-SERIAL CH340",
          vid: 0x1a86,
          pid: 0x7523,
          association_status: "ambiguous",
          association_candidates: [{ device_id: 1, device_name: "AT4532", matched_by: "vid_pid_candidate" }],
          status: "available",
          status_message: "Porta disponível",
          identification_status: "possible_at4532",
          confidence: "low",
          driver_status: "installed",
          driver_message: "Porta enumerada",
          suggested_device: "Conversor CH340; AT4532 apenas como candidato",
        }];
      }
      if (path === "/hardware/serial-diagnostic/open") {
        return {
          session_id: "engineering-session",
          port_open: true,
          bytes_received: 0,
          elapsed_ms: 2,
          timeout: false,
          raw_hex: "",
          raw_ascii: "",
          parameters: { data_bits: 8, parity: "N", stop_bits: 1 },
          parameters_source: "engineering_assumption",
          physical_validation: "pending",
        };
      }
      if (path === "/devices/1/protocol-probe") {
        return {
          device_id: 1,
          result: "passed_with_warning",
          physical_validation: "pending",
          stages: [
            { key: "identity", label: "Identidade", status: "warning", message: "*IDN? não respondeu; validação funcional continuará" },
            { key: "protocol", label: "Protocolo", status: "passed", message: "Resposta validada" },
          ],
          transactions: [{
            command_name: "identity",
            vendor_documented: true,
            source: "https://www.anbai.cn/app_file/products/AT4532/ug_en_AT4532.pdf",
            section: "9.5.5",
            tx_ascii: "*IDN?\\n",
            tx_hex: "2A 49 44 4E 3F 0A",
            timestamp_tx: "2026-08-11T12:00:00Z",
            rx_ascii: "AT4532,A6,SN,Applent\\n",
            rx_hex: "41 54",
            timestamp_rx: "2026-08-11T12:00:00Z",
            elapsed_ms: 2,
            bytes_received: 24,
            parsed: {},
          }, {
            command_name: "measurements",
            vendor_documented: true,
            source: "https://www.gwinstek.com/en-US/download/downloadFile/11551",
            section: "NUMeric Commands",
            tx_ascii: ":NUMERIC:NORMAL:VALUE?\\r\\n",
            tx_hex: "3A 4E",
            timestamp_tx: "2026-08-11T12:00:01Z",
            rx_ascii: "126.86,2.0199,256.07,256.25,59.989,0.9993,-9.5985,59.988\\r\\n",
            rx_hex: "31 32 36",
            timestamp_rx: "2026-08-11T12:00:01Z",
            elapsed_ms: 3,
            bytes_received: 62,
            parsed: {
              number_requested: 8,
              number_reported: 8,
              headers_requested: ["U", "I", "P", "S", "FU", "LAMBDA", "Q", "FI"],
              headers_reported: ["U", "I", "P", "S", "FU", "LAMBDA", "Q", "FI"],
              raw_values: { U: "126.86", Q: "-9.5985" },
              parsed_values: { Vrms: 126.86, Irms: 2.0199, P: 256.07, VA: 256.25, VHz: 59.989, PF: 0.9993, VAR: -9.5985, IHz: 59.988 },
            },
          }],
        };
      }
      return [];
    }),
  };
});

test("envia protocolo oficial somente após confirmação explícita", async () => {
  const user = userEvent.setup();
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
  localStorage.setItem("thermopower.token", "test-token");
  render(<MemoryRouter><AuthProvider><DevicesDiscoveryPage /></AuthProvider></MemoryRouter>);

  await user.click(await screen.findByRole("button", { name: /Testar identificação/ }));
  expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining("*IDN?"));
  expect((await screen.findAllByText("vendor_documented")).length).toBe(2);
  expect(screen.getByText("*IDN?\\n")).toBeInTheDocument();
  expect(screen.getByText("ATENÇÃO")).toBeInTheDocument();
  expect(screen.getByText(/validação funcional continuará/)).toBeInTheDocument();
  expect(screen.getByText("Comparação GPM-8213 / PowerMeterSeries")).toBeInTheDocument();
  expect(screen.getByText(/HEADER reportado: U, I, P, S, FU, LAMBDA, Q, FI/)).toBeInTheDocument();
  expect(screen.getAllByText("-9.5985").length).toBeGreaterThan(0);
  const call = vi.mocked(api).mock.calls.find(([path]) => path === "/devices/1/protocol-probe");
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({
    mode: "identity",
    operator_confirmed: true,
  });
  confirmSpy.mockRestore();
});

test("mostra identidade ambígua e diagnóstico serial estritamente read-only", async () => {
  localStorage.setItem("thermopower.token", "test-token");
  render(<MemoryRouter><AuthProvider><DevicesDiscoveryPage /></AuthProvider></MemoryRouter>);

  expect(await screen.findByText("Identidade ambígua")).toBeInTheDocument();
  expect(await screen.findByText("Diagnóstico serial avançado")).toBeInTheDocument();
  expect(screen.getByText(/READ-ONLY · NENHUM COMANDO É ENVIADO/)).toBeInTheDocument();
  expect(screen.getByPlaceholderText("AT4532: 19200")).toBeInTheDocument();
});

test("mantém parâmetros desconhecidos e exige consentimento explícito para 8-N-1", async () => {
  const user = userEvent.setup();
  localStorage.setItem("thermopower.token", "test-token");
  render(<MemoryRouter><AuthProvider><DevicesDiscoveryPage /></AuthProvider></MemoryRouter>);

  await screen.findByText("Diagnóstico serial avançado");
  const dataBits = screen.getByLabelText("Data bits");
  const parity = screen.getByLabelText("Parity");
  const stopBits = screen.getByLabelText("Stop bits");
  const openButton = screen.getByRole("button", { name: "Abrir porta em modo read-only" });

  expect(dataBits).toHaveValue("");
  expect(dataBits).not.toHaveValue("5");
  expect(parity).toHaveValue("");
  expect(stopBits).toHaveValue("");
  expect(dataBits).not.toBeRequired();
  expect(parity).not.toBeRequired();
  expect(stopBits).not.toBeRequired();
  expect(openButton).toBeDisabled();

  await user.selectOptions(screen.getByLabelText("Porta"), "COM2");
  await user.type(screen.getByPlaceholderText("AT4532: 19200"), "19200");
  await user.type(screen.getByLabelText(/^Timeout do diagnóstico/), "1.25");
  await user.type(screen.getByLabelText(/^Read timeout do diagnóstico/), "4.5");
  await user.click(screen.getByRole("checkbox", { name: /Usar 8 data bits/ }));

  expect(screen.getByText("8-N-1 NÃO FOI CONFIRMADO PARA ESTE INSTRUMENTO.")).toBeInTheDocument();
  expect(openButton).toBeEnabled();
  await user.click(openButton);

  expect(await screen.findByText(/Hipótese de engenharia/)).toBeInTheDocument();
  expect(screen.getByText(/validação física: pending/)).toBeInTheDocument();
  const openCall = vi.mocked(api).mock.calls.find(([path]) => path === "/hardware/serial-diagnostic/open");
  expect(openCall).toBeDefined();
  const payload = JSON.parse(String(openCall?.[1]?.body));
  expect(payload).toMatchObject({
    data_bits: null,
    parity: null,
    stop_bits: null,
    use_engineering_assumption_8n1: true,
    timeout_s: 1.25,
    read_timeout_s: 4.5,
  });
});
