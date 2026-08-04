# Plano de implementação — relatórios por período, descoberta USB e pacote Windows

## Estado atual preservado

O ThermoPower Monitor já separa aquisição, persistência e apresentação. A integração física
continua atrás de `DeviceAdapter`; o simulador, os importadores AT4532/GPM-8213, as sessões,
os snapshots de configuração de canais e os relatórios legados por sessão devem continuar
funcionando. As tabelas antigas de medições permanecem como fallback somente para bancos
anteriores à migração dos fluxos independentes.

O relatório existente seleciona uma sessão, sincroniza seus fluxos e monta CSV, XLSX, PDF e
imagem. Esta iteração acrescenta um escopo de período sem remover esse contrato. Os manuais
`docs/AT4532.md`, `docs/GPM8213.md` e `docs/TIME_SYNCHRONIZATION.md` mencionados no briefing
não estão presentes no repositório; portanto, identificação USB e integração serial serão
conservadoras, sem VID/PID, comandos ou capacidades inferidas.

## Consulta e modelo temporal

1. O contrato recebe início e fim ISO 8601, aceitando offset explícito. Datas sem offset são
   interpretadas no fuso solicitado, cujo padrão é `America/Sao_Paulo`.
2. O backend valida `fim > início`, converte limites para UTC e aplica o período máximo
   configurável antes de consultar dados.
3. A seleção parte das sessões que se sobrepõem ao intervalo solicitado e aplica filtros de
   sessão e equipamento. Em seguida, consulta diretamente `temperature_samples`,
   `temperature_channel_values` e `electrical_samples`.
4. Para cada amostra, o timestamp efetivo é `device_timestamp` quando solicitado e
   disponível; caso contrário, `received_timestamp`. O fallback é individual e fica
   registrado nos indicadores de qualidade.
5. Bancos que ainda contenham somente `measurements` e `temperature_measurements` usam uma
   leitura legada explícita, sem duplicar pontos já migrados.

## Sessões concorrentes e sincronização

Cada sessão constitui um segmento independente. Sessões simultâneas são exibidas e
estatisticamente tratadas separadamente, mesmo que pertençam aos mesmos equipamentos. Não há
sincronização, interpolação, integração de energia ou linha contínua atravessando a fronteira
entre sessões. A sincronização temperatura–elétrica usa vizinho mais próximo apenas dentro da
mesma sessão e da tolerância solicitada. Pontos sem par permanecem ausentes; nunca se inventa
zero. `interpolation=visual_only` poderá ligar pequenos intervalos apenas na renderização e
nunca altera estatísticas ou dados persistidos.

## Estatísticas e energia

As estatísticas são calculadas sobre todos os pontos filtrados, antes do downsampling:

- cobertura temporal, quantidade de sessões, amostras, frequência observada, lacunas,
  desconexões, timestamps substituídos e alertas;
- mínimo, máximo, média, mediana, desvio padrão e percentis das grandezas elétricas;
- energia ativa em Wh por integração trapezoidal de potência em timestamps reais, por sessão;
- intervalos maiores que o limite de lacuna calculado/configurado são excluídos da energia e
  contabilizados como dados indisponíveis;
- mínimo, máximo, média e disponibilidade por canal, preservando o nome capturado no snapshot
  de cada sessão. Quando o mesmo canal tiver nomes diferentes, os resultados continuam
  identificados por sessão e também recebem um agregado claramente rotulado.

## Gráficos e redução de pontos

Matplotlib usa o backend não interativo `Agg`. O gráfico principal combina potência no eixo
esquerdo e temperaturas no direito, com quebra visual entre sessões e lacunas. Canais são
divididos em grupos configuráveis, com oito por padrão; potência pode ser repetida como
referência. Gráficos complementares cobrem grandezas elétricas e qualidade.

Para visualização, cada série é reduzida por buckets temporais preservando mínimo, máximo e
média, além das extremidades. Esse algoritmo é determinístico e testável. Estatísticas e
energia nunca usam a série reduzida. PNG e JPEG recebem DPI configurável e metadados mínimos;
o PDF incorpora PNGs de alta resolução, evitando gráficos meramente ilustrativos.

## Persistência e migração

Uma nova migration Alembic tornará `reports.session_id` opcional e acrescentará:

- `scope_type` (`session` ou `period`);
- `period_start`, `period_end` e `timezone`;
- `title`, `filters_json`, `status` e `error_message`;
- os campos existentes `type`, `file_path`, `generated_at` e `generated_by` serão mantidos.

Registros antigos serão preenchidos com `scope_type=session`. A alteração terá caminhos
compatíveis com SQLite (batch mode) e PostgreSQL. Falhas de geração serão auditadas com
`status=failed` e mensagem saneada; artefatos concluídos recebem `status=completed`.

## Contratos HTTP

- `POST /api/v1/reports/period/preview`: resumo JSON, disponibilidade, estatísticas, sessões e
  série reduzida para prévia.
