# API

Base: `/api/v1`. Documentação interativa: `/docs`; schema: `/openapi.json`.

## Contratos

Autenticação usa `Authorization: Bearer <token>`. Erros de aplicação seguem `{"error":{"status":...,"message":"..."}}`. Coleções retornam `items`, `page`, `page_size`, `total` e `pages`.

Principais grupos:

- `/auth/login`, `/auth/me`;
- `/users`;
- `/devices`, `/devices/{id}/connect|disconnect|test|status`;
- `/devices/{id}/channels`;
- `/sessions` e transições `pause|resume|finish|cancel|duplicate`;
- `/measurements` e `/measurements/series`;
- `/alert-rules`, `/alerts`, `/alerts/{id}/acknowledge`;
- `/events`, `/reports`;
- `/statistics/sessions/{id}`, `/statistics/executive`, `/statistics/compare`;
- `/diagnostics`, `/simulator/scenarios` e configuração/cenários;
- `/ws?token=...`.

## WebSocket

Envelopes possuem `type`, `timestamp` e `payload`. Tipos atuais: `connection.ready`, `heartbeat`, `measurement.created`, `device.status`, `session.status` e `alert.created`. O cliente reconecta com backoff; o servidor mantém filas limitadas e remove o ponto mais antigo para clientes lentos.

## Paginação e séries

`page_size` é limitado pelo backend. `/measurements/series` recebe `session_id`, `start`, `end` e `max_points`; a agregação retorna média, mínimo e máximo por bucket sem enviar todos os registros ao navegador.
