# Exportação resiliente e preparação da análise GPM — 13/10/2026

Base: branch `security/audit-070`, HEAD `862c8ce10ac02754c2e02dcc7eb48547fae8e060`.
As mudanças locais de segurança foram preservadas. A persistência periódica aprovada
permanece intacta. Nenhum driver, comando, timing, framing, parser, reconnect,
common-start ou pausa/continuação foi alterado. Sem ensaio físico nesta etapa.

## Evidência local e limites da conclusão

1. Reproduzido: `/support/physical-package` aguardava `acquisition_service.status()`
   indefinidamente quando a coroutine não respondia. O teste anterior à correção
   falhou por `TimeoutError` na chamada de status. A rota genérica também dependia
   desse status. Isso demonstra vulnerabilidade ao bloqueio; não demonstra que
   o driver GPM da Britânia tenha apresentado esse bloqueio específico.
2. A leitura de JSONL físicos usava o tamanho completo do arquivo, sem limite de
   histórico, e o ZIP era montado integralmente em memória. A geração usava uma
   Session ORM da requisição em outra thread. A exportação genérica fazia trabalho
   síncrono no event loop. Inspeção de código confirmou esses caminhos.
3. Reproduzido com o histórico local: sanitização de logs acumulados consumiu o
   prazo do coletor (stack em `support_snapshot`/`sanitize`). Os arquivos originais
   não foram apagados. A solução limita bytes, registros e tempo por seção.
4. Reproduzido na UI com download que nunca resolve: não existia prazo de espera.
   Agora, mesmo um download pendente, erro de corpo ou resposta tardia libera a UI.

A causa das interrupções físicas GPM e do travamento observado pela cliente
continua **não determinada**, aguardando os dois diagnósticos físicos.

## Coleta

- Snapshot passivo de memória no mesmo event loop, sem `status()`, métodos do
  adapter, propriedades de hardware, abertura de porta ou testes físicos.
- Tarefa de aquisição: estado final/cancelado e nomes das coroutines aguardadas,
  sem variáveis locais de stack. Inclui estado existente do adapter, último RX,
  timestamps existentes, lock serial, transações existentes, filas WebSocket,
  buffer, contadores recebidos/persistidos e resultados anteriores de conexão.
- Handle serial presente **não comprova conexão**. Contador recebido **não comprova
  publicação WebSocket**. Nenhuma medição é criada ou corrigida pela coleta.
- Processo separado, uma exportação por vez; chamadas concorrentes recebem 429.
  Coleta: 12 s; transferência: 12 s; interface: 20 s incluindo corpo. Cancelamento
  e timeout encerram o coletor e seus filhos no Windows, com espera de encerramento
  limitada. Limpeza dos temporários também ocorre na falha do envio HTTP.
- Banco em conexão exclusiva do coletor, somente leitura: SQLite `mode=ro`,
  `query_only`, espera por lock 50 ms e orçamento de consulta 500 ms; PostgreSQL
  transação read-only/repeatable-read, statement timeout 250 ms, lock timeout 50 ms.
  Banco indisponível produz ZIP parcial, com indicação explícita. A autenticação
  HTTP continua obrigatória; indisponibilidade do banco de autenticação não libera
  acesso anônimo. Nesse caso usar coleta local sob a conta Windows.
- Fontes físicas: até 4 MiB, 256 KiB por arquivo, 32 entradas de diretório,
  16 caracterizações, 1.024 registros/arquivo, 64 KiB/registro, orçamento 2 s.
  Logs da aplicação: 256 KiB por família, 512 linhas e 1,5 s por família.
  Metadados: 128 dispositivos, 100 erros/eventos, 10 sessões recentes.
  Memória cresce com esses recortes limitados, não com o histórico completo.
  Arquivo final aceito pela API/UI: até 24 MiB. Não há limite de RSS do SO.
- Runtime: até 32 fontes e 256 transações por fonte; strings/estruturas também
  limitadas. Snapshot final limitado a 12.000 nós/256 Ki caracteres de strings.
- Não há flush do journal durante exportação. Eventos ainda na fila podem faltar.
  `evidence-status.json` e `logs/status.json` informam indisponibilidade/recortes;
  os originais continuam no disco. SHA256SUMS verifica os arquivos exportados.
- Snapshot de memória representa um instante; metadados SQL usam uma transação;
  cada arquivo é limitado a uma fronteira de bytes. Não são um instante atômico
  único entre memória, banco e arquivos. Capturas antigas permanecem identificadas
  como checkpoints, sem serem apresentadas como estado atual.

## Coleta local quando a API não responde

Na raiz do repositório, com a venv já instalada:

```powershell
.\scripts\export-local-diagnostic.ps1 -AppData "$env:LOCALAPPDATA\ThermoPower Monitor" -Output "$env:USERPROFILE\Documents\Diagnostico-local.zip"
```

Para um banco de desenvolvimento diferente, informar `-Database C:\caminho\banco.db`
e `-AppData` apontando para a pasta cujo subdiretório `logs` deve ser coletado.
O destino precisa ser novo: o script recusa sobrescrever evidências existentes.
Não executa migrations, servidor, login, aquisição nem inicialização de equipamentos.
Banco ausente/incompatível resulta em seção indisponível, não em criação/migração.

