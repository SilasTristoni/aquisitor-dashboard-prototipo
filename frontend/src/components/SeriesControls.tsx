export type ChartSeries = { key: string; label: string; color: string };

export function SeriesControls({ series, hidden, onChange }: {
  series: ChartSeries[]; hidden: string[]; onChange: (value: string[]) => void;
}) {
  return <div className="series-controls" aria-label="Séries do gráfico">
    <div className="series-legend">{series.map((item) => <button key={item.key} type="button"
      aria-pressed={!hidden.includes(item.key)} title={`${hidden.includes(item.key) ? "Mostrar" : "Ocultar"} ${item.label}`}
      onClick={() => onChange(hidden.includes(item.key) ? hidden.filter((key) => key !== item.key) : [...hidden, item.key])}>
      <i style={{ background: item.color }} />{item.label}
    </button>)}</div>
    <button className="button small ghost" onClick={() => onChange([])} disabled={!hidden.length}>Mostrar todos</button>
  </div>;
}

export function MeasurementTooltip({ active, label, rows, series, formatTime }: {
  active?: boolean; label?: string | number; rows: Array<Record<string, any>>;
  series: ChartSeries[]; formatTime: (value: number) => string;
}) {
  if (!active || label == null) return null;
  const exact = rows.filter((row) => Math.abs(Number(row.axisValue) - Number(label)) < 0.001);
  return <div className="measurement-tooltip"><strong>{formatTime(Number(label))}</strong>
    {series.map((item) => {
      const value = exact.find((row) => row[item.key] != null)?.[item.key];
      return value == null ? null : <div key={item.key}><i style={{ background: item.color }} /><span>{item.label}</span><b>{Number(value).toLocaleString("pt-BR", { maximumFractionDigits: 2 })} {item.key.includes("power") ? "W" : "°C"}</b></div>;
    })}<small>Leituras no instante indicado, sem interpolação.</small>
  </div>;
}
