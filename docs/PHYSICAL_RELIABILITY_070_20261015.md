# Confiabilidade 0.7.0 — evidências de 13–15/10/2026

## Diagnóstico anterior à implementação

Branch de trabalho: `fix/physical-reliability-070`, baseada em `9727c710`.
Preservados os ancestrais `862c8ce` (persistência), `a0f0ba69` (segurança) e
`9727c710` (exportação). Árvore limpa ao iniciar. Nenhum equipamento acessado.

Pacote recebido: `ThermoPower-evidencias-fisicas-20261013-a-15.zip`.
SHA-256: `520793b73643054fcf3f2d59181e50182034564b6cfb11f48b34aa954fabd6b2`.
Todos os membros foram extraídos e lidos, inclusive o diagnóstico aninhado.
36.221 registros JSON válidos, 36.204 após remover 17 repetições exatas.
Os dois logs internos começam com uma linha truncada; há uma linha vazia.
Inventário, hashes, registros com arquivo/linha e extração permanecem em
`build/physical-evidence-20261015/` (ignorado, não integra a candidata).

### Código efetivamente utilizado

O diagnóstico informa `e196671e`, **source_dirty=true**, build
`2026-10-08T01:20:17.501848+00:00`. Esse SHA sozinho não identifica o executado.
O manifesto da build local correspondente reproduz o digest declarado
`3fbc3e28a174613d17baa62f846003574876ddb20f0bbf22087a272cf82cec2c`.
Os hashes dos arquivos `adapters/specific.py`, `adapters/transports.py` e
`services/acquisition.py` coincidem com `401e582`, considerando CRLF.
Os dois primeiros ainda coincidem com HEAD; aquisição já contém a correção
posterior de persistência. Não se afirma equivalência integral do pacote com
um commit: existem diferenças em outros arquivos e assets gerados.

### Cronologia UTC e limites

| Instante / intervalo | Evidência e interpretação |
| --- | --- |
| 08/10 17:10:26 | Histórico interno contém SQLite FULL térmico. |
| 13/10 18:05:39 | Início da sessão 56. Snapshot final: pausada, 193 amostras elétricas, 52 térmicas. São contagens persistidas, não prova de continuidade. |
| 13/10 18:08–18:09 | Frames AT parciais e ressincronização sem fronteira segura. |
| 13/10 18:10:20 / 18:10:28 | SQLite FULL ao gravar AT / GPM. Flush e gravação de SystemEvent também falham; erro secundário escapa da tarefa. |
| 14/10 04:03–11:51 | 11.051 falhas de reconexão GPM: **11.050** contêm FileNotFoundError; a última é timeout de identidade. Há lacuna de captura 05:22–06:41. Não inferir tentativas nesse intervalo. |
| 14/10 11:58–12:41 | 16 falhas GPM de resposta sem terminador oficial, propagadas como erro de parser e encerramento do leitor. |
| 14/10 20:03–15/10 12:11 | 2.478 falhas Celsius nos arquivos externos e 1.232 recuperações malsucedidas. Há retomadas com frames válidos, inclusive no último arquivo. Não é falha térmica permanente. |

Contextos HTTP são herdados: `started_at`, endpoint e identificadores associados
à criação da tarefa não equivalem ao instante nem à sessão de cada evento.
Usou-se `timestamp` UTC do registro. Parte do histórico interno é de versões
anteriores (0.6.x e outras candidatas); não atribuir todos os erros à build atual.

### Problemas classificados

**P0 — persistência indisponível derruba o leitor e provoca cascata.**
Componente: `services/acquisition.py`, `_read_loop`, `_flush`, gravação de
SystemEvent; `pending_persistence.py`. Causa comprovada: SQLite recusou escrita
com FULL. O código transforma falha de armazenamento em encerramento do adapter;
o registro do erro usa o mesmo banco sem proteção. A rotina periódica atual
preserva o buffer, mas repete logs/retries a cada 2 s indefinidamente.
Regressão necessária: FULL elétrico/térmico, erro secundário, rollback, capacidade
restabelecida, retenção limitada sem descarte silencioso e sem duplicação.

O ZIP não contém banco, WAL, quota ou espaço livre do volume da cliente.
Portanto **não está comprovado** se foi volume cheio, quota, limite de páginas
SQLite ou outro limite de capacidade. O diretório padrão Windows é derivado do
ambiente do usuário; não constitui prova do caminho efetivamente usado na bancada.
O payload térmico e os logs têm potencial de crescimento; não provam a causa FULL.

