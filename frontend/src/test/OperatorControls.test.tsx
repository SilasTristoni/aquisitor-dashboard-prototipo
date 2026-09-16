import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { QualityDetails } from "../components/QualityDetails";
import { MeasurementTooltip, SeriesControls } from "../components/SeriesControls";

const series = [{ key: "power", label: "Potência", color: "blue" }, { key: "t25", label: "T25", color: "orange" }];

test("legenda permite ocultar pelo teclado e restaurar todas as séries", async () => {
  function Fixture() {
    const [hidden, setHidden] = useState<string[]>([]);
    return <SeriesControls series={series} hidden={hidden} onChange={setHidden} />;
  }
  render(<Fixture />);
  const power = screen.getByRole("button", { name: "Potência" });
  power.focus(); await userEvent.keyboard("{Enter}");
  expect(power).toHaveAttribute("aria-pressed", "false");
  expect(screen.getByRole("button", { name: "T25" })).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(screen.getByRole("button", { name: "Mostrar todos" }));
  expect(power).toHaveAttribute("aria-pressed", "true");
});

test("tooltip usa somente amostras do instante e não interpola a outra fonte", () => {
  render(<MeasurementTooltip active label={1} rows={[{ axisValue: 1, power: 35 }, { axisValue: 1.15, t25: 70 }]} series={series} formatTime={() => "00:00:01"} />);
  expect(screen.getByText("35 W")).toBeInTheDocument();
  expect(screen.queryByText("70 °C")).not.toBeInTheDocument();
});

test("integridade explica frequência reduzida sem invalidar as leituras existentes", async () => {
  render(<QualityDetails electrical={300} thermal={50} sources={[{ role: "temperature", count: 50, expected_interval_seconds: 1, observed_interval_seconds: 6, frequency_reduced: true }]} />);
  await userEvent.click(screen.getByText("Ver detalhes da integridade"));
  expect(screen.getByText(/Frequência reduzida. As leituras existentes continuam válidas/)).toBeVisible();
  expect(screen.getByText(/Intervalo configurado: 1 s · Observado: 6 s/)).toBeVisible();
});
