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

Vitest e Testing Library cobrem login com sucesso/falha, indicadores do dashboard, canais e eventos filtrados. Pytest cobre também normalização de unidades, detecção de cabeçalho TXT/XLSX, canal T32, qualidade de sobrecarga, preview/confirm, proteção de assinatura e sincronização ponta a ponta.

Os arquivos usados pelos testes são sintéticos e construídos em memória; nenhum arquivo real de bancada é copiado para o repositório.

```bash
cd frontend
npm run lint
npm run typecheck
npm test -- --run
npm run build
```

## Hardware

Testes automatizados não substituem validação elétrica/metrológica. O checklist físico está em `DEVICE_INTEGRATION.md` e requer equipamento, driver, referência conhecida e sessão de soak.
