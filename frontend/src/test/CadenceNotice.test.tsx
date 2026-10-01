import { render, screen } from "@testing-library/react";
import { CadenceNotice } from "../components/CadenceNotice";

test("cadência reduzida válida fica nos detalhes e falhas permanecem destacadas", () => {
  const status = { device_id: 1, state: "connected", connected: true, cadence_degraded: false };
  const view = render(<CadenceNotice status={status} />);
  expect(view.container).toBeEmptyDOMElement();
  view.rerender(<CadenceNotice status={{ ...status, cadence_degraded: true }} />);
  expect(screen.getByText("Cadência térmica reduzida · As medições continuam válidas.")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  for (const failure of [{ persistent_failure: true }, { state: "recovering" }, { last_error: "Porta perdida" }, { last_error: "Dado inválido" }, { state: "interrupted" }]) {
    view.rerender(<CadenceNotice status={{ ...status, cadence_degraded: true, ...failure }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Falha na aquisição térmica");
    expect(screen.queryByText("Cadência térmica reduzida · As medições continuam válidas.")).not.toBeInTheDocument();
  }
});
