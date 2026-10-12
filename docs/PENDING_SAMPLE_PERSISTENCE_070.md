# Persistência de amostras pendentes — 0.7.0

Correção de 11/10/2026 sobre HEAD `401e5825ba721e135be3f588b1ec9b2caa13fbbe`,
preservando as alterações locais da auditoria anterior. Escopo exclusivo: A3
da auditoria `RELIABILITY_AUDIT_070_20261011.md`.

## Defeito e correção

**P0 reproduzido:** após receber uma amostra, uma fonte silenciosa deixa dados
no buffer por tempo indeterminado. A condição temporal de flush era avaliada
somente com a chegada da próxima leitura. Interromper o processo antes do
commit perde essas amostras.

`backend/app/services/pending_persistence.py` acrescenta uma tarefa de
persistência vinculada ao lifespan da aplicação. A cada 2 s, ela percorre
buffers não vazios associados a sessões e usa o `_flush` existente. Não solicita
leituras, não acessa o adaptador e não muda a cadência de aquisição.

O flush atual executa SQLAlchemy síncrono e não possui pontos de suspensão
entre a leitura do buffer, o commit e a atualização dos contadores. A tarefa
usa o mesmo event loop; não há thread adicional disputando o buffer. A prova
de regressão intercala as entradas de flush periódico e de lote, verificando
ausência de duplicação. Se essa transação passar a suspender execução no futuro,
a exclusão entre os consumidores do buffer precisará ser reavaliada.

Em falha de gravação, a transação existente faz rollback e mantém o buffer.
O gravador registra somente identificadores e classe do erro, continua a outra
fonte e tenta novamente no próximo ciclo de persistência. Ele não altera
`last_error` de aquisição nem dispara recuperação do equipamento.

A validação complementar reproduziu bloqueio de **11,145 s** no event loop
quando outra conexão segurava uma transação SQLite. Foi acrescentado um contexto
de persistência com `busy_timeout=25 ms`, restrito ao gravador periódico e ao
encerramento da aplicação. O flush normal durante aquisição, pausa, continuação
e encerramento de sessão mantém a configuração anterior de espera.

O contexto usa conexão explicitamente retida até restaurar o timeout original,
antes de devolvê-la ao pool. Não há alteração global de PRAGMA nem disputa com
conexões emprestadas por outras requisições. PostgreSQL não recebe esse PRAGMA.

No encerramento normal, a tarefa periódica é cancelada e aguardada antes da
sequência já existente de desconexão e flush final. Há uma tentativa final por
fonte, sem loop de retry no shutdown. As gravações de eventos de desconexão
também usam o limite durante shutdown: o teste reproduziu uma segunda espera
longa ao tentar registrar a falha no próprio banco bloqueado. As ramificações,
chamadas aos adaptadores e regras de pausa/continuação permanecem idênticas.

## Arquivos desta correção

- `backend/app/services/pending_persistence.py`: novo gravador periódico.
- `backend/app/main.py`: vínculo da tarefa ao lifespan, sem alterar a sequência
  existente de shutdown dos dispositivos; ativa o limite de espera de persistência
  durante shutdown.
- `backend/app/services/acquisition.py`: substitui apenas a abertura de sessão
  SQLAlchemy em `_flush` e nos dois registros de evento de desconexão pelo contexto
  de persistência. Nenhum comando, fluxo de controle ou agendamento foi alterado.
- `backend/tests/test_pending_persistence.py`: testes de integridade, rollback,
  retry, independência de fontes, lifecycle e encerramento forçado.
- `backend/tests/test_reliability_audit.py`: A3 passa a executar o gravador e
  exigir contagem persistida, sem `xfail`.
- Este documento e atualização de acompanhamento no relatório da auditoria.

As alterações de produção/interface anteriores à correção foram preservadas.
SHA-256 confirma que os drivers e o teste P0 original permanecem inalterados.
Comparação AST de todos os métodos de `AcquisitionService`, normalizando somente
as três aberturas de sessão SQLAlchemy, confirma fluxo de controle idêntico.
Comandos, parsers, framing, polling, recovery/reconnect, common-start e regras
de pausa/continuação não foram modificados.
Não houve alteração de esquema ou migration nesta correção.

## Validação inicial (rodada anterior)

Primeiro foco: **6 testes aprovados** (`build/pending-persistence/focused.xml`).

- Fonte entrega uma leitura e fica silenciosa: a amostra é gravada sem novo RX.
- Flush de lote e periódico não duplicam amostras ou contadores.
- Valores, timestamps recebido/original, intervalo de 120 s e canal `null`
  permanecem exatamente como recebidos pelo gravador.
- Falha após enviar SQL mas antes do commit: rollback real, buffer intacto,
  outra fonte gravada; retry persiste uma única vez.
- Erro transitório não encerra o gravador; saída do contexto não deixa tarefa órfã.
- Flags de pausa e vínculo de sessão são preservados; buffer sem sessão não é
  descartado pelo gravador.
- Subprocesso com lifespan real e SQLite isolado: persistência sem nova leitura,
  morte forçada e reabertura do banco com amostras preservadas, integridade válida
  e nenhuma violação de chave estrangeira.

Regressão focada final: **40 aprovados, nenhuma falha esperada**, em 77,96 s,
com 14 avisos de depreciação de dependências gráficas
(`build/pending-persistence/regression.xml`). Comando executado no backend:

```powershell
../.venv/Scripts/python.exe -m pytest tests/test_pending_persistence.py tests/test_partial_combined_acquisition.py tests/test_session_pipeline.py tests/test_runtime_synchronization.py tests/test_reliability_audit.py --basetemp=../build/pending-persistence/tmp-regression --junitxml=../build/pending-persistence/regression.xml
```

