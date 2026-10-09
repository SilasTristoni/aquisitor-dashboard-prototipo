# ThermoPower 0.7.0-engineering-AT4532-celsius-trigger

Uso interno de engenharia. Não é client-preview, release ou homologação física.
Esta candidata usa o aplicativo 0.7.0 atual, com instrumentação no próprio adaptador,
transporte, probes e publicação de amostras. Não existe outro driver de aquisição.

## Sequência da bancada

1. Extraia todo o ZIP para uma pasta nova. Preserve instalações e evidências anteriores.
2. Com ThermoPower fechado, execute `characterize-at4532-repeated-celsius.ps1`.
   Porta padrão COM5; para outra associação fisicamente confirmada, use `-Port COMx`.
   O script usa `ThermoPowerMonitor.exe --characterize-at4532-repeated-celsius`.
   O mutex da aplicação impede executar os dois modos ao mesmo tempo.
3. A ferramenta abre em 19200 / 8-N-1: passivo 5 s; Celsius #1 + 5 s;
   Celsius #2 + 5 s; Celsius #3 + 5 s. Nunca envia FETCH, IDN ou outro comando.
   Fronteira incompleta bloqueia escrita; mantém a guarda prévia de 1 s após RX.
   Se não houver fronteira segura em 10 s, interrompe sem retentar o comando.
   Portanto bytes espontâneos podem adiar o próximo write, sempre registrado.
4. Abra `ThermoPowerMonitor.exe`, com o mesmo usuário Windows usado no script.
   Credenciais do primeiro acesso são geradas localmente, nunca incluídas neste ZIP.
5. Execute **Testar leitura**, depois **Teste completo**. Não confunda uma leitura
   válida com aquisição contínua comprovada.
6. Execute AT sozinho; depois AT + GPM em sessão real. Registre os horários e o
   resultado observado. Não force comunicação em porta cuja associação seja incerta.
7. Abra **Diagnóstico** e clique **Exportar diagnóstico físico completo**.
   Envie somente esse ZIP final. Ele inclui automaticamente a caracterização Celsius,
   runtime, testes, transações, estados, sessões e contadores; não procure logs à mão.
   Pode exportar após desconectar: checkpoints preservam os contadores encerrados.

Dados/capturas ficam no diretório local da aplicação, fora da pasta do executável.
Não mova nem apague os dados entre a caracterização e a exportação. Uma variável
`THERMOPOWER_APP_DATA_DIR` ou `THERMOPOWER_LOG_DIRECTORY` personalizada deve ser a
mesma nas duas execuções. Exportar é somente leitura: não abre COM nem envia probes.

Preserve a associação já validada da bancada. Em uma base nova, a política existente
só permite validar por medição após IDN silencioso no contexto `physical-alpha`
(ou desenvolvimento/teste), sempre com associação manual exata e 19200/8-N-1.
Nesse caso, abra pelo PowerShell com `$env:THERMOPOWER_ENVIRONMENT='physical-alpha'`
e depois `./ThermoPowerMonitor.exe`, confirmando a porta correta no aplicativo.
O contexto padrão `engineering` exige associação previamente validada por medição;
a correção não amplia fallback para portas desconhecidas ou ambíguas.

## Política Celsius-triggered

O mesmo adaptador de produção agora recebe uma medição TCP-32 por `SYST:UNIT CEL`.
Não transmite FETCH no loop, no teste de leitura nem no teste completo. Intervalo
inicial de 5 s entre TX, janela de recepção de 4 s, guarda pós-RX de 1 s e nenhum
novo comando enquanto houver fragmento incompleto. `THERMOPOWER_AT4532_TRIGGER_INTERVAL_SECONDS`
permite intervalos maiores (mínimo 5). O sistema apresenta essa cadência esperada.

Um timeout isolado deixa a COM aberta e tenta o próximo ciclo seguro; reconecta
somente por falha física ou watchdog com vários ciclos consecutivos sem leitura.
Instância validada por TCP-32 não repete IDN na recuperação. O teste completo exige
dois timestamps E dois hashes distintos. `Open=null`, fila, dedupe e timestamps
originais permanecem preservados; os nomes históricos `fetch_*` nos contadores
agora contam tentativas Celsius, não comandos FETCH transmitidos.