**P0 — reconexão GPM sem verificar presença física e sem backoff progressivo.**
Componente: `adapters/specific.py`, leitor GPM. O loop tenta novamente a mesma COM
com esperas fixas de 1 s + 1 s e traceback a cada falha. A descoberta USB ocorre
na conexão do serviço, não no loop de recuperação. Isso explica a repetição;
**não explica por que o Windows perdeu o dispositivo**. Identidade de referência:
VID 0x2184, PID 0x0052, serial GES913349. Regressões: ausência prolongada, ocupação,
I/O, mesma COM com outro dispositivo, retorno na mesma/nova COM com identidade
inequívoca, interrupção/cancelamento e preservação da sessão.

**P1 — GPM parcial encerra a tarefa.**
Componente: transação e leitor GPM. O parser corretamente rejeita ausência de CRLF,
mas a exceção segue o caminho fatal. Reproduzir fragmentação, timeout parcial,
registro da transação rejeitada e recuperação sem publicar dados incompletos.
O motivo físico dos bytes faltantes não está demonstrado nos arquivos.

**P1 — AT tem interrupções prolongadas, com limite físico não explicado.**
Componente: transporte TCP-32 e recuperação Celsius. Capturas mostram bytes
parciais; preservar sua rejeição, retenção e bloqueio de TX até fronteira segura.
O código já possui backoff até 30 s e só zera falhas após medição válida.
Não há evidência para trocar trigger, aumentar janela ou descartar fragmentos.
Reproduzir capturas reais, timeout isolado e recuperação simultânea antes de
atribuir defeito adicional à engine. A origem dos bytes faltantes exige bancada.

**P1 — volume de logs durante falhas.** O log de aplicação já rotaciona em 5 MiB;
milhares de tracebacks repetidos substituem rapidamente o histórico útil.
A trilha serial de engenharia precisa ter retenção limitada e declarar truncamento
na exportação. Contadores e último erro devem sobreviver à supressão de repetição.

### Política para implementação e validação

Separar armazenamento, disponibilidade USB e protocolo. Manter Celsius 5 s,
janela 4 s, TCP-32/CP936/69 campos, Open=null, CRLF GPM, comandos, timestamps,
dedupe, common-start e isolamento de fontes. Não simular integridade nem amostras.
Exportação permanece passiva, limitada e independente de dispositivos/SQLite.
Testes determinísticos precedem mudanças; gates completos somente ao final.
Resultados simulados não constituem homologação. Nenhuma candidata é autorizada
antes de todos os gates relevantes passarem.

## Resolução e validação final — 16/10/2026

### Correções implementadas

- Armazenamento: erros SQL/IO deixam de ser tratados como desconexão física.
  O leitor aguarda com o lote retido, sem consumir novas amostras indefinidamente.
  A transação só remove o buffer após commit; rollback mantém timestamps e dados.
  Até oito tentativas automáticas, com backoff limitado a 30 s, depois tentativa
  explícita do operador. O primeiro SQLite BUSY pode ser retentado imediatamente;
  esperas SQLite no caminho de leitura/periódico ficam limitadas a 25 ms.
  Status distingue a indisponibilidade de armazenamento. A recuperação grava um
  SystemEvent de interrupção junto às amostras; erros secundários não escapam do leitor.
- GPM: enumeração USB passiva fora do event loop, correspondência única por
  VID/PID/serial antes de abrir a COM, inclusive após mudança de porta. Ausência,
  ocupação, I/O, timeout e resposta incompleta têm causas diferentes. Backoff
  2/4/8/16/30 s, zerado apenas após leitura válida. Logs repetidos de recuperação
  limitados a um por minuto, além de mudanças de causa. CRLF incompleto permanece
  rejeitado, registrado na transação e segue recuperação sem encerrar o leitor.
- Ciclo de vida: Continuar preserva a tarefa que já está recuperando; um runtime
  efetivamente recriado retoma a sequência persistida da sessão.
- Diagnóstico: orçamento de 256 MiB para novas trilhas físicas, sem apagar arquivos
  anteriores; perdas por orçamento e erros de escrita são explícitos. Erro de I/O
  no gravador aguarda 30 s. `storage-state.json` acrescenta tamanho DB/WAL/SHM,
  volume, páginas e espaço livre dentro do coletor isolado. API e fallback local
  continuam sem testar equipamentos. Script local incluído na candidata.

