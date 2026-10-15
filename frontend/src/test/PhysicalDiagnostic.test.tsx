import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { SupportButton } from "../components/SupportButton";

const download = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));
vi.mock("../api", () => ({ download }));

test("exporta o diagnóstico físico completo em uma única requisição", async () => {
  render(<SupportButton physical label="Exportar diagnóstico físico completo" />);
  await userEvent.click(screen.getByRole("button", { name: "Exportar diagnóstico físico completo" }));
  expect(download).toHaveBeenCalledTimes(1);
  expect(download).toHaveBeenCalledWith("/support/physical-package?", expect.stringMatching(/\.zip$/), expect.objectContaining({ signal: expect.any(AbortSignal), maxBytes: 24 * 1024 * 1024 }));
});

test("limita espera mesmo se o download não responder e oferece coleta local", async () => {
  vi.useFakeTimers();
  download.mockImplementationOnce(() => new Promise(() => {}));
  try {
    render(<SupportButton physical />);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("button")).toBeDisabled();
    await act(() => vi.advanceTimersByTimeAsync(20_001));
    expect(screen.getByRole("button")).toBeEnabled();
    expect(screen.getByRole("alert")).toHaveTextContent("20 segundos");
    expect(screen.getByRole("alert")).toHaveTextContent("export-local-diagnostic.ps1");
    expect(download.mock.lastCall?.[2].signal.aborted).toBe(true);
  } finally { vi.useRealTimers(); }
});

test("desmontar cancela a requisição pendente", async () => {
  download.mockImplementationOnce(() => new Promise(() => {}));
  const view = render(<SupportButton physical />);
  fireEvent.click(screen.getByRole("button"));
  const signal = download.mock.lastCall?.[2].signal;
  await act(() => view.unmount());
  expect(signal.aborted).toBe(true);
});
