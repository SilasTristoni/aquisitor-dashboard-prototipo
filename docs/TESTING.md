# Testes

## Backend

`pytest` cobre unidades, validação, parsers, simulador, falhas, estatística, operadores de alerta, senha/token, autenticação, permissões, paginação, WebSocket e fluxo ponta a ponta com os formatos de relatório. A suíte de período acrescenta fuso/offset, sessões concorrentes, integração de energia sem cruzar sessões, exclusão de lacunas, downsampling com extremos, PDF/PNG/JPEG reais, auditoria e erro sem dados.

```bash
cd backend
../.venv/bin/python -m pytest
../.venv/bin/python -m ruff check .
```

No Windows, use `..\.venv\Scripts\python`.

## Frontend

Vitest e Testing Library cobrem login com sucesso/falha, indicadores do dashboard, canais,
eventos filtrados e a central de relatórios por período com suas abas e payload de prévia.
Pytest cobre também descoberta USB mockada, associação por serial e sugestão conservadora.

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
