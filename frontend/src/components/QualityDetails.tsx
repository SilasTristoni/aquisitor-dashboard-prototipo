import { InfoTip } from "./ui";

export type SourceQuality = {
  role: string; count: number; expected_count?: number;
  expected_interval_seconds?: number; observed_interval_seconds?: number;
  frequency_reduced?: boolean; has_issue?: boolean; reasons?: string[];
};

const interval = (value?: number) => value == null ? "Aguardando leituras" : `${value.toLocaleString("pt-BR", { maximumFractionDigits: 2 })} s`;

export function QualityDetails({ sources = [], electrical = 0, thermal = 0 }: {
  sources?: SourceQuality[]; electrical?: number; thermal?: number;
}) {
  return <details className="quality-details"><summary>Ver detalhes da integridade</summary>
    <p>Elétrica: {electrical} leituras · Térmica: {thermal} leituras</p>
    {sources.map((source, index) => <div key={index} className="quality-source">
      <strong>{source.role === "temperature" ? "Fonte térmica" : "Fonte elétrica"}</strong>
      <span>Intervalo configurado: {interval(source.expected_interval_seconds)} · Observado: {interval(source.observed_interval_seconds)}</span>
      <span>{source.frequency_reduced ? "Frequência reduzida. As leituras existentes continuam válidas." : !source.count ? "Nenhuma amostra neste período. Verifique a fonte e a janela escolhida." : source.has_issue ? "Há amostras ausentes neste período. Confira o início e o fim da aquisição." : "Frequência dentro do esperado."}</span>
    </div>)}
    <p className="hint">Campos ausentes não invalidam as demais grandezas. Uma lacuna indica falta de amostras; o diagnóstico permite distinguir timeout de desconexão. <InfoTip text="Open indica termopar aberto ou sem leitura. Dado inválido é uma resposta que não pode ser usada como medição; não é substituído por zero." /></p>
  </details>;
}
