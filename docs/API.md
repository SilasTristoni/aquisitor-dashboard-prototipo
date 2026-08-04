# API

Base: `/api/v1`. Documentação interativa: `/docs`; schema: `/openapi.json`.

## Contratos

Autenticação usa `Authorization: Bearer <token>`. Erros de aplicação seguem `{"error":{"status":...,"message":"..."}}`. Coleções retornam `items`, `page`, `page_size`, `total` e `pages`.

Principais grupos:

- `/auth/login`, `/auth/me`;
- `/users`;
- `/devices`, `/devices/{id}/connect|disconnect|test|status`;
- `/device-ports` para enumerar portas seriais sem abrir conexão;
- `/devices/{id}/channels`;
- `/sessions` e transições `pause|resume|finish|cancel|duplicate`;
- `/measurements` e `/measurements/series`;
- `/sessions/{id}/synchronized-series` com `grid_ms`, `tolerance_ms`, `channels` e `max_points`;
- `/imports/gpm8213/preview`, `/imports/at4532/preview` e `/imports/session`;
- `/alert-rules`, `/alerts`, `/alerts/{id}/acknowledge`;
- `/events`, `/reports`;
- `/statistics/sessions/{id}`, `/statistics/executive`, `/statistics/compare`;
- `/diagnostics`, `/simulator/scenarios` e configuração/cenários;
- `/ws?token=...`.

## WebSocket

Envelopes possuem `type`, `timestamp` e `payload`. Tipos atuais: `connection.ready`, `heartbeat`, `measurement.created`, `device.status`, `session.status` e `alert.created`. O cliente reconecta com backoff; o servidor mantém filas limitadas e remove o ponto mais antigo para clientes lentos.

## Paginação e séries

`page_size` é limitado pelo backend. `/measurements/series` recebe `session_id`, `start`, `end` e `max_points`; a agregação retorna média, mínimo e máximo por bucket sem enviar todos os registros ao navegador.

## Importação e sincronização

As prévias recebem multipart com o campo `file` e não persistem dados. A confirmação recebe `name`, opções de sincronização e os campos opcionais `at4532_file` e `gpm8213_file`. Ao menos um arquivo é obrigatório. O upload é limitado por `THERMOPOWER_MAX_UPLOAD_BYTES`, valida extensão, assinatura XLSX e bytes nulos em TXT.

A série sincronizada usa grade padrão de 1000 ms e vizinho temporal mais próximo, sem interpolar valores. A tolerância padrão é 1500 ms e o limite é 3000 ms. A resposta informa pares, pontos sem correspondência, taxa de pareamento e offsets médio/máximo.