Ruff nos arquivos Python desta correção e `git diff --check`: aprovados.
Sem nova execução das suítes completas ou frontend; sem hardware, build Windows,
ZIP, tag, release, commit ou push.

## Validação complementar de concorrência e ciclo de vida

O teste P0 não foi removido nem alterado nesta rodada; seu SHA-256 foi comparado
com o snapshot de entrada. **12 testes focados aprovados**, incluindo:

| Verificação | Evidência |
|---|---|
| Escrita normal e periódica no mesmo buffer | Ambos os ordenamentos de entrada via `asyncio.gather`; contagens, valores, timestamps e sequências sem duplicação. A transação continua sem suspensão interna. |
| SQLite bloqueado de verdade | Outra conexão mantém `BEGIN IMMEDIATE`; nenhuma linha parcial, buffer intacto e retry após rollback. Espera total medida de **163,178 ms**, contra **11.145 ms** antes da correção. |
| Restauração do timeout | Listener de check-in do pool confere o valor original tanto após sucesso quanto após exceção, antes de reutilização da conexão. |
| Cadências diferentes | Fontes sintéticas elétricas a 1 s e térmicas a 5 s; seis amostras elétricas e duas térmicas persistidas sem lacunas inventadas ou duplicação. |
| Responsividade | Heartbeat do event loop: maior intervalo ocioso de **16,632 ms** e durante produção/gravação de **38,743 ms**. Critérios locais: máximo abaixo de 200 ms e incremento abaixo de 150 ms. Não é homologação de desempenho serial físico. |
| Reinicialização | Processo isolado grava, é encerrado à força e reinicia com lifespan real; as contagens persistidas continuam 2/1, sem replay de amostras. |
| Lifecycle | Início/saída repetidos, ausência de tarefa `pending-sample-persistence` após saída e nenhuma thread adicional após o ensaio de cadências. |
| Encerramento normal | Flush final real antes de remoção do runtime: **77,431 ms**, uma tentativa por fonte, buffers vazios. |
| Encerramento com falha | Banco bloqueado: **805,339 ms**, uma tentativa final por fonte, buffers retidos e duas falhas explicitamente registradas no log. Critério de aplicação abaixo de 2 s inclui formatação e flush dos logs; cada flush de amostra abaixo de 200 ms. |

Logs e JUnit em `build/persistence-final/`, incluindo `repro.log`,
`shutdown-repro.log`, `focused-final.xml`, `metrics.json` e `scope.json`.
Esses tempos são observações desta máquina e destas cargas, não limites de
tempo real para qualquer hardware, volume ou disco.

Backend completo: **301 aprovados, sem falhas ou xfail, 14 avisos de depreciação
das dependências gráficas**, em **272,50 s**. Executado **uma única vez** após
aprovação dos testes focados; inclui regressões AT/GPM e do ciclo de sessão.
Evidência: `build/persistence-final/backend.xml` e `backend.log`.
`ruff check backend`: aprovado. `git diff --check`: aprovado.
Sem frontend/build, ZIP, commit, push ou release nesta rodada.

Comando de backend completo, executado no diretório `backend`:

```powershell
../.venv/Scripts/python.exe -m pytest --basetemp=../build/persistence-final/tmp-backend --junitxml=../build/persistence-final/backend.xml -o junit_family=legacy
```

Arquivos efetivamente alterados nesta rodada complementar: `pending_persistence.py`,
`acquisition.py` (somente contextos de persistência), `main.py` (contexto de
persistência no shutdown), `test_pending_persistence.py` e este documento.
As demais alterações locais anteriores foram preservadas; o teste P0 em
`test_reliability_audit.py` mantém exatamente o hash de entrada.

## Limites

O intervalo de 2 s é de tentativa de persistência, não uma garantia de tempo
real sob event loop bloqueado ou banco indisponível. Uma queda antes do commit
ainda pode perder o lote em RAM. A correção elimina a dependência de nova
leitura, mas não introduz journal durável nem garantia de exatamente uma gravação
em cenários de commit com resultado incerto por falha de conexão ao banco.

O teste de encerramento forçado comprova sobrevivência **após commit**, não
durabilidade de amostras que ainda não foram gravadas. A lógica transacional e
compatibilidade de banco continuam sendo as existentes; PostgreSQL real não foi
exercitado nesta máquina. O executável anterior não contém esta correção.

O limite de 25 ms restringe espera por lock SQLite por operação, não o tempo
total de processamento de um lote, fsync, falta de espaço, falha de disco ou
espera pelo pool. Os timeouts da escrita normal permanecem iguais aos anteriores.
Os testes não demonstram limite universal de desligamento dos adaptadores ou
de rede PostgreSQL; esses componentes não foram modificados. Não houve deadlock
ou espera indefinida nos cenários exercitados. Banco permanentemente indisponível
impede salvar o buffer, e encerrar o processo nessa condição ainda perde a RAM.

A investigação física das interrupções AT4532/GPM permanece independente,
aguardando os dois diagnósticos da Britânia. Nenhuma hipótese sobre sua causa
foi implementada ou declarada resolvida.

Git ao final: branch `master`, HEAD `401e5825ba721e135be3f588b1ec9b2caa13fbbe`,
oito arquivos rastreados modificados e cinco não rastreados, incluindo as mudanças
anteriores da auditoria. A lista específica desta correção está acima;
`build/persistence-final/scope.json` registra os checks de preservação desta rodada.
