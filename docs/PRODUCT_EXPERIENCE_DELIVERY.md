# Rodada de produto e experiência — ThermoPower

Base: `master`, commit `1a3170f`. O trabalho começou com árvore limpa e branch alinhada
ao `origin/master` local. Foram lidos `AGENTS.md` e `AT4532_066_CURRENT_STATE.md`.
Validação realizada em 30/09–01/10/2026. Nenhum commit, push, tag ou release foi feito.

## Resultado

- Seleção do intervalo por dois cliques no gráfico ou pelo Brush, disponível nos dois
  modos de eixo. A área selecionada fica destacada e sincronizada com os campos.
  A seleção só recalcula os indicadores após **Aplicar período**.
- Sessão completa, estabilização sugerida e seleção no gráfico evoluem o fluxo existente.
  `PeriodReportDataService` continua calculando KPIs e alimentando preview/exportações;
  não foi criado outro motor de cálculo. Precisão de milissegundos e fuso explícito
  são preservados. Lacunas não são preenchidas com amostras inventadas.
- Período oficial com início, fim, nome, autor e data. Reabrir a sessão usa a preferência
  salva; consultar temporariamente a sessão completa não a apaga. Campos novos são
  opcionais para manter sessões antigas utilizáveis.
- Eventos manuais com horário real, tipo, título, descrição, autor e data. Marcadores no
  gráfico, conteúdo nos PDFs e planilha de eventos no XLSX quando existem eventos.
  Horários fora da sessão são rejeitados. Admin edita/remove qualquer evento;
  operator edita/remove seus próprios eventos.
- Viewer, já existente no modelo e cadastro, passa a ter navegação de consulta e
  bloqueio central das ações operacionais no backend. A interface oculta edição,
  período oficial, eventos, compartilhamentos e páginas de operação/configuração.
- Página pública `/compartilhado#token`, independente do layout operacional, para uma
  única sessão. Identificação do produto/modelo/amostra, período, KPIs, canais, gráfico,
  eventos e downloads autorizados. Não recebe equipamentos, usuários ou outras sessões.
- Compartilhamentos paginados com criador, datas, acessos, senha configurada (sim/não),
  status, cópia do link e revogação. Expiração de 24 h, 7 dias, 30 dias ou sem prazo.
- Cadência reduzida válida fica em detalhes de integridade. Falha, recuperação,
  interrupção ou erro continuam destacados; nenhum threshold físico foi alterado.

Os exports por período usam exatamente o intervalo aplicado. A rota antiga de export
por sessão prefere o período oficial quando disponível; sem período salvo, mantém
o export anterior. Relatórios distinguem período oficial **analisado** de período
oficial **salvo** quando a janela solicitada é diferente.

## Persistência e migrations

| Revisão | Conteúdo |
| --- | --- |
| `0009_session_analysis` | Cinco campos opcionais em `measurement_sessions`; tabela `session_annotations` |
| `0010_session_shares` | Tabela `session_shares`, índices, vínculos e credenciais com hash |

O upgrade SQLite adiciona os campos sem reconstruir a tabela de sessões; um teste com
FKs ativas verifica que as amostras históricas permanecem intactas. A exclusão autorizada
de uma sessão também remove seus eventos e compartilhamentos.

Aplicação: com a configuração do banco da instalação e backup existente, executar
`cd backend` e `python -m alembic upgrade head`. Nesta rodada somente bancos isolados
de teste foram migrados. Downgrade remove os metadados novos; no SQLite exige a conexão
isolada do Alembic com `foreign_keys=OFF`, recusando reconstrução sob cascatas ativas.

## Endpoints

Todos têm prefixo `/api/v1`. As coleções novas usam `page` e `page_size`.

| Método e caminho | Autorização / finalidade |
| --- | --- |
| `PUT /sessions/{id}/analysis-period` | Admin/operator; salva a janela oficial |
| `GET /sessions/{id}/annotations` | Autenticado, incluindo viewer; lista eventos |
| `POST /sessions/{id}/annotations` | Admin/operator; cria evento |
| `PUT /sessions/{id}/annotations/{event_id}` | Autor operator ou admin; edita evento |
| `DELETE /sessions/{id}/annotations/{event_id}` | Autor operator ou admin; remove evento |
| `GET /sessions/{id}/shares` | Admin/operator; lista compartilhamentos e links recuperáveis |
| `POST /sessions/{id}/shares` | Admin/operator; cria link e define permissões |
| `DELETE /sessions/{id}/shares/{share_id}` | Admin/operator; revoga, preservando auditoria |
| `POST /public/shares/access` | Token e senha opcional no corpo; somente a sessão vinculada |
| `POST /public/shares/download/{pdf\|xlsx\|csv}` | Mesmas credenciais e permissão específica |

