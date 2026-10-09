import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { SupportButton } from "../components/SupportButton";

const download = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));
vi.mock("../api", () => ({ download }));

test("exporta o diagnóstico físico completo em uma única requisição", async () => {
  render(<SupportButton physical label="Exportar diagnóstico físico completo" />);
  await userEvent.click(screen.getByRole("button", { name: "Exportar diagnóstico físico completo" }));
  expect(download).toHaveBeenCalledTimes(1);
  expect(download).toHaveBeenCalledWith("/support/physical-package?", expect.stringMatching(/\.zip$/));
});
