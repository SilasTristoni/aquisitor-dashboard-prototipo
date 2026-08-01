# ThermoPower Monitor - normas do repositório

## Objetivo

Evoluir o ThermoPower Monitor como produto industrial full-stack, mantendo a integração com hardware desacoplada e o simulador sempre utilizável.

## Convenções obrigatórias

- Código, nomes de arquivos, componentes, tipos e variáveis em inglês; textos da interface em português do Brasil.
- O frontend nunca acessa diretamente portas seriais. Toda aquisição passa pelo backend e pela interface `DeviceAdapter`.
- Potência é persistida em watts, preservando também valor e unidade originais. Temperatura é persistida em graus Celsius.
- Segredos e senhas reais não entram no repositório. Configuração sensível vem do ambiente.
- Endpoints de coleções usam paginação. Séries extensas usam agregação/downsampling no backend.
- Toda mudança de comportamento deve incluir ou atualizar testes proporcionais ao risco.
- Compatibilidade de PostgreSQL deve ser mantida, mesmo que SQLite seja o padrão de desenvolvimento.
- Alterações de esquema são feitas por migrations Alembic.
- Recursos dependentes do aquisitor real devem ser explicitamente marcados como pendentes de validação física.

## Organização

- `frontend/`: React, TypeScript e Vite.
- `backend/app/api/`: rotas HTTP e WebSocket.
- `backend/app/core/`: configuração, segurança e infraestrutura transversal.
- `backend/app/models/`: modelos persistidos.
- `backend/app/schemas/`: contratos Pydantic.
- `backend/app/services/`: regras de negócio.
- `backend/app/adapters/`: fontes de aquisição.
- `backend/tests/`: testes automatizados do backend.
- `frontend/src/**/*.test.tsx`: testes do frontend.
- `legacy/`: cópia imutável do protótipo original.
- `docs/`: decisões técnicas, operação e escopo comercial.

## Qualidade antes de entregar

Execute, corrija e registre os resultados:

```bash
cd backend && pytest
cd frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build
docker compose config
```

Não altere o conteúdo de `legacy/` depois de criado.