`GET /sessions/{id}`, listagem e edição de sessões passam a incluir `analysis_period`.
Preview e exports existentes continuam em `/reports/period/...`.
`GET /reports/sessions/{id}.{formato}` passa a preferir o período oficial.

Viewer conserva leitura de resultados, comparação e geração/download de relatórios.
Todos os métodos de escrita operacionais são bloqueados centralmente, inclusive import
preview; os POSTs de consulta/export por período são a exceção explícita. Diagnósticos,
descoberta física, pacote de suporte e gerenciamento de compartilhamentos são negados.
As regras anteriores de admin/operator permanecem nas dependências específicas.

## Compartilhamento e implantação

O token tem 256 bits e é derivado por HMAC-SHA256 com domínio exclusivo, nonce aleatório
de 256 bits por link e a chave `THERMOPOWER_JWT_SECRET` já configurada no ambiente.
O banco guarda SHA-256 do token e o nonce, sem token puro. O nonce isoladamente não
autoriza acesso. Isso permite copiar o link posteriormente por uma rota autenticada.
Trocar a chave do ambiente impede reconstruir os links anteriores; URLs já copiadas
continuam validáveis pelo hash até expirar/revogar. A senha usa bcrypt e nunca retorna
na listagem. Entrada acima do limite em bytes do bcrypt é rejeitada.

Os endpoints públicos não aceitam `session_id`, filtros ou permissões do cliente.
Aplicam validação de expiração/revogação em cada acesso e download, limite de 30
requisições/minuto por IP/processo, contagem atômica dos acessos bem-sucedidos,
`Cache-Control: no-store` e `Referrer-Policy: no-referrer`.
O token está no fragmento da URL, enviado ao servidor somente no corpo, junto da senha.
Não é JWT de login e não autoriza endpoints internos. Os exportadores recebem dados
somente da sessão vinculada e sem identificação administrativa de usuários/equipamentos.

O endereço do link usa a origem aberta pelo operador. Em `127.0.0.1`/`localhost`, somente
o próprio computador o acessa; em LAN/servidor acessível, utiliza esse endereço.
Não foram criados túneis, exposição à internet ou infraestrutura externa.

## Frontend

Alterados: `SessionDetailPage`, `DashboardPage`, `App`, `Layout`, `HelpMenu` e ajuste
local de largura da página pública em `styles.css`.

Novos: `SessionAnnotations`, `SessionSharing`, `CadenceNotice` e `SharedSessionPage`.
Mantidos o tema, componentes de UI, Recharts e utilitários de séries independentes.

## Verificação

| Check | Resultado |
| --- | --- |
| Backend completo | **258 aprovados**, 20 avisos, 188,38 s |
| Frontend completo final | **46 aprovados**, 15 arquivos |
| Ruff backend | Aprovado |
| ESLint frontend | Aprovado |
| TypeScript | Aprovado |
| Build Vite | Aprovado, versão preservada |
| Regressões de relatórios/export | Nove testes existentes aprovados |
| Migrations | Quatro testes aprovados, incluindo preservação SQLite e compilação PostgreSQL |
| Alembic isolado | Upgrade → check → downgrade 0008 → upgrade → check aprovados |
| `git diff --check` | Aprovado |
| Compose config | Aprovado em 01/10/2026 com `build/tools/docker-compose.exe config --quiet` |

Evidências locais: `build/product-full-backend.xml`, `build/product-full-backend.log`,
`build/product-full-frontend-final.log`. O pytest precisou de `--basetemp` dentro de
`build/` porque a pasta temporária padrão do Windows apresentou acesso negado.

Testes novos cobrem: KPIs/export da mesma janela, preferência oficial e sessão antiga,
horário de eventos, GETs de viewer e 403 em todas as rotas operacionais, UI restrita,
isolamento público, token inválido, expiração, revogação, senha, permissões de download,
negação de APIs internas, sessão sem link, contadores, cadência válida e falhas reais.

Falhas encontradas e corrigidas durante o trabalho: formato UTC diferente na resposta
de gravação/leitura; aba vazia de eventos alterando exports antigos; mensagem de falha
duplicada na dashboard; remoção de coluna com FK no downgrade SQLite. Os testes
afetados foram reexecutados. A aba XLSX de eventos agora só existe quando necessária.

## Limites e riscos restantes

- PostgreSQL teve compilação das operações de migration; não havia servidor PostgreSQL
  nem daemon Docker disponível para validar execução real. A configuração Compose foi validada posteriormente com o executável standalone.
- Rate limiting é básico, em memória e por processo. Uma implantação com múltiplos
  workers requer limite compartilhado ou no proxy se desejar um limite global.
- Validação visual e de uso na instalação da cliente ainda deve ser feita. Não foi
  criado pacote Windows, candidata física, tag, release ou alteração de versão.