O launcher contém a entrada `--export-local-diagnostic`; num **futuro executável
gerado com este código**, usar o script com `-Executable C:\caminho\ThermoPowerMonitor.exe`.
O executável atualmente instalado na cliente ainda não recebe esta alteração:
nenhum pacote foi gerado nesta etapa. Validar o modo congelado no gate futuro.

## Roteiro de análise do GPM após chegada dos logs

| Camada | Código atual / evidência a correlacionar |
|---|---|
| Serial | `Gpm8213SerialTransport`, `_io_lock`, `last_query_boundary`; TX/RX hex, CRLF e erro de transporte em transactions |
| Protocolo | `Gpm8213UsbSerialAdapter._after_identity/_read_once`; identidade, configuração, quantidade, headers e classificação da resposta |
| Loop | `_DocumentedProtocolAdapter.start_reading`; log de início/parada, timeout, reconnect agendado e erro de parser |
| Runtime | `AcquisitionService._read_loop`; tarefa aguardada/finalizada, `last_error`, último timestamp recebido, contador e buffer |
| Persistência | `_flush` e serviço periódico; buffer retido, contador persistido, erros DATABASE e contagens SQL da sessão |
| Publicação | `_publish_reading`, hub WebSocket, filas e await chain; RX/persistência sem atualização na tela não prova falha serial |
| Operação | `pause_session`, `resume_session/attach_session`, `disconnect`; correlacionar sessão, evento, hora e tarefa antes/depois |

No código atual, erros `SerialTransportError` seguem a política existente de
reconexão; outros erros propagam para o runtime. Pausa muda o estado de gravação
da sessão e realiza flush; continuar passa por `attach_session`. Isso explica
quais caminhos examinar, sem atribuir a falha física a qualquer um deles.

Solicitar exportação antes de reiniciar, quando possível, e horário aproximado
da interrupção e de Pausar/Continuar. Comparar TX → RX → leitura recebida → buffer
→ commit → WebSocket, mantendo as lacunas reais. Os rings são finitos: registros
ausentes não comprovam ausência de atividade. Não há novo journal contínuo GPM;
a instrumentação adicional é passiva, no momento da exportação.

## Validação

Encerramento da análise em 14/10/2026. Backend completo executado uma única vez
ao final: **366 passed, 14 warnings, 303,86 s**. Os avisos são de depreciação
Pyparsing/Matplotlib. Não ficaram processos Python de coleta/teste em execução.

Regressões novas cobrem runtime
pendente, banco ocupado, concorrência, cancelamento HTTP, deadline, ZIP/SHA, logs
grandes/inválidos, coleta offline, launcher sem aquisição, GPM contínuo simulado,
snapshot com recuperação e persistência pendente, limite de download e UI.
Os testes P0 de persistência existentes são mantidos integralmente.

- 30 testes focados de exportação, suporte e trace: aprovados.
- 145 testes focados de regressão, incluindo GPM, TCP-32, common-start e
  persistência: aprovados.
- Frontend: 59/60 passaram na execução completa; a única falha era a expectativa
  antiga de dois argumentos de `download`. O teste passou a verificar também o
  AbortSignal e limite de bytes, e os 4 testes de Support passaram na repetição
  focada. Os 6 testes novos/focados de diagnóstico e download passaram.
- Lint, typecheck e build Vite: aprovados. Nenhum build Windows executado.
- Script PowerShell de coleta offline: smoke com pasta sintética/banco ausente,
  ZIP parcial válido, sem iniciar aplicação ou criar banco.
- Ruff e `git diff --check`: aprovados.
- `docker compose config --quiet`: indisponível; Docker não instalado no ambiente.
- Hashes de 23 arquivos protegidos (drivers, aquisição, persistência e alterações
  anteriores de segurança): idênticos ao início. `iniciar-windows.bat` preservado.

Arquivos desta etapa, separados das alterações de segurança preexistentes:

```text
backend/app/api/support_routes.py
backend/app/engineering/local_diagnostic.py                  (novo)
backend/app/services/diagnostic_snapshot.py                  (novo)
backend/app/services/support_collection.py                   (novo)
backend/app/services/physical_diagnostic.py
backend/app/services/support.py
backend/app/windows_launcher.py
backend/tests/test_diagnostic_export_resilience.py           (novo)
frontend/src/api.ts
frontend/src/components/SupportButton.tsx
frontend/src/test/DiagnosticDownload.test.ts                 (novo)
frontend/src/test/PhysicalDiagnostic.test.tsx
frontend/src/test/Support.test.tsx
scripts/export-local-diagnostic.ps1                         (novo)
docs/DIAGNOSTIC_EXPORT_070_20261013.md                        (novo)
```

Pendências externas: evidência física Britânia; teste PostgreSQL real; smoke do
executável congelado em futura candidata. Nenhuma homologação física declarada.

Estado Git final: branch `security/audit-070`, HEAD inalterado (`862c8ce`).
15 arquivos desta etapa (8 modificados e 7 novos), além dos 12 arquivos de
segurança preexistentes preservados (8 modificados e 4 novos). Index sem alterações
staged. Sem commit, push, tag, release ou pacote de entrega.
