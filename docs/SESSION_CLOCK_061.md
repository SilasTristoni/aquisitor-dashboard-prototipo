# Correção incremental — 0.6.1-client-preview

## Evidências e limites da conclusão

Os arquivos de homologação fornecidos foram consultados sem alteração. O XLSX contém
322 leituras elétricas e 11 térmicas exportadas; os horários térmicos avançam em 6 s,
começam aproximadamente 4 min 30 s após o início declarado e terminam depois do fim
declarado da sessão. O PDF individual usa a apresentação antiga. As imagens mostram
as curvas exportadas e o gráfico ao vivo vazio apesar dos indicadores atualizados.

O banco local encontrado contém apenas duas sessões de agosto, não a sessão 8.
Os anexos não trazem o par `device_timestamp`/`received_timestamp`, contagens completas
do banco nem o log de reconexões dessa sessão. Portanto, **não é possível afirmar que
apenas 11 amostras foram persistidas, nem atribuir historicamente esse número a uma
única causa**. Não foram reconstruídos valores ausentes ou alterados dados de produção.

## Causas reproduzíveis e correções

1. **Gráfico vazio por fuso:** SQLite devolvia o início UTC sem sufixo; `Date.parse`
   interpretava esse início como horário local no navegador. O filtro anterior à sessão
   podia excluir três horas de leituras. A API agora explicita UTC, e o frontend
   interpreta datas antigas sem fuso segundo o contrato UTC. O filtro foi preservado.
2. **Gráfico vazio com dados:** linhas alimentadas pela união de fontes tinham um ponto
   ausente em cada leitura da outra fonte. `connectNulls=false` e pontos invisíveis
   interrompiam todas as linhas. Cada linha agora recebe apenas os pontos da sua fonte,
   mantendo valores Open como interrupções e desenhando a primeira leitura isolada.
3. **Relógios diferentes:** o AT traz o relógio do instrumento no frame TCP-32, enquanto
   o GPM usa recebimento. O serviço normaliza aquisição ao vivo, sessão e relatórios
   pelo UTC de recebimento. O timestamp do equipamento e o payload original continuam
   persistidos; ambos os relógios também são exportados nas abas de leituras reais.
   A preferência pelo relógio do equipamento permanece disponível para importações.
4. **Reconexão sem persistência na sessão:** o runtime recriado perdia o vínculo com a
   sessão ativa. A reconexão agora recupera esse vínculo, a pausa e a contagem gravada.
   Esse defeito reproduz a situação “dashboard vivo, sessão sem novas amostras”; não
   há evidência suficiente para afirmar que ocorreu na sessão 8.
5. **Início combinado sem garantia das duas fontes:** agora as duas precisam conectar
   e entregar um novo par válido dentro da tolerância. Só então a sessão é confirmada,
   com origem no primeiro instante desse par. As próprias leituras capturadas são
   gravadas e publicadas uma única vez. Sem par novo, o início falha e nenhuma sessão
   combinada é confirmada. Uma fonte isolada continua utilizável quando explicitamente
   selecionada. A UI informa “Sincronizando fontes...”.

Não foi encontrada deduplicação por timestamp nem descarte proporcional de temperaturas
no flush. A gravação continua uma amostra por leitura real, em lotes transacionais,
com buffer retido quando o commit falha. As sequências e os contadores da sessão agora
continuam entre lotes e reconexões. Contadores de conexão e de sessão são diferenciados.

## Apresentação e documentos

- Eixo X comum, temperaturas à esquerda e potência à direita, sem deslocar uma fonte
  atrasada para 00:00. Esse marco significa início do ensaio, não temperatura zero.
- Escalas positivas partem de zero; negativos são incluídos automaticamente. Margem
  superior de 8% e formatação numérica legível. Todas as ponteiras com leitura aparecem.
- Pico de potência e máximo térmico identificados com marcadores e indicadores de
  valor/tempo, incluindo o canal térmico. O máximo térmico considera o histórico exibido.
- PDF, PNG/JPEG, XLSX e CSV individuais reutilizam a infraestrutura de relatório por
  período. O renderizador antigo foi removido. A planilha usa séries XY independentes,
  coordenadas temporais numéricas e abas de leituras reais sem interpolação.
- Cadência vem do adapter efetivo na conexão e é registrada na sessão. Configurações
  históricas não são reescritas para afirmar 1 Hz retroativamente.
- Relatórios sinalizam início ausente e contagem insuficiente em relação à cadência,
  além das lacunas internas. O texto antigo que prometia mover cada primeira leitura
  para 00:00 foi removido.

Em 120 s a aproximadamente 1 Hz, espera-se cerca de 120 leituras por fonte; em 5 min,
cerca de 300. Pequenas diferenças de fase e latência são normais. Um resultado 322/11
exige investigar aquisição, vínculo e relógios; não deve ser escondido pelo gráfico.

## Validação e reprodução

- `test_session_pipeline.py`: 100 e 120 leituras por fonte pela aquisição real do serviço,
  banco, API, WebSocket e relatórios individuais PDF/PNG/JPEG/XLSX; relógio térmico
  atrasado e repetido, valores iniciais e pico preservados, sequência sem duplicação.
- Testes de início sem reutilizar `latest` antigo, de conexão parcial explícita e de
  reconexão preservando sessão/pausa.
- `SessionClock.test.tsx`: 120 pares com UTC, `-03:00` e UTC sem sufixo, navegador em
  São Paulo, filtro anterior à sessão e dois caminhos SVG com 119 segmentos cada.
- `scripts/review-session-dashboard.mjs`: navegador Chrome real com 120 amostras por
  fonte e nove curvas SVG; evidência sintética, sem acessar portas físicas.
- `scripts/generate-client-preview-fixtures.py`: documentos sintéticos de 120 s para
  revisão visual em `build/session-clock-review`.

O empacotamento exige Ruff, regressões físicas, backend completo, migrations/check,
dependências, frontend completo, Compose e smoke isolado do executável. Neste host,
Compose é o binário oficial standalone v5.5.0, em `build/tools`, com SHA-256 conferido
contra o arquivo da mesma release. Não há daemon Docker neste ambiente.

Para reproduzir a revisão de navegador, instalar Playwright isoladamente:
`npm install --prefix build/browser-tools playwright --no-audit --no-fund`, executar
`npm run build` em `frontend`, gerar as fixtures e executar
`node scripts/review-session-dashboard.mjs` na raiz. Chrome deve estar instalado.

Parser TCP-32, CP936, SCPI, SerialTransport, mapeamento de 32 canais, Open, GPM V1.05
e proteção da cadência não foram alterados. A validação física da **nova versão de
ponta a ponta** permanece pendente no conjunto GPM + AT da cliente.

A saída nova é `engineering/ThermoPower-0.6.1-client-preview.zip`; versões anteriores
não são promovidas, substituídas nem removidas por essa entrega. O ZIP inclui manifesto
SHA-256, identificação do commit de origem e resultados do smoke.
