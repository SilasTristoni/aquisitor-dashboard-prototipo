# Auditoria de UX — 0.7.0

## Antes das alterações

Auditoria da aplicação em 127.0.0.1:5173, sessão demo de análise visual #13,
1366×768 e 1920×1080, zoom 100%. Árvore inicial limpa na master, base `e196671`.
AGENTS, documento da rodada anterior, estado físico e migrations 0009/0010 lidos.

Problemas reais: botão de compartilhamento esticado pela grade do formulário,
checkboxes sem dimensionamento próprio, eventos usando a grade de identificação
(títulos estreitos e muito espaço vazio), labels sobrepostos no gráfico, formulário
oficial sempre exposto, navegação Avançado do viewer e microcopy técnica de relatórios.

Preferências estéticas: espaçamentos, quantidade de bordas, peso dos títulos e
discrição das ações. Identidade, tipografia, sidebar e cores de base preservadas.

Já adequados: KPIs, escolha do período, dois eixos, layout geral de comparação,
fluxo de tempo real, permissões da API e serviços de cálculo/exportação existentes.

## Implementação

`ResultEvents` atende lista interna e pública. Agrupamento de marcadores usa apenas
coordenadas de exibição, sem modificar timestamps dos eventos ou amostras.
Estilos compartilhados: barra de ações, formulário compacto, grupo de escolhas,
metadados, seções expansíveis, lista de eventos e tabela numérica com scroll interno.
Nenhuma biblioteca UI nova.

Período oficial: remoção via DELETE autenticado e normalização UTC na gravação dos
metadados. A API continua controlando permissões; viewer recebe 403 nas mutações.
Persistência em SQLite/PostgreSQL usa o mesmo modelo, sem mudança de esquema.
O teste real de arraste encontrou propagação do clique do Brush para a seleção
por pontos. O handler agora distingue as duas interações e preserva o intervalo
arrastado; a regressão está coberta por teste de UI e verificação no navegador.

## Evidência visual local

Arquivos em `build/ux-070/` (fora do pacote cliente):

- `before-share-1366.png`: formulário/eventos originais.
- `before-public-1366.png`, `before-reports-1366.png`, `before-compare-1366.png`,
  `before-realtime-1366.png`, `before-viewer-1366.png`: situação inicial.
- `after-session-1366.png`, `after-session-1920.png`, `after-stable-1366.png`,
  `after-selection-1366.png`, `after-official-1366.png`: sessão e períodos.
- `after-share-form-1366.png`, `after-shares-1366.png`: compartilhamentos.
- `after-public-{768,1024,1366,1920}.png`: página pública responsiva.
- `after-session-dark-1366.png`, `after-viewer-1366.png`: tema escuro e viewer.
- `after-{reports,compare,realtime}-1366.png`: telas preservadas/refinadas.
- `visual-results.json`: checagem de overflow, erros JS e fluxos; `public.pdf`
  e `public.csv`: downloads pelo navegador em link com senha.
- `after-brush-detail.png`, `after-share-detail.png`, `after-chart-dark.png` e
  `interaction-results.json`: arraste, cancelamento e controles por teclado.

A validação usa cópia isolada do banco demo e API em 8012 na retomada de 05/10.
Na execução anterior, em 8011, o reinício do backend original foi bloqueado pelo
ambiente. Na retomada, a porta 8000 estava livre: um novo backend foi iniciado com
o código atual e o banco original, sem executar o ciclo de inicialização da aquisição.
O frontend em 5173 responde com a versão 0.7.0-client-preview.
Nenhuma aquisição física foi acionada; as validações mutáveis não alteraram o banco
original nem seus compartilhamentos.

## Verificações

- Backend completo: 271 testes passaram, 14 avisos; relatório `backend-full.xml`.
- Frontend final: 51 testes em 16 arquivos, incluindo regressão do Brush.
- Ruff, lint, TypeScript, build Vite, diff check e configuração Compose passaram.
- SQLite: upgrade até 0010, check, downgrade até 0008 e novo upgrade/check passaram.
- 16 capturas finais sem overflow ou erro JavaScript. Share com senha, PDF/CSV,
  bloqueio de XLSX não autorizado e viewer com três links/403 foram verificados.
- Núcleo físico e migrations comparados com HEAD e preservados.
- Pacote Windows: executável/SPA/login aprovados em banco isolado; 18 exports
  passaram (seis formatos em elétrica/térmica/combinada), além de manual e suporte.
- ZIP extraído e todos os hashes do manifesto conferidos; módulos de caracterização,
  seed, dados demo e credenciais de teste ausentes do produto distribuído.

## Arquivos e candidata

Frontend: `Layout`, `SessionAnnotations`, `SessionSharing`, `ResultEvents`,
`SessionDetailPage`, `SharedSessionPage`, `PeriodReportsPage` e estilos compartilhados.
Testes: `PeriodReportsPage`, `SessionDetailPage`, `ViewerLayout`, `ResultControls`.
Backend: `api/analysis_routes.py` (metadados/permissões) e `windows_launcher.py`
(retirada da entrada de caracterização); testes `test_product_analysis.py` e
`test_physical_engineering.py` (este último somente expectativas da versão).
Empacotamento: `VERSION.txt`, `frontend/package.json`, lockfile, `thermopower.spec`,
`scripts/package-client-preview.py`, `scripts/smoke-packaged-exports.py` e notas 0.7.0.

Candidata: `release/ThermoPower-0.7.0-client-preview.zip`, 58.030.110 bytes.
SHA-256: `e5d69878925c66e588b8b9e402dbca5f267678b98db8fa42f0c2651703c5583e`.
Base `e196671e41babd45981a8c0bd0fdf958cae7ab3f`, build em 05/10/2026 21:41:24 UTC,
`source_dirty=true`; nenhum novo commit/push/tag. Estado/diff completo local em
`build/ux-070/git-delivery-status.txt`. Manifesto de fontes dentro do pacote permite
identificar as alterações locais usadas na compilação.

## Limites

Screenshots e testes de teclado/foco não substituem auditoria completa WCAG ou
homologação de hardware. PostgreSQL requer execução real quando houver servidor;
os testes locais verificam a compilação das migrations para esse dialeto.
Links antigos foram lidos antes das mudanças e seus contratos de token/permissão
permanecem iguais. Screenshots do seed são evidência de desenvolvimento, nunca
amostras físicas ou dados a incluir no pacote cliente.
