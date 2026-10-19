# Resultados e experiência — validação local

Registro de entrega em 18/10/2026. Trabalho no worktree
`aquisitor-dashboard-prototipo-product-experience-071`, branch `feat/product-experience-071`.
Não houve commit, merge, push, tag, release ou pacote Windows nesta rodada.

## Base preservada

- Branch física: `fix/physical-reliability-070`.
- Checkpoint: `7059784949250ccf5519bc70b7e25c7f8ea4f384`.
- Ancestrais preservados: `862c8ce` (persistência/confiabilidade), `a0f0ba6` (segurança),
  `9727c71` (diagnóstico resiliente).
- ZIP físico original: `ThermoPower-0.7.0-engineering-AT4532-reliability-20261016.zip`.
- SHA-256 original reconferido:
  `e8061576efa648663a2a61025ffe3e8d4d848e46ea5e7990dcb8a440f5e5d8d0`.

O worktree físico original continua limpo. Comparação de bytes/SHA-256 de 26 arquivos
protegidos entre os dois worktrees aprovada: adapters, core, main, rotas de aquisição,
aquisição, persistência pendente, saúde de armazenamento, diagnóstico físico,
`iniciar-windows.bat` e `VERSION.txt`. O diff desses caminhos é vazio. Evidência local:
`build/product-tests/physical-base-proof.json`. Os dois campos novos em `entities.py`
pertencem somente a `SessionShare`; a mudança em `contracts.py` é somente o filtro de
canais de relatórios. Nenhuma alteração de comando, parser, framing, recuperação,
common-start, pausa/continuação, timestamp ou amostra armazenada.

## Funcionalidades

**Canais:** a seleção térmica visível alimenta exports PDF/PNG/XLSX/CSV. O seletor
"Canais nos arquivos" permite selecionados/todos; potência tem controle independente.
Nomes personalizados aparecem em legendas, tabelas e cabeçalhos CSV. Uma lista vazia
de canais agora significa nenhuma série térmica, sem voltar silenciosamente para todos.
A navegação para outra sessão reinicia os controles da página e não transporta preferências.

**Picos:** máximo global e por canal são calculados antes do downsampling, com horário
original da ocorrência na política de timestamps já existente, duração desde início da
sessão e desde início do período aplicado. Empates usam a primeira ocorrência; empate
simultâneo entre canais usa menor número de canal. Valores Open, nulos, não finitos e
qualidade inválida são excluídos da projeção analítica, inclusive no legado, sem regravar
o banco. Sessão, PDF, XLSX e resultado público exibem os indicadores; XLSX tem aba
"Picos térmicos" com máxima global explicitamente identificada.

**Lacunas e estado:** zero real continua zero. A fonte informa última potência válida,
ausência de leitura recente, desconexão e pausa; o timestamp da leitura válida permanece.
Zero sozinho não prova desligamento do produto nem desconexão da fonte. Eventos manuais
do ensaio continuam sendo o contexto para desligamentos conhecidos. Lacunas entre leituras
usam os intervalos reais de cada fonte e são calculadas antes da redução do gráfico.
Separadores são exclusivamente visuais, sem amostras adicionadas às estatísticas ou ao
banco. Gráficos exportados segmentam antes de reduzir pontos e não ligam valores através
de Open/null. Marcadores indicam lacuna e retorno de leituras, sem atribuir causa física.
Até 12 lacunas recebem rótulos para limitar sobreposição; todas mantêm a quebra da curva.
A integração de energia das leituras existentes permanece igual; sem potência disponível
o relatório informa ausência, em vez de apresentar 0 Wh como energia medida.

**Compartilhamento:** links locais antigos permanecem disponíveis. A opção de portal
publica snapshot autorizado do período oficial de sessão finalizada e dos canais escolhidos.
O serviço independente não importa aquisição nem depende do aplicativo local aberto.
Reutiliza autorização, senha/expiração/permissões; adiciona rate limiting persistente,
integridade de snapshot, tamanho/tempo limitados e revogação resistente a uploads atrasados.
Uma confirmação de upload perdida deixa registro local revogável, sem link confirmado.

## Verificações

| Verificação | Resultado |
| --- | --- |
| Backend completo, uma execução | 411 aprovados, 390,75 s |
| Complemento final de relatórios/portal/compartilhamento | 27 aprovados, 29,84 s |
| Frontend completo final | 65 aprovados, 19 arquivos |
| ESLint / TypeScript | Aprovados |
| Build web operacional e portal separado | Aprovados; versão da aplicação preservada |
| Navegador Edge headless | Sessão e portal em 390×844 e 1440×1000; quatro cenários sem erro JS/overflow |
| Migrations locais | SQLite com histórico/FKs e schema pré-existente; compilação PostgreSQL aprovados |
| Migrations do portal | SQLite upgrade/check/downgrade/upgrade/check e SQL PostgreSQL aprovados |
| Ruff / git diff --check | Aprovados |
| Compose config | Aprovado com executável standalone e valores fictícios de validação |

Após o gate completo, a revisão final acrescentou o teste de qualidade inválida no legado,
a identificação explícita do pico global no XLSX e a distinção entre energia zero e energia
ausente. Esses caminhos foram verificados novamente por regressões focadas de relatórios e
compartilhamento, sem repetir o backend completo. Resultado desse complemento registrado
em `build/product-tests/reports-final.log`.

