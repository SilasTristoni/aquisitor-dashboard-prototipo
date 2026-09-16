# Auditoria de operação — 0.6.3-client-preview

Rodada de 16/09/2026. Referências: anexos da sessão física 14 e capturas fornecidas pela usuária. Os arquivos e as séries reais não foram copiados para o repositório. As evidências visuais geradas em `build/ux-review/` usam exclusivamente fixtures sintéticas.

## Ponto de partida

- Árvore limpa antes das alterações; versão `0.6.2-client-preview`.
- HEAD `c32fdb540535c5506d0819c963913c5efaed3166`; referência local `origin/master` `ae50d552c06dbb7e7829a6fe3c7cda21c344e8f7` (3 commits à frente). Não foi realizado push.
- Baseline física: 57 testes aprovados. Backend: 154 aprovados ao todo; quatro testes com diretórios temporários precisaram ser repetidos fora da restrição do sandbox. Frontend: 30 testes, lint, typecheck e build aprovados.
- Captura anterior: `build/ux-review/before-dashboard.png`. Séries independentes com 120 pontos por fonte e nove curvas verificadas no navegador.

## Cadência térmica: evidência e limite da conclusão

Os horários de recebimento persistidos no XLSX confirmam intervalo térmico sistemático de aproximadamente seis segundos, enquanto a fonte elétrica permanece próxima de um segundo. O problema existe nos dados persistidos; não resulta do eixo visual nem da diferença entre relógio do instrumento e computador.

Na versão anterior, qualquer `SerialTransportError` durante leitura contínua executava fechamento, espera e reconexão. Para o AT com identidade sem resposta, isso também repetia `*IDN?`, seu timeout e o FETCH de validação do fallback.

A fixture `RecoverableTransport` reproduziu essa sequência: uma resposta válida após cada abertura, seguida de timeout recuperável na mesma porta. Antes da correção, seis amostras exigiam seis aberturas e os intervalos eram `[6, 6, 6, 6, 6]` segundos. Reabrir reiniciava o ciclo da falha. A soma nesse cenário é espera de cadência + timeout FETCH + espera de reconexão + timeout IDN + resposta válida.

Isso comprova um mecanismo de amplificação no software compatível com a evidência. **Os anexos não incluem o log transacional daquele ensaio; não comprovam que esse foi o gatilho específico de cada intervalo físico.** Os novos contadores e logs permitem confirmar ou descartar essa hipótese no próximo ensaio real.

### Recuperação e observabilidade

- Timeout isolado de FETCH com COM aberta: nova tentativa na mesma conexão, respeitando o intervalo e a guarda após RX; nenhuma resposta é repetida como amostra.
- Três timeouts consecutivos: reconexão controlada, com no máximo três tentativas de reabertura. Porta fechada ou outro erro de transporte inicia recuperação sem aguardar três timeouts.
- Parâmetros físicos, comandos SCPI, parsers, SerialTransport e aquisição do GPM permanecem preservados.
- Sessão, contagem de amostras e sequência de persistência permanecem no mesmo runtime. Só respostas válidas entram no fluxo de medição.
- Diagnóstico: `successful_fetches`, `fetch_timeouts`, `consecutive_fetch_timeouts`, `reconnect_count`, `average_fetch_interval_ms`, `average_successful_rx_interval_ms`, `maximum_gap_ms`, `average_query_duration_ms`, `last_successful_fetch_at`.
- Falhas registram FETCH, TX/RX, horários, duração, bytes, código, estado da porta, tentativa e motivo da recuperação.
- Cadência observada ao vivo: mediana dos últimos intervalos de recebimento, até 60. Frequência reduzida exige pelo menos quatro intervalos e mediana acima de 1,5 vez o intervalo configurado. Relatórios usam a mediana do período por fonte/sessão.
- Meta saudável continua próxima de 1 Hz, conforme duração real da resposta e guarda serial. Não há preenchimento artificial para alcançar essa taxa.

## Auditoria por tela

P0: confiabilidade; P1: operação/legibilidade; P2: organização.