GPM e common-start por prontidão independente (preparação de 15 s) não mudaram.
A ferramenta controlada reutiliza framing/parser do MESMO executável. A bancada de
06/10 comprovou três medições distintas com Celsius no alvo Britânia; isso não é
uma afirmação genérica sobre o manual nem homologação de aquisição contínua.
Detalhes em `AT4532_CELSIUS_TRIGGER_070.md`.

## Evidência e interpretação

`serial-events.jsonl` registra AT_STATE, AT_OPEN, AT_CLOSE, AT_TX, AT_RX_FIRST_BYTE,
AT_RX_COMPLETE, AT_FRAME_ACCEPTED, AT_FRAME_RECOVERED, AT_FRAME_DUPLICATE,
AT_FRAME_REJECTED, AT_TIMEOUT, AT_RESYNC, AT_RECOVERY, AT_RECONNECT e AT_SAMPLE_PUBLISHED.
Os campos aplicáveis incluem relógio monotônico e UTC, sessão/dispositivo, COM/baud,
comando/write efetivo, primeiro/último byte, comprimento/prefixo/terminador/hash,
timestamp original do equipamento, origem da resposta, intervalos TX/RX, estados,
tentativas/timeouts/reconexões, fila e resultado de deduplicação.

Tempos são observações de chamadas ao driver no PC, não medição elétrica do fio.
Monotônicos só devem ser comparados dentro do mesmo processo (`run_id`).
TX é registrado no write real; bytes recuperados não são atribuídos a um novo comando
(`tx_sent=false`). AT_RX_COMPLETE significa fronteira completa, não aprovação do
parser. AT_FRAME_RECOVERED significa enfileirado, não publicado. Só AT_FRAME_ACCEPTED
passou pela validação/dedupe; AT_SAMPLE_PUBLISHED registra a publicação real, incluindo
session_id quando há sessão. A ferramenta de observação não aplica dedupe de produção.
Timeouts de transporte/transação/tentativa podem representar a mesma ocorrência:
use `stage`, `reason`, contadores e `fetch_attempt`, não a quantidade de linhas isolada.

O gravador usa fila fora do caminho de I/O serial; mantém o histórico sem rotação
automática. `evidence-status.json` informa fila, perdas, erros e flush. Qualquer perda,
erro ou captura incompleta limita a evidência e não deve ser tratada como silêncio
físico. Transações detalhadas do runtime mantêm o limite preexistente de 256;
o JSONL AT preserva o histórico completo disponível. Checkpoints guardam estado de
probes e desconexões, incluindo GPM. Senhas/tokens/segredos são sanitizados.

O ZIP também contém acquisition-state.json, devices.json, transactions.json,
input-boundary-metrics.json, runtime-state.json, build-info.json, version.txt,
commit.txt, session-summary.json, last-errors.json, counters-AT-GPM.json e manifesto.

## Rastreabilidade e aceite

`build-info.json` identifica commit-base, fontes locais dirty/clean, data e manifesto.
`PRODUCTION-070-BASELINE.json` identifica exatamente a árvore 0.7.0 anterior à
instrumentação. `SOURCE-SHA256.json` identifica esta candidata; `SHA256SUMS.txt`
verifica seu conteúdo. As alterações 0.7.0 prévias foram preservadas.

Antes de empacotar: backend completo, regressões GPM/TCP-32/recuperação, testes do
JSONL e da exportação, repeated-Celsius, frontend e smoke do executável/exportação.
Esses testes usam fixtures e NÃO comprovam hardware. Nenhum equipamento é acionado
durante geração/validação local da candidata.

A próxima bancada deve validar estabilidade contínua e recuperação da candidata Celsius.
AT4532 continua não homologado; client-previews estão suspensas. Não restaurar FETCH
sem nova evidência física.
