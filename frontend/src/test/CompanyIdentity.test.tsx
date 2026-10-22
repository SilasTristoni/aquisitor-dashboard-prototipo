import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { api } from "../api";
import CompanyIdentityPage from "../pages/CompanyIdentityPage";
import { CompanyMark } from "../components/CompanyIdentity";

vi.mock("../api", () => ({ api: vi.fn() }));
const neutral = { identity_id: null, company_name: "", laboratory: "", logo: null };

test("admin edits persistent company identity and gets server validation errors", async () => {
  vi.mocked(api).mockReset().mockResolvedValue(neutral);
  render(<CompanyIdentityPage />);
  await waitFor(() => expect(api).toHaveBeenCalledWith("/company-identity"));
  fireEvent.change(screen.getByLabelText("Nome da empresa"), { target: { value: "Empresa DEMO" } });
  vi.mocked(api).mockResolvedValue({ ...neutral, company_name: "Empresa DEMO" });
  fireEvent.click(screen.getByRole("button", { name: "Salvar identificação" }));
  expect(await screen.findByRole("status")).toHaveTextContent("salva");
  expect(api).toHaveBeenLastCalledWith("/company-identity", expect.objectContaining({ method: "PUT", body: JSON.stringify({ company_name: "Empresa DEMO", laboratory: "" }) }));
  vi.mocked(api).mockRejectedValue(new Error("Arquivo de imagem inválido."));
  fireEvent.change(screen.getByLabelText("Logotipo PNG ou JPEG"), { target: { files: [new File(["invalid"], "logo.png", { type: "image/png" })] } });
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Arquivo de imagem inválido."));
});

test("neutral identity renders no company and remote images are never fetched", () => {
  const { rerender, container } = render(<CompanyMark identity={neutral} />);
  expect(container).toBeEmptyDOMElement();
  rerender(<CompanyMark identity={{ ...neutral, company_name: "Empresa DEMO", logo: "https://external.invalid/logo" }} />);
  expect(screen.getByText("Empresa DEMO")).toBeVisible();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
});
