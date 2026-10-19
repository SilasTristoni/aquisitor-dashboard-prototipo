# Integração externa Render — entrega local 19/10/2026

Branch: `feat/product-experience-071`. Base desta execução:
`cfd2df680e03d0322592ee84962ed102be833196`, incluindo `80b0442` e ancestral físico `7059784`.
O worktree original continua em `fix/physical-reliability-070`; a implementação foi feita
no worktree `aquisitor-dashboard-prototipo-product-experience-071`, inicialmente limpo.

## Auditoria e implementação

Já existiam coleta autorizada, snapshot v1, documentos com hash, HMAC, senha, expiração,
revogação com tombstone, viewer independente, migrations próprias e limites persistentes.
Faltavam identidade por instalação/empresa, cofre Windows, reenvio durável local,
política mutável sincronizada, configuração administrativa e infraestrutura Render.

Foram reutilizados os schemas e a política de acesso, os cálculos e os geradores de
documentos existentes. A implementação acrescenta:

- Configuração e teste de conexão administrativos; credencial protegida pelo Gerenciador
  de Credenciais do Windows. Alternativa administrada por ambiente, sem arquivo secreto.
- Autenticação por instalação com hash da credencial no servidor; propriedade vinculada
  à empresa e à instalação autenticadas. Outras instalações não administram o resultado.
- UUID local único, snapshot pendente durável e reenvio explícito dos mesmos bytes.
  Confirmação perdida não oferece link prematuramente; sessão permanece consultável.
- Publicação atômica/idempotente no portal; recibo validado e link HTTPS do site público.
- Permissões sincronizadas por revisão, limitadas ao conteúdo originalmente autorizado,
  com HMAC e estado pendente visível após erro. Revogação impede upload atrasado.
- Migração local 0012 apenas em compartilhamentos; migração do portal 0002 para identidade
  e política. Nenhuma alteração de esquema das medições ou reescrita de amostras.
- API/site separados, CORS restrito, health check do banco, normalização do URL PostgreSQL,
  Blueprint Hobby com migrations e segredos. Sem exposição da aplicação operacional.

## Preservação

26 arquivos protegidos conferidos contra `7059784`, mais seis comparações contra `cfd2df6`
(relatórios, contrato, banco e main), com igualdade após normalizar apenas CRLF/LF.
Prova local: `build/render-integration-071/preservation.json`.
O único modelo operacional alterado é `SessionShare`; core, adapters, aquisição,
recuperação serial, persistência de medições e geradores de relatórios foram preservados.
`legacy/`, versão, launcher, builds e releases anteriores permanecem intactos.

## Validação executada

| Gate | Resultado |
| --- | --- |
| Backend completo | **427 aprovados**, 381,97 s, 27 avisos |
| Frontend completo | **70 aprovados**, 20 arquivos |
| ESLint / TypeScript / Ruff | Aprovados |
| Build operacional / build portal | Aprovados |
| Build portal com origem HTTPS externa sintética | Aprovado; URL correta nos assets |
| Smoke Edge desktop/mobile, viewer e sessão/configuração | 4 cenários aprovados, sem erros JS ou overflow |
| Cofre Windows real | Gravação/leitura com credencial sintética e alvo descartável; removido no teste |
| Migrations | SQLite upgrade/check/downgrade do portal e histórico local; compilação PostgreSQL |
| Blueprint | Zero erros no JSON Schema público oficial do Render |
| Compose | `docker-compose.exe config --quiet` aprovado com valores fictícios |
| Git diff / preservação / ancestralidade | Aprovados |

Docker não está no PATH; foi usado o executável Compose já existente em
`aquisitor-dashboard-prototipo/build/tools/docker-compose.exe`, conforme fallback do projeto.
Não foi iniciado container nem instalado serviço de banco.

Os testes incluem publicação/consulta/download sintéticos, senha, expiração, revogação,
rate limiting, integridade, empresa/instalação incorreta, credencial desabilitada, upload
concorrente duplicado, confirmação perdida, indisponibilidade, reinício independente,
política pendente e reenvio, recusa de redirects e regressões físicas simuladas locais.
O primeiro gate frontend encontrou dois mocks/nomes de botão antigos; foram atualizados
para a nova configuração e o destino explícito. A execução completa seguinte passou.
Avisos remanescentes: deprecações de dependências, JUnit/record_property, React Router
e chunk público acima de 500 kB. Nenhuma falha pendente nos gates locais.

Evidência ignorada pelo Git: `build/render-integration-071/backend.log`, `backend.xml`,
`frontend-tests.log`, `blueprint-validation.txt`, `preservation.json` e `ui/results.json`.

## Arquivos da entrega

- API local: `backend/app/api/share_routes.py`.
- Modelo/migration local: `backend/app/models/entities.py`,
  `backend/alembic/versions/0012_publication_outbox.py`.
- Transporte/configuração: `backend/app/services/result_publication.py`,
  `backend/app/services/portal_configuration.py`.
- Portal: `backend/app/portal/application.py`, `body_limit.py`, `contracts.py`,
  `models.py`, `settings.py`.
- Migrations portal: `backend/portal_migrations/env.py`,
  `backend/portal_migrations/versions/0002_installation_ownership.py`.
- Backend tests: `backend/tests/test_render_publication.py`, `test_result_portal.py`,
  `test_migrations.py`.
- Interface: `frontend/src/components/SessionSharing.tsx`, `PortalConfiguration.tsx`,
  `frontend/vite.portal.config.ts`.
- Frontend tests: `frontend/src/test/portalPublication.test.tsx`,
  `ResultControls.test.tsx`, `SessionDetailPage.test.tsx`.
- Infraestrutura/ferramentas: `deploy/results-portal/render.yaml`,
  `scripts/portal-installation-record.py`, `scripts/smoke-results-ui.cjs`.
- Documentos: este registro, `docs/RESULTS_RENDER_DEPLOYMENT_071.md` e aviso de
  substituição das instruções históricas em `docs/RESULTS_PORTAL_DEPLOYMENT.md`.

## Entrega operacional e pendências

O [guia Render/Windows](RESULTS_RENDER_DEPLOYMENT_071.md) contém arquitetura, sequência
de configuração, variáveis sem segredos, identidade/rotação, custos, backups e aceite.
Modelo: API a partir de US$ 7/mês, PostgreSQL a partir de US$ 6/mês, site estático;
workspace Hobby, sem dependência Pro. Confirmar orçamento no Render antes de aprovar.

Permanecem pendentes aprovação de custo/deploy, disponibilização autorizada da branch,
configuração real dos segredos/domínios, PostgreSQL real, Linux/Render, TLS/CORS externos,
carga, restauração e aceite com laboratório desligado em redes distintas. A confiança
em proxy permanece conservadora; conferir a cota compartilhada por IP de proxy.
Snapshots antigos sem identidade não são promovidos automaticamente.

Não houve publicação de dados reais, deploy, contratação, push, merge, tag, release,
build executável ou ZIP Windows. Nenhuma bancada ou homologação física foi declarada.
Integração preparada para a futura candidata 0.7.1; não é um portal já implantado.
