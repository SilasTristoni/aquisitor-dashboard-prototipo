# Testes

## Backend

`pytest` cobre unidades, validação, parsers, simulador, falhas, estatística, operadores de alerta, senha/token, autenticação, permissões, paginação, WebSocket e fluxo ponta a ponta com os três formatos de relatório.

```bash
cd backend
../.venv/bin/python -m pytest
../.venv/bin/python -m ruff check .
```

No Windows, use `..\.venv\Scripts\python`.

## Frontend

Vitest e Testing Library cobrem login com sucesso/falha, indicadores do dashboard, os 16 canais e eventos filtrados.

```bash
cd frontend
npm run lint
npm run typecheck
npm test -- --run
npm run build
```

## Hardware

Testes automatizados não substituem validação elétrica/metrológica. O checklist físico está em `DEVICE_INTEGRATION.md` e requer equipamento, driver, referência conhecida e sessão de soak.
