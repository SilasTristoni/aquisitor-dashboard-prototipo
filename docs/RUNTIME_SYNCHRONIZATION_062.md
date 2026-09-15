# Correções da homologação — 0.6.2-client-preview

## Início combinado

Na 0.6.1, `prepare_common_start()` levantava `ConnectionError` imediatamente se
qualquer runtime estivesse ausente, tivesse `last_error` preenchido, sua tarefa
estivesse encerrada ou `adapter.get_status().connected` fosse falso. Essa decisão
precedia a análise das leituras novas: um estado transitório podia invalidar uma
fonte que ainda produzia dados. Além disso, somente os últimos elementos das filas
eram comparados; um par anterior dentro da tolerância podia ser ignorado.

A correção mantém os leitores em execução, sem reconectá-los na preparação. Aguarda
até o prazo existente de 15 segundos e procura a menor diferença entre as leituras
novas válidas das filas, recebidas após o pedido e com no máximo três segundos de
idade. Confirma somente um par dentro da tolerância com ambas as tarefas em execução.
Uma tarefa encerrada não inicia sessão com suas últimas leituras. Um timeout limpa
apenas a preparação da sessão e preserva a aquisição da outra fonte.

São registrados a cada segundo, em transições de estado, ao sucesso e ao timeout:

- Por dispositivo: protocolo, papel da fonte, `connected`, `task_running`,
  `last_error`, `latest_received_timestamp` e `fresh_samples`.
- `interruption_flags`: condições que rejeitariam a fonte na implementação antiga;
  `status_error`: eventual erro ao consultar seu estado.
- `best_delta_ms`, `tolerance_ms`, instante do pedido e resultado da sincronização.

O último registro está em `common_start_diagnostic` no status da aquisição combinada
e também no log `common start diagnostic`. Os IDs e protocolos identificam GPM e AT.
Os testes reproduzem separadamente os estados transitórios; **sem o log da falha
física, não é possível atribuir aquele episódio a um dos flags específicos**.

## Diagnóstico com porta em uso

O probe documentado e a abertura do diagnóstico serial verificam o runtime antes de
construir/abrir outro adapter ou transporte. Usam o mesmo lock de porta da conexão,
com nova verificação depois de aguardar uma conexão concorrente. A comparação da COM
ignora maiúsculas/minúsculas e considera qualquer runtime associado à mesma porta,
inclusive cadastros diferentes. Um runtime ainda presente é tratado conservadoramente
como proprietário, mesmo durante transições ou falhas de fechamento.

O bloqueio retorna HTTP 409 e o código interno `port_owned_by_thermopower`, com:

> O equipamento está atualmente em aquisição pelo ThermoPower. Desconecte-o antes de
> executar o diagnóstico de comunicação.

Não altera estado, resultado de probe anterior, tarefa, conexão, buffer ou associação
à sessão. O teste de conexão da página também recusa portas já pertencentes ao runtime.
Não há reutilização da serial para diagnóstico: isso poderia consumir respostas do
leitor ativo. O status e o diagnóstico da aquisição permanecem disponíveis.

Erros de acesso à COM sem proprietário no runtime são apresentados como porta ocupada
por processo externo ao ThermoPower, sem atribuição injustificada ao fabricante.
O transporte serial e sua classificação interna original não foram alterados.

## Regressões

`backend/tests/test_runtime_synchronization.py` cobre:

- GPM e AT já conectados, publicando a 1 Hz, antes de iniciar sessão combinada.
- Início por HTTP, publicação no WebSocket e persistência inicial de ambas as fontes.
- Probe documentado, diagnóstico serial e teste de conexão durante aquisição; nenhuma
  segunda abertura, reconexão ou interrupção, com contadores continuando a crescer.
- Melhor par anterior às últimas leituras e estados transitórios de conexão/erro.
- Timeout sem par e tarefa encerrada, preservando a outra fonte.
- Porta de processo externo e posse assumida durante uma conexão concorrente.

SCPI, parsers, SerialTransport e cadência física não foram modificados. A validação
física desta correção no conjunto GPM + AT4532 permanece pendente.

## Entrega validada em 15/09/2026

- Backend completo: **154 testes passaram**, incluindo os oito novos; 14 avisos de
  depreciação de dependências.
- Gate de regressões com fixtures físicas: **57 passaram** (subconjunto do backend).
- Frontend: **30 testes passaram**, em dez arquivos; ESLint, TypeScript e Vite passaram.
- Ruff, Alembic upgrade/check e pip check passaram; nenhuma migration nova necessária.
- Configuração Compose validada pelo binário oficial standalone disponível neste
  ambiente; não foi realizada execução de containers.
- Executável PyInstaller e smoke isolado passaram: saúde, login, SPA, versão e rotas.
- ZIP extraído e todos os arquivos conferidos contra o manifesto SHA-256 pelo
  empacotador. A integridade do ZIP final foi confirmada após sua promoção.
- O checksum do ZIP anterior da 0.6.1 permanece idêntico ao registrado na entrega anterior.

Commit de origem da build: `4fb50d4fdc7c96de940d73dd2f736ba570691752`.
Implementação principal: `55d3a04`; ajuste de cancelamento e transições: `4fb50d4`.
Este registro final de resultados é posterior ao empacotamento, sem alteração do executável.

Pacote: `engineering/ThermoPower-0.6.2-client-preview.zip`.
Tamanho: **56.173.059 bytes**.
SHA-256: `C8B5EEC52A711C73E5810C4FE67F9C4EE8AD40DB3CF5E4D5F2453A1792055508`.
O pacote contém `TEST-RESULTS.txt` e `SHA256SUMS.txt`.

Para analisar uma nova tentativa física, consultar o campo `common_start_diagnostic`
em `GET /api/v1/acquisition/combined-status`, ou as entradas `common start diagnostic`
do log da aplicação. O log local disponível durante esta correção estava vazio;
não foi possível determinar qual flag específico ocorreu no episódio relatado.