A suíte completa inclui autenticação, viewer, segurança, persistência periódica, shutdown,
AT/Celsius, GPM, common-start, recuperação e soak com transporte simulado. Nenhum teste físico
foi executado. O teste de browser usa apenas respostas sintéticas e servidor temporário em
loopback, encerrado ao final. Fixtures não representam homologação física.

Evidências: `build/product-tests/backend-full.log`, `backend-full.xml`, `reports-final.log`,
`ui/results.json`, quatro screenshots e `physical-base-proof.json`. Reexecutar o browser
após os builds com `node scripts/smoke-results-ui.cjs`; instalar Playwright no ambiente de
teste ou definir `THERMOPOWER_PLAYWRIGHT_MODULE` para um módulo já instalado. O script não
faz parte do runtime de cliente. Os avisos restantes são Pyparsing de dependências, avisos
JUnit sobre record_property, avisos React Router e um chunk web do portal acima de 500 kB.

## Implantação e riscos restantes

Consultar `RESULTS_PORTAL_DEPLOYMENT.md` para variáveis, instalação, TLS/proxy, backup,
revogação e roteiro externo. **O portal não está publicado e não há link HTTPS real validado.**
Dependem de decisão: hospedagem interna administrada ou serviço gerenciado, domínio,
certificados, PostgreSQL/volume, região, retenção, operação e custos. Não houve DNS,
contratação, publicação de dados da Britânia ou abertura externa de portas.

PostgreSQL real, Nginx/TLS na infraestrutura escolhida, restauração com reconciliação de
revogações e teste de carga pública continuam pendentes. Usar implantação dedicada por
organização; proteger credencial administrativa, chaves de integridade e backups. A cota
por IP pode ser compartilhada por usuários atrás do mesmo NAT. Revogação não recolhe
arquivos já baixados. Ao eliminar banco/sessão local, conservar os registros de publicação
necessários à gestão no portal; o snapshot é independente da instalação.

## Roteiro manual

1. Sessão histórica/sintética com T25/T29/T32 e um canal Open: alternar selecionados/todos,
   ocultar canais, desligar inclusão de potência e comparar os quatro formatos exportados.
2. Aplicar janela diferente da oficial: conferir máxima, canal, horário e as duas durações;
   voltar ao período oficial; abrir outra sessão e verificar que seleção anterior não vazou.
3. Conferir zero real antes de lacuna, fonte térmica contínua e retorno elétrico: curva
   elétrica interrompida, sem zero artificial nem alteração de médias das amostras existentes.
4. Criar link local protegido; testar permissões, senha, expiração/revogação e viewer.
5. Em ambiente isolado com portal configurado, publicar resultado sintético oficial; fechar
   a aplicação local, abrir o portal e baixar apenas documentos autorizados. Alterar dados
   locais não deve alterar o snapshot. Revogar, inclusive após confirmação perdida.

## Arquivos

Inventário e status completos registrados abaixo; todas as alterações permanecem locais
e fora do staging. Nenhum banco, credencial real, log, screenshot ou build foi adicionado ao Git.

```text
 M .gitignore
 M backend/app/api/share_routes.py
 M backend/app/models/entities.py
 M backend/app/schemas/contracts.py
 M backend/app/services/period_documents.py
 M backend/app/services/period_reporting.py
 M backend/app/services/period_workbook.py
 M backend/tests/test_migrations.py
 M backend/tests/test_period_reports.py
 M frontend/package.json
 M frontend/src/components/SessionSharing.tsx
 M frontend/src/pages/DashboardPage.tsx
 M frontend/src/pages/SessionDetailPage.tsx
 M frontend/src/pages/SharedSessionPage.tsx
 M frontend/src/test/SessionDetailPage.test.tsx
 M frontend/src/utils/chartPresentation.ts
 M frontend/src/utils/combinedReadings.ts
?? backend/alembic/versions/0011_share_result_options.py
?? backend/app/portal/__init__.py
?? backend/app/portal/application.py
?? backend/app/portal/body_limit.py
?? backend/app/portal/contracts.py
?? backend/app/portal/models.py
?? backend/app/services/result_publication.py
?? backend/app/services/share_policy.py
?? backend/portal-alembic.ini
?? backend/portal_migrations/env.py
?? backend/portal_migrations/versions/0001_result_portal.py
?? backend/tests/test_result_experience.py
?? backend/tests/test_result_portal.py
?? deploy/results-portal/nginx.conf
?? deploy/results-portal/requirements.txt
?? docs/RESULTS_EXPERIENCE_071.md
?? docs/RESULTS_PORTAL_DEPLOYMENT.md
?? frontend/portal.html
?? frontend/src/components/ReadingGapMarkers.tsx
?? frontend/src/components/ThermalPeak.css
?? frontend/src/components/ThermalPeak.tsx
?? frontend/src/pages/SessionDetailPage.css
?? frontend/src/portal.tsx
?? frontend/src/test/resultExperience.test.tsx
?? frontend/src/utils/sourcePresentation.ts
?? frontend/vite.portal.config.ts
?? scripts/smoke-results-ui.cjs
```