- `POST /api/v1/reports/period/pdf`: relatório multipágina em PDF.
- `POST /api/v1/reports/period/chart.png`: gráfico completo em PNG.
- `POST /api/v1/reports/period/chart.jpeg`: gráfico completo em JPEG.
- `GET /api/v1/hardware/discovery`: portas COM/USB com metadados reportados pelo sistema,
  associação, estado de uso, sugestão conservadora e estado do driver.
- `POST /api/v1/hardware/discovery/associate`: associa uma porta descoberta a um equipamento
  cadastrado, registrando identificadores reais disponíveis.

Downloads usam nome de arquivo saneado e `Content-Disposition` compatível com UTF-8. Períodos
sem dados retornam erro 422 claro; filtros que não existem retornam 404/422 conforme o caso.

## Interface

A página de relatórios terá abas “Por período”, “Por sessão” e “Histórico”. O formulário de
período oferece presets, datas, fuso, filtros, canais, conteúdo, orientação, tema, DPI,
tolerância e limite de tabela. A prévia mostra cobertura, séries reduzidas e avisos antes do
download. A geração comunica as fases de consulta, cálculo, gráfico e documento sem simular
percentuais de trabalho do servidor.

A página de equipamentos passa a descobrir portas sob demanda e em polling moderado enquanto
visível. Cards mostram metadados disponíveis, associação, confiança e avisos de driver/porta.
O cadastro pode selecionar uma porta detectada. O diagnóstico apresenta abertura, leitura,
reconhecimento, frequência, canais e erros em etapas, sem declarar homologação física.

O assistente de primeiro uso conduz: boas-vindas, armazenamento, administrador local,
descoberta, associação/configuração e teste. Ele permanece acessível posteriormente e não
bloqueia o simulador.

## Pacote Windows

O build produzirá o frontend estático, empacotará backend/launcher com PyInstaller e criará o
instalador Inno Setup `ThermoPower-Setup-0.4.0-beta.exe`. Em execução empacotada, o FastAPI
serve a SPA. Banco, logs e relatórios ficam sob `%LOCALAPPDATA%\ThermoPower Monitor`; o
launcher aplica migrations, escolhe porta local livre, inicia o servidor e abre o navegador.
Credenciais de homologação são locais, documentadas e sobrescrevíveis por ambiente — nunca
credenciais de produção.

## Estratégia de testes

- validação completa do contrato temporal, offset/fuso, período máximo e filtros;
- seleção de sessões sobrepostas, concorrência e fallback de timestamp/legado;
- garantia de ausência de sincronização e integração entre sessões;
- estatísticas, energia trapezoidal e exclusão de lacunas;
- downsampling com extremos e quebras preservados;
- PDF/PNG/JPEG reais, cabeçalhos, auditoria concluída/falha e nomes seguros;
- descoberta com portas mockadas, associação por serial/VID/PID/porta, driver ausente e porta
  ocupada;
- componentes de seleção por período, descoberta e assistente;
- regressão integral de backend/frontend, build Vite e configuração Docker.

## Riscos e mitigação

- **Volume:** consulta limitada por período configurável e downsampling só na apresentação.
- **Fuso/DST:** `zoneinfo`, armazenamento UTC e fuso original persistido no relatório.
- **Dados concorrentes:** segmentação obrigatória por sessão e rótulos explícitos.
- **SQLite/PostgreSQL:** migration em batch onde necessário e testes de SQL portável.
- **USB heterogêneo:** campos opcionais, nenhuma identificação por palpite e nenhuma escrita na
  porta durante descoberta.
- **Hardware indisponível:** simulador continua sendo o caminho de aceite; recursos reais ficam
  marcados como “preparados, pendentes de validação física”.
- **Ferramentas Windows ausentes:** scripts falham com instrução acionável e preservam os
  artefatos já gerados; a compilação final é registrada como pendência do ambiente.

## Critérios de aceite

1. Um usuário autenticado gera prévia, gráfico e PDF para um intervalo que cruza múltiplas
   sessões, com filtros e fuso corretos.
2. Estatísticas usam o conjunto integral; gráficos permanecem legíveis em séries extensas.
3. Sessões sobrepostas não são fundidas e lacunas não viram zeros nem energia fictícia.
4. Relatórios antigos por sessão continuam disponíveis e o histórico distingue os escopos.
5. Portas USB/COM são listadas com transparência sobre incerteza, podem ser associadas e
   alimentam o cadastro/diagnóstico.
6. O simulador permite concluir o assistente e validar o produto sem hardware.
7. Migration sobe e desce em SQLite e mantém SQL compatível com PostgreSQL.
8. Testes backend/frontend, lint, typecheck, build e `docker compose config` passam, ressalvada
   indisponibilidade documentada de executáveis externos para gerar o instalador.
9. `legacy/` permanece byte a byte inalterado.