| Tela | Antes / problema e impacto | Depois / solução | Prioridade |
| --- | --- | --- | --- |
| Tempo real — vazio | Conectar e iniciar competiam, sem sequência clara | CTA por estado e etapas conectar → iniciar → acompanhar → resultados | P1 |
| Tempo real — conectado | Metadados pequenos competiam com a leitura | Nome, conexão e leitura em destaque; contagens recolhidas | P1 |
| Tempo real — sincronizando | Espera sem contexto operacional suficiente | Estado e botão “Sincronizando fontes”, ação bloqueada durante a solicitação | P1 |
| Tempo real — ativo/pausado | Muitos controles e possibilidade de perder contexto ao voltar à tela | Pausar/retomar/finalizar; recuperação da sessão pausada ao abrir a página; desconexão direta desabilitada durante ensaio | P0 |
| Tempo real — degradado | Configuração de 1 s podia sugerir frequência efetiva de 1 s | Aviso humano de leitura térmica abaixo da frequência esperada com acesso ao diagnóstico | P0 |
| Tempo real — finalizado | Próximo passo pouco evidente | “Ver resultados” e opção de novo ensaio | P1 |
| Detalhe de sessão | Cinco exportações e edição concorrentes | Menu Exportar, Comparar e edição sob demanda | P1 |
| Período na sessão | Datas arredondadas para minutos podiam excluir o final | Sessão completa usa timestamps exatos; estabilização exige confirmação; período personalizado é aplicado explicitamente | P0 |
| Exportação | Rascunho de datas podia divergir da análise visível | Arquivos usam a última janela aplicada com sucesso | P0 |
| Indicadores | “Cobertura incompleta” cortava no card | “Atenção”, contagens e detalhes de integridade; cards podem quebrar texto | P1 |
| Gráficos ao vivo e da sessão | Legenda estática e hover pouco explicativo | Legenda clicável/teclado, Mostrar todos, cursor vertical e valores exatos do instante; ausência não é interpolada | P1 |
| Sessões | Lista técnica com tipografia pequena | Leitura maior, tabela com rolagem local quando necessária; acesso aos detalhes preservado | P1 |
| Relatórios por período | Grade com larguras mínimas causava transbordamento | Grade em uma coluna nas larguras menores, prévia e detalhes humanos de qualidade | P1 |
| Relatório técnico PDF | Capa com espaço excessivo e dicionário de qualidade cru | Fluxo mais compacto, títulos junto ao conteúdo, contagens em linguagem natural e intervalos configurado/observado | P1 |
| Equipamentos | Diagnóstico podia propor TX mesmo quando aplicação usava a porta | Bloqueio preventivo na interface e proteção backend existente; mensagem identifica aquisição pelo ThermoPower | P0 |
| Equipamentos — avançado | Formulário serial extenso antecedia a operação | Parâmetros seriais recolhidos, mantendo todos os controles técnicos | P2 |
| Termopares | Valores/metadados pequenos | Tipografia maior; edição, qualidade e 32 canais preservados | P1 |
| Alertas | Lista e filtros pequenos | Tipografia consistente; severidade e reconhecimento preservados | P1 |
| Comparar sessões | Seleção com texto pequeno | Cartões e dados mais legíveis; comparação preservada | P2 |
| Medições | Densidade elevada de dados | Tabela legível com rolagem contida; disponível no grupo Avançado | P2 |
| Eventos e logs | Navegação técnica disputava espaço operacional | Grupo Avançado, lista e horários maiores | P2 |
| Importação | Entrada técnica no caminho principal | Grupo Avançado; ocultada para visualizador; fluxo de importação preservado | P2 |
| Usuários | Função administrativa no menu geral | Grupo Avançado e acesso apenas administrativo preservado | P1 |
| Diagnóstico do sistema | Sem resumo da frequência efetivamente recebida | Intervalos configurado/observado e contadores técnicos expansíveis, somente consulta do runtime | P0 |
| Visão executiva | Histórico disputava espaço com operação ao vivo | Grupo Avançado; métricas históricas e gráficos preservados | P2 |
| Configuração inicial | Fluxo especializado misturado à aquisição | Acesso pelo atalho superior preservado; revisão de adaptação de largura | P2 |
| Login | Tela separada do fluxo operacional | Autenticação e primeiro acesso preservados; revisão de largura e foco | P2 |
| Navegação geral | Lista longa sem agrupamento | Operação, Configuração e Avançado recolhível; funções administrativas ocultadas conforme perfil | P1 |

## Gráficos e cálculos preservados

Não foram alterados integração da energia, estatísticas de potência/temperatura, domínio dos eixos, cores, marcadores de pico/máxima, relógio comum ou timestamps. Ocultar uma série mantém o domínio dos eixos e os marcadores. O tooltip apresenta somente medições existentes no instante selecionado; duas fontes aparecem juntas quando efetivamente compartilham o instante. Não aproxima nem inventa a leitura da outra fonte.

A seleção inicial de sessão completa foi corrigida: incluir segundos que antes eram excluídos pode legitimamente alterar os resultados daquela janela. Isso decorre da seleção de dados correta, não de uma nova fórmula.

## Revisão reproduzível

```powershell
.venv\Scripts\python.exe scripts/generate-client-preview-fixtures.py --samples 300 --output build/ux-review/reports
cd frontend
npm run build
cd ..
node scripts/review-operator-ux.mjs
```

O script usa Chrome headless e Playwright instalado em `build/browser-tools`. Valida 22 estados/telas em 1366×768 e 1920×1080, cada um em 100% e 125%. A escala de 125% é reproduzida pelo viewport CSS dividido por 1,25 e device pixel ratio 1,25; não é uma inspeção manual do menu de zoom do navegador. Há verificações de transbordamento do documento, cards fora da tela, erros JavaScript e curvas reais renderizadas. As capturas são locais e não entram no pacote nem no Git.

O ensaio sintético usa 300 leituras por fonte; a variante degradada entrega somente uma térmica a cada seis segundos. Não há acesso às portas seriais nos testes visuais.

## Validação e entrega

Resultados finais, commit do código, ZIP e SHA-256 são registrados nas notas da versão após a execução dos gates. A suíte cobre 100/300 FETCH saudáveis sem reconexão, timeout isolado, reconexões justificadas, sessão preservada, persistência sem duplicação, frequência observada, mensagens e fluxos da interface. As regressões físicas existentes do GPM, sincronização e proteção das portas continuam obrigatórias.

**Homologação física final pendente:** repetir um ensaio de pelo menos cinco minutos com GPM + AT4532 reais; conferir contagens, intervalos observados, timeouts/reconexões e relatório. Não basta observar a configuração “1 s”. Exportar diagnóstico antes de desconectar para preservar os contadores da conexão.
