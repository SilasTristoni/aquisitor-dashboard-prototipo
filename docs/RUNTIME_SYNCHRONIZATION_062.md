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
