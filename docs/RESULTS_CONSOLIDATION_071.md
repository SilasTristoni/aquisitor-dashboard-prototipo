# Consolidação da candidata integrada — 19/10/2026

Branch: `feat/product-experience-071`. Checkpoint físico ancestral:
`7059784949250ccf5519bc70b7e25c7f8ea4f384`.
Checkpoint das funcionalidades: `80b0442e3a19af3c73ef218d3a3c9918936a01b5`.

## Revisão e preservação

Conferidos os 17 arquivos modificados e 27 novos inventariados em
`RESULTS_EXPERIENCE_071.md`; os 44 foram incluídos no checkpoint local.
O registro de 18/10 naquele documento descreve o estado anterior ao commit.
Não foram incluídos bancos, logs, screenshots, builds ou credenciais reais.
As credenciais literais dos testes são fictícias; configuração operacional vem do ambiente.

Comparação com os blobs de `7059784`, normalizando somente CRLF/LF para a comparação:
26 arquivos protegidos idênticos, com SHA-256 registrado em
`build/product-tests/consolidation-proof.json` (evidência local ignorada pelo Git).
Inclui todos os adapters/core, aquisição, common-start no serviço de aquisição,
persistência pendente, armazenamento, diagnóstico, main, rotas operacionais,
`iniciar-windows.bat` e `VERSION.txt`. O worktree físico original permanece limpo.
Os campos de modelo novos pertencem somente a `SessionShare`; a alteração de contrato
permite seleção térmica vazia nos relatórios. Nenhuma amostra persistida foi reescrita.

## Revisão funcional integrada

- Seleção de canais, potência independente e exportações PDF/XLSX/CSV/PNG usam a mesma
  coleta; regressões cobrem T25/T29/T32, canal único, todos, seleção vazia e Open.
- Máxima global e por canal é calculada antes da redução gráfica; empates conservam
  a primeira ocorrência. Horário, duração desde sessão/período e médias são conferidos.
- Zero real permanece zero; Open/qualidade inválida são ausência na projeção. O teste
  legado confirma que o valor inválido original continua no banco. Sem potência,
  energia indisponível não vira zero. Separadores gráficos não entram nas estatísticas.
- Lacunas, fontes independentes, pausa, desconexão e atraso têm regressões. Zero isolado
  não prova desligamento do produto; eventos informados continuam sendo seu contexto.
- Portal: senha, expiração, revogação, permissões, integridade, upload atrasado e perda
  de confirmação são exercitados com serviço independente e dados sintéticos.
- Histórico usa fixtures de esquema antigo e registros sintéticos, sem modificar banco
  da cliente. Migration local aditiva preserva histórico/FKs; portal tem banco próprio.
- Acrescentado teste de ausência de configuração externa: publicação retorna 503 com
  orientação HTTPS, sem criar registro; sessão, link local, consulta e CSV continuam
  funcionando. A primeira execução do novo teste usou incorretamente `detail`; corrigida
  a expectativa para o contrato existente `error.message`, sem alterar produção.

## Empacotamento e infraestrutura

A revisão estática de `thermopower.spec` e `windows_launcher.py` confirma coleta do
frontend operacional e da pasta completa de migrations locais, inclusive 0011.
Os módulos novos necessários ao aplicativo local possuem imports estáticos. A configuração
do servidor do portal só é exigida na fábrica independente; não é requisito do launcher.
O ambiente de build deverá possuir `.venv`, dependências e insumos de documentação/build-info
exigidos pelo processo existente. A versão não foi alterada nesta etapa.

As funcionalidades locais estão preparadas para o próximo gate de candidata interna
0.7.1. A comprovação do executável congelado exige build e smoke posteriores: não foi
gerado executável, instalador ou ZIP nesta consolidação. Não houve bancada física.

O compartilhamento externo independente do computador exige hospedagem do portal,
domínio/TLS, banco/volume, chaves, proxy e operação de backups/revogações. Permanecem
pendentes PostgreSQL real, TLS/proxy real, restauração e carga pública na infraestrutura
escolhida. Links locais continuam dependendo do computador acessível. Não há portal
publicado, homologação física, push, merge, tag ou release.

## Gates finais

| Gate | Resultado |
| --- | --- |
| Backend completo, uma execução final | 413 aprovados, 382,75 s |
| Frontend completo | 65 aprovados, 19 arquivos |
| ESLint / TypeScript / Ruff | Aprovados |
| Build web operacional / portal | Aprovados |
| Smoke Edge com respostas sintéticas | 4 cenários desktop/mobile, sem erros JS ou overflow |
| Compose config com valores fictícios / git diff --check | Aprovados |
| Core físico comparado ao checkpoint / ancestralidade | Aprovados |

O backend inclui regressões AT/Celsius, GPM, common-start, persistência periódica,
shutdown e recuperação com transportes simulados, além de relatórios, compartilhamento,
viewer e migrations. Evidência local: `build/product-tests/consolidation-backend.log`
e `consolidation-backend.xml`; navegador: `build/product-tests/ui/results.json`.
Avisos restantes: dependência Pyparsing, metadados JUnit/record_property, avisos de
migração futura do React Router e chunk do portal acima de 500 kB. Nenhum gate falhou
na execução final. Nenhuma correção adicional de produção foi necessária nesta rodada.

Conclusão: apto a avançar para **geração e smoke de candidata interna integrada 0.7.1**,
não para declarar o executável já validado ou homologação física/comercial.
