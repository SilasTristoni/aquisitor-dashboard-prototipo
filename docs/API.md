# API

Base: `/api/v1`. Documentação interativa: `/docs`; schema: `/openapi.json`.

## Contratos

Autenticação usa `Authorization: Bearer <token>`. Erros de aplicação seguem `{"error":{"status":...,"message":"..."}}`. Coleções retornam `items`, `page`, `page_size`, `total` e `pages`.

Principais grupos:

- `/auth/login`, `/auth/me`;
- `/users`;
- `/devices`, `/devices/{id}/connect|disconnect|test|status`;
- `POST /devices/connect-sources` conecta as fontes elétrica e térmica de forma independente e
  retorna `electrical`, `thermal` e `overall` (`both`, `partial` ou `none`), sem desfazer uma
  conexão saudável quando a outra falha;
- `/device-ports` (compatibilidade) e `/hardware/discovery` para enumerar portas, metadados,
  associação, disponibilidade e incerteza de identificação;
- `POST /hardware/discovery/associate` para vincular uma porta atualmente descoberta;
- `/devices/{id}/channels`;
- `/sessions` e transições `pause|resume|finish|cancel|duplicate`;
- `/measurements` e `/measurements/series`;
- `/sessions/{id}/synchronized-series` com `grid_ms`, `tolerance_ms`, `channels` e `max_points`;
- `/imports/gpm8213/preview`, `/imports/at4532/preview` e `/imports/session`;
- `/acquisition/combined-status`: estado, identidade/protocolo, última leitura, contagem e erro
  independentes das fontes física elétrica e térmica;
- `/alert-rules`, `/alerts`, `/alerts/{id}/acknowledge`;
- `/events`, `/reports` e `/reports/sessions/{id}.{tipo}`;
- `POST /reports/period/preview`, `/reports/period/pdf`,
  `/reports/period/chart.png` e `/reports/period/chart.jpeg`;
- `/statistics/sessions/{id}`, `/statistics/executive`, `/statistics/compare`;
- `/diagnostics`, `/simulator/scenarios` e configuração/cenários;
- `/ws?token=...`.

## WebSocket

Envelopes possuem `type`, `timestamp` e `payload`. Tipos atuais: `connection.ready`, `heartbeat`, `measurement.created`, `device.status`, `session.status` e `alert.created`. O cliente reconecta com backoff; o servidor mantém filas limitadas e remove o ponto mais antigo para clientes lentos.

## Conexão e sessão com fontes independentes

`POST /devices/connect-sources` aceita `electrical_device_id` e `thermal_device_id`. Cada fonte
tem resultado próprio com `requested`, `success`, `status`, `error` e `runtime_status`; uma falha
não executa rollback da outra e os dois IDs devem ser distintos. O início de sessão aplica a mesma
política: remove o vínculo malsucedido somente depois de desfazer seu attach com segurança e
devolve o objeto `connection`. Se um flush/fechamento falhar, o runtime e o vínculo são retidos para
uma nova tentativa sem perder o buffer. A sessão fica
`running` com uma ou duas fontes e fica `failed` somente quando nenhuma fonte solicitada pode ser
anexada. Os timestamps e as quantidades de amostras permanecem independentes.

## Paginação e séries

`page_size` é limitado pelo backend. `/measurements/series` recebe `session_id`, `start`, `end` e `max_points`; a agregação retorna média, mínimo e máximo por bucket sem enviar todos os registros ao navegador.

## Importação e sincronização

As prévias recebem multipart com o campo `file` e não persistem dados. A confirmação recebe `name`, opções de sincronização e os campos opcionais `at4532_file` e `gpm8213_file`. Ao menos um arquivo é obrigatório. O upload é limitado por `THERMOPOWER_MAX_UPLOAD_BYTES`, valida extensão, assinatura XLSX e bytes nulos em TXT.

A série sincronizada usa grade padrão de 1000 ms e vizinho temporal mais próximo, sem interpolar valores. A tolerância padrão é 1500 ms e o limite é 3000 ms. A resposta informa pares, pontos sem correspondência, taxa de pareamento e offsets médio/máximo.

## Relatórios por período

O corpo `PeriodReportRequest` recebe `start`, `end`, `timezone`, textos de capa, filtros de
equipamento/sessão/canal, opções de conteúdo, orientação, tema, DPI, limite de tabela, tamanho
dos grupos de canais, tolerância, preferência de timestamp e interpolação `none|visual_only`.
Offsets ISO 8601 são aceitos; datas sem offset usam o fuso IANA informado e são convertidas a
UTC internamente. O período máximo padrão é 366 dias.

Sessões sobrepostas são segmentos independentes. A API nunca sincroniza ou integra energia
entre sessões, nunca preenche lacunas com zero e retorna 422 com mensagem clara quando não há
dados. A prévia reduz pontos por buckets; estatísticas e energia usam todas as amostras. Os
downloads registram `completed` ou `failed` em `reports` e usam nome de arquivo saneado.