A comparação AST com `9727c710` confirmou igualdade integral de At4532Protocol,
At4532Parser, At4532Normalizer, At4532SerialAdapter, At4532SerialTransport,
Gpm8213Protocol, Gpm8213Parser, Gpm8213Normalizer e prepare_common_start.
Não houve alteração de migration, versão, relatórios, UX ou `iniciar-windows.bat`.

### Testes

- Reprodução inicial: quatro falhas esperadas (FULL elétrico/térmico, SystemEvent
  secundário, resposta GPM parcial encerrando o leitor), antes das correções.
- Novas regressões incluem SQLITE_FULL real via max_page_count, rollback/retry,
  oito tentativas sem descarte, USB ausente por mais de uma hora simulada sem
  abrir porta, identidade ambígua/divergente, retorno na mesma/nova COM, CRLF
  fragmentado, dez capturas parciais reais AT, retomada e exportação sob falha.
- Soak simultâneo: **9.016,75 s simulados**, 1.500 amostras por fonte, sequências
  completas e timestamps recebidos distintos, recuperação AT/GPM e flush periódico.
  A primeira execução excedeu o orçamento de 120 s com logs informativos por ciclo;
  limitando esses logs no teste e dando 180 s ao trabalho de disco, passou em 44,78 s.
  Isso altera apenas o harness, não a cadência nem a política de produção.
- Backend completo executado uma vez após correções: **396 passed**, 367,46 s,
  14 avisos existentes Pyparsing/Matplotlib. Inclui regressão P0 original, segurança,
  persistência, protocolos, isolamento e exportação. Nenhum teste original removido.
- Frontend: **60 passed**, lint, typecheck e build web aprovados.
- Ruff e git diff --check aprovados. Alembic upgrade head/check e pip check aprovados.
  Compose validado com o executável standalone existente e segredos fictícios locais.
- Evidências automatizadas: `build/physical-reliability-full/backend-full.xml`,
  `build/physical-reliability-tests/soak.xml` e `preserved-core.json`.

### Arquivos da alteração

| Área | Arquivos |
| --- | --- |
| Recuperação GPM | `backend/app/adapters/specific.py`, `transports.py`, `usb_identity.py` |
| Persistência e estado | `backend/app/services/acquisition.py`, `pending_persistence.py`, `storage_health.py` |
| Evidência e exportação | `backend/app/core/physical_trace.py`, `backend/app/engineering/local_diagnostic.py`, `backend/app/services/diagnostic_snapshot.py`, `physical_diagnostic.py`, `storage_diagnostic.py` |
| Regressões | `backend/tests/test_physical_reliability.py`, `backend/tests/fixtures/at4532_partial_20261013_15.json` |
| Operação e candidata | este documento, `docs/ENGINEERING_AT4532_070.md`, `scripts/export-local-diagnostic.ps1`, `scripts/package-at4532-engineering.py`, `scripts/smoke-packaged-exports.py` |

### Riscos e condições da bancada

Não foi determinada a causa Windows/USB do desaparecimento da COM3 nem a origem dos
bytes AT/GPM faltantes. Não foi medido espaço/quota da instalação da cliente.
Enumeração depende do retorno da API do Windows; o worker é aguardado no cancelamento
para não abandonar trabalho concorrente. Espera por lock SQLite é limitada; latência
física de disco/driver não possui garantia de tempo real. Sem identidade USB completa
e inequívoca, o GPM exige reassociação explícita, em vez de tentar uma COM incerta.

Com disco cheio e encerramento forçado, o lote ainda em memória não é durável.
Os dados já commitados são preservados; a sessão com interrupção não representa um
ensaio contínuo íntegro. Retenção de logs é finita, e uma exportação parcial não prova
ausência de atividade física. PostgreSQL permanece compatível em código, mas não foi
testado contra um servidor PostgreSQL nesta execução.

Sem commit, push, merge, tag ou release. Branch `fix/physical-reliability-070`,
HEAD `9727c7104be574abc2acecb62906b2cf060ef35d`; alterações permanecem locais.
A candidata é exclusivamente para bancada de 30–60 min com as duas fontes,
verificação de amostras distintas, persistência e recuperação. Não há homologação física.