- AT4532, GPM-8213, transports, parsers, polling, reconnect, probe, sincronização,
  common start e aquisição não foram modificados. `legacy/` e `iniciar-windows.bat`
  também permanecem intactos. Testes automatizados não homologam hardware físico.

## Roteiro manual curto

1. **Período:** abrir ensaio com leituras; escolher Selecionar no gráfico; clicar em dois
   pontos ou mover o Brush; conferir início/fim; aplicar; comparar KPIs e exportar CSV,
   XLSX, PDF e PNG. Salvar como oficial, reabrir e conferir preferência. Consultar Sessão
   completa e depois Usar período oficial, verificando que o intervalo salvo continua.
2. **Viewer:** criar conta Visualizador em Usuários, entrar com ela, abrir detalhe,
   comparar sessões e baixar relatório. Verificar ausência dos controles operacionais;
   POST de início/edição com esse token deve retornar 403.
3. **Link:** como operator/admin, abrir Compartilhar resultado → Criar novo; selecionar
   senha/prazo/downloads; copiar; abrir janela anônima. Testar senha errada/correta e
   ausência dos downloads desmarcados. Recarregar a sessão e copiar novamente. Revogar
   e tentar abrir/baixar outra vez. Conferir acessos e último acesso na listagem.
4. **Eventos:** adicionar estabilização/desligamento com horário dentro da sessão;
   conferir marcador e relatório. Editar/remover como autor ou admin. Tentar horário
   fora da sessão e verificar rejeição.
5. **Cadência:** em ambiente de teste, usar estados já disponíveis de cadência reduzida
   com conexão saudável e conferir o detalhe discreto. Comparar com estado de falha,
   erro ou recuperação e conferir aviso destacado. Não alterar thresholds/protocolos.

## Estado do Git antes do commit solicitado

```text
$ git status --short
 M backend/app/api/deps.py
 M backend/app/api/routes.py
 M backend/app/main.py
 M backend/app/models/entities.py
 M backend/app/services/period_documents.py
 M backend/app/services/period_reporting.py
 M backend/app/services/period_workbook.py
 M backend/tests/test_migrations.py
 M frontend/src/App.tsx
 M frontend/src/components/HelpMenu.tsx
 M frontend/src/components/Layout.tsx
 M frontend/src/pages/DashboardPage.tsx
 M frontend/src/pages/SessionDetailPage.tsx
 M frontend/src/styles.css
 M frontend/src/test/DashboardPage.test.tsx
 M frontend/src/test/SessionDetailPage.test.tsx
?? backend/alembic/versions/0009_session_analysis.py
?? backend/alembic/versions/0010_session_shares.py
?? backend/app/api/analysis_routes.py
?? backend/app/api/share_routes.py
?? backend/tests/test_product_analysis.py
?? backend/tests/test_session_sharing.py
?? backend/tests/test_viewer_permissions.py
?? docs/PRODUCT_EXPERIENCE_DELIVERY.md
?? frontend/src/components/CadenceNotice.tsx
?? frontend/src/components/SessionAnnotations.tsx
?? frontend/src/components/SessionSharing.tsx
?? frontend/src/pages/SharedSessionPage.tsx
?? frontend/src/test/CadenceNotice.test.tsx
?? frontend/src/test/SharedSessionPage.test.tsx
?? frontend/src/test/ViewerLayout.test.tsx

$ git diff --stat
 backend/app/api/deps.py                      | 10 ++++
 backend/app/api/routes.py                    | 23 +++++++++
 backend/app/main.py                          |  4 ++
 backend/app/models/entities.py               | 41 ++++++++++++++-
 backend/app/services/period_documents.py     | 43 ++++++++++++++++
 backend/app/services/period_reporting.py     | 27 ++++++++++
 backend/app/services/period_workbook.py      | 19 +++++++
 backend/tests/test_migrations.py             | 77 +++++++++++++++++++++++++++-
 frontend/src/App.tsx                         |  6 ++-
 frontend/src/components/HelpMenu.tsx         |  4 +-
 frontend/src/components/Layout.tsx           |  5 +-
 frontend/src/pages/DashboardPage.tsx         |  5 +-
 frontend/src/pages/SessionDetailPage.tsx     | 63 ++++++++++++++++++-----
 frontend/src/styles.css                      |  2 +
 frontend/src/test/DashboardPage.test.tsx     |  4 +-
 frontend/src/test/SessionDetailPage.test.tsx | 51 +++++++++++++++---
 16 files changed, 354 insertions(+), 30 deletions(-)
```

O diff stat acima inclui somente arquivos já rastreados. Os arquivos novos aparecem
como `??` nesse registro anterior ao commit. O pedido posterior de commit/push inclui essas alterações, o seed e a segunda ferramenta de caracterização.
