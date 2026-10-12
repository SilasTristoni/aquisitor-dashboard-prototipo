# Auditoria de confiabilidade e usabilidade — 0.7.0

Data: 11/10/2026. Base: `401e5825ba721e135be3f588b1ec9b2caa13fbbe`, branch
`master`. A árvore estava limpa no início. Referências: `AGENTS.md` e
`AT4532_CELSIUS_TRIGGER_070.md`. Esta auditoria não homologa aquisição física.

Foram usados históricos sintéticos, fixtures e bancos isolados. Nenhuma porta
física foi aberta. Os dois novos diagnósticos da Britânia continuam pendentes;
nenhuma conclusão sobre a causa das interrupções AT/GPM foi antecipada.

## Classificação dos problemas reproduzidos

| ID | Prioridade / componente | Reprodução e impacto | Regressão e situação |
|---|---|---|---|
| A1 | **P0**, `backend/app/services/period_workbook.py` | Exportar título `=3+3` e evento com título `=1+1`/descrição `=2+2`. O XLSX original contém três células de fórmula. Conteúdo fornecido por usuário pode executar fórmulas ao abrir o relatório, comprometendo segurança e integridade do documento. | `test_workbook_preserves_untrusted_text_without_executable_formulas`: exportação real, leitura com openpyxl, nenhuma célula de fórmula e texto preservado. **Corrigido**: texto literal no workbook; referências dos gráficos permanecem independentes. |
| A2 | **P0**, `backend/app/windows_launcher.py` e `backend/alembic/env.py` | Aplicar migrations com banco em diretório `Lab 100%`. `ConfigParser` interpreta `%` e lança `ValueError`, impedindo inicialização. | `test_windows_migrations_accept_percent_in_application_directory`: subprocesso real executa migrations em SQLite isolado. **Corrigido**: escape apenas na entrada do ConfigParser, sem modificar a URL usada pelo banco. Não houve migration de esquema. |
| A3 | **P0**, `backend/app/services/acquisition.py::_read_loop` | Fonte sintética entrega uma amostra logo após o último flush e permanece silenciosa. Após 3 s, a amostra continua só no buffer, embora o código use um limiar de 2 s. A avaliação do flush depende de outra leitura. Encerramento abrupto nesse intervalo perde dados ainda não confirmados no banco; a espera pode exceder 2 s indefinidamente. | `test_idle_source_persists_buffer_within_flush_deadline`: reprodução com o loop real e fonte silenciosa, sem hardware. **Pendente por restrição explícita de core**; `xfail(strict=True)` documenta o defeito, não equivale a aprovação. Regressão futura deve incluir morte de processo, banco indisponível e confirmação de gravação sem próxima amostra. |
| A4 | **P1**, `backend/app/services/period_reporting.py::_integrate_energy_wh` e `frontend/src/pages/DashboardPage.tsx` | Potências `100, null, 100 W` nos segundos `0, 5, 10`: o filtro removia a indisponibilidade e calculava `0,277778 Wh` através dela. O indicador sugere energia observada em intervalo sem dados suficientes. | `test_energy_does_not_bridge_explicit_unavailable_power` e teste UI “energia monitorada não integra através de potência indisponível”. **Corrigido**: intervalo com qualquer ponta indisponível é excluído; nenhuma amostra ou timestamp é modificado. |
| A5 | **P1**, `backend/app/services/period_reporting.py::_power_cycle_analysis` | `100,100,0,0 W` nos segundos `0,1,120,121`: duração média de ciclo de 120 s apesar da lacuna de 119 s e apenas 1 s observado ligado. | `test_cycle_duration_does_not_span_an_unobserved_gap` e controle de energia/ciclo contínuos. **Corrigido**: lacuna acima do limite configurado ou potência indisponível interrompe o ciclo em análise. |
| A6 | **P1**, `frontend/src/pages/DashboardPage.tsx` | Status conectado, sem amostra ou última leitura há 120 s: indicador verde e “Fontes prontas” sugeriam aquisição atual. | Dois cenários no `DashboardPartialConnection.test.tsx`. **Corrigido**: conexão e leitura recente têm textos distintos; recência usa o maior entre 10 s e três intervalos esperados. É exclusivamente apresentação: iniciar, pausar, retomar e common-start mantêm o comportamento existente. |

As quatro primeiras reproduções de relatório/inicialização falharam antes das
correções (`build/audit-070/repro.xml`); os dois cenários de conexão sem leitura
também falharam antes da alteração (`ui-repro.log`). A classificação foi
apresentada antes das respectivas correções.

## P2 — melhorias opcionais, sem implementação nesta rodada

| Componente | Cenário / impacto | Validação necessária antes de uma evolução |
|---|---|---|
| `docs/DATABASE.md`, operação de backup | As instruções recomendam backup/restauração, mas não definem frequência, retenção, responsável, RPO/RTO ou ensaio periódico. O procedimento comercial fica dependente da implantação. | Restaurar banco, configurações e segredo local em máquina isolada; medir RPO/RTO e testar links/autenticação conforme política da instalação. A falta de rotina operacional não foi tratada como nova funcionalidade de produto. |
| `period_reporting.py::_suggest_stabilization` | A sugestão de estabilização merece cobertura específica para dados esparsos e janelas com lacunas. A confirmação humana continua exigida. Não houve reprodução suficiente para classificar erro obrigatório. | Históricos com patamar curto, canal aberto e grande lacuna; verificar duração observada e indicação de confirmação. |
| `backend/app/windows_launcher.py`, operação Windows | O smoke verifica servidor e retomada após encerramento forçado; não verifica a experiência completa de fechar navegador versus encerrar processo ou uma sequência longa de uso comercial. | Ensaio manual do executável existente, sessão simulada, encerramento normal e reinício, sem conectar equipamento físico. |

## Verificações e limites

- **Persistência e ciclo de vida:** os testes existentes exercitam falha de commit,
  retenção do buffer, falha de desconexão, rollback de pausa/finalização e vínculo
  da sessão na reconexão. Nenhuma dessas rotinas foi modificada. A falha A3
  permanece: aprovação dos caminhos de encerramento controlado não garante
  durabilidade do que ainda está apenas em RAM após queda de energia.
- **Após interrupção inesperada:** o estado `running`/`paused` persistido pode
  sobreviver ao processo, enquanto runtimes são memória. A reconciliação de sessão
  órfã precisa de avaliação específica de retomada e está fora das alterações
  autorizadas. Não foi validada continuidade automática de sessão física.
- **Período oficial, médias e eventos:** os testes de análise verificam recorte,
  preservação do histórico, anotação, exportação legada e restauração do período
  completo. Médias são das observações existentes; não foram criadas amostras
  intermediárias. A integração trapezoidal mantém seu limite temporal existente
  de 60 s por padrão; A4 corrige indisponibilidade explícita, não redefine essa
  política ou a detecção de todas as lacunas curtas.
- **Viewer e compartilhamento:** cobertura de autorização, downloads, senha,
  expiração, revogação, permissões por formato e limitação de acesso. Exportações
  públicas são verificadas pelos testes existentes. Compartilhamentos são apenas
  fixtures descartáveis nos testes; nenhum link real foi publicado.
- **Lacunas visuais:** a ausência de interpolação nas linhas persistidas não prova
  ausência de união visual entre pontos. Os gráficos React e as coordenadas XLSX
  usam observações da própria fonte e `connectNulls=false`/`display_blanks=gap`,
  mas uma lacuna sem linha explícita nula merece inspeção gráfica: pode ser ligada
  visualmente por uma reta. **Suspeita de P1 ainda sem reprodução visual nesta
  rodada**, não corrigida nem declarada resolvida. Regressão necessária: renderizar
  pontos em 0/1/120/121 s na sessão, dashboard, compartilhamento e Excel e inspecionar
  os segmentos; nenhuma solução deve criar medições ou alterar timestamps reais.
- **Backup SQLite:** a API nativa de backup copiou banco com histórico sintético;
  a restauração em outro arquivo preservou o dump completo, inclusive valores e
  horários. `integrity_check=ok` e `foreign_key_check` vazio. Isso não substitui
  backup periódico da instalação, nem valida cópia simples de arquivo com banco
  em escrita. Preservar também configuração e `jwt-secret.key` em backup protegido.
- **Migrations e PostgreSQL:** upgrade SQLite e testes de migrations existentes
  são executados. O ajuste de `%` não altera tipos nem esquema. Não há servidor
  PostgreSQL nem Docker disponível para ensaio real de upgrade/restauração;
  compatibilidade não é apresentada como validada integralmente em PostgreSQL.
- **Executável Windows existente:** duas inicializações com `/health=ok` e SPA
  acessível, encerramento forçado do processo criado pelo smoke e reinício em
  diretório isolado. Banco íntegro, credenciais e segredo mantidos. Nenhuma fonte
  foi conectada. Esse binário anterior **não contém as correções desta auditoria**;
  não foi recompilado. Evidência: `build/audit-070/windows-smoke.json`.

## Alterações

- `backend/alembic/env.py`
- `backend/app/windows_launcher.py`
- `backend/app/services/period_reporting.py`
- `backend/app/services/period_workbook.py`
- `backend/tests/test_reliability_audit.py` (novo)
- `frontend/src/pages/DashboardPage.tsx`
- `frontend/src/test/DashboardPartialConnection.test.tsx`
- Este relatório.

Não foram alterados adaptadores, comandos SCPI, framing, parsers, polling,
recovery, reconnect, common-start ou lógica de pausa/continuação. Não houve
commit, push, tag, release ou empacotamento Windows. O build de frontend é apenas
validação do código, sem criação de pacote de distribuição.

## Resultados de validação

Logs locais em `build/audit-070/` (ignorados pelo Git):

- Foco em relatório, análise, compartilhamento e migrations: **20 aprovados**
  (`focused.xml`).
- Novos testes de auditoria, backup e preservação de cálculos: **6 aprovados,
  1 falha esperada** pelo P0 A3 (`audit-final.xml`).
- Frontend completo: **54 aprovados e uma falha no seletor do novo teste**.
  O seletor exato foi corrigido para considerar o restante do texto do elemento;
  reteste somente de `DashboardPartialConnection.test.tsx`: **10 aprovados**.
  Os **55 casos** ficaram cobertos pelas execuções, sem repetir a suíte completa.
  Evidências: `frontend-full.log`, `ui-final-focused.log`.
- `npm run lint`, `npm run typecheck`, `npm run build`: **aprovados**.
- Ruff nos arquivos Python alterados: **aprovado**; `git diff --check`: sem erros.
- Smoke do executável existente e restauração SQLite: **aprovados nos limites
  descritos acima**.
- `docker compose config --quiet`: **não executado**, comando Docker indisponível.
- Backend completo, executado **uma vez**: **289 aprovados, 1 falha esperada
  (`xfail` A3), 21 avisos**, em 268,28 s (`backend-full.xml` e `backend-full.log`).
  Inclui regressões AT/GPM com fixtures, persistência, pipeline, migrations,
  análise, permissões e exportações. Os avisos são de depreciação de dependências
  gráficas e compatibilidade de propriedades de teste com JUnit xunit2.

Git permanece em `master`, HEAD `401e5825ba721e135be3f588b1ec9b2caa13fbbe`.
Estado final: seis arquivos rastreados modificados e dois novos (teste e
relatório), listados acima. `scope-verification.json` compara SHA-256 com o
snapshot inicial e confirma ausência de alterações nos arquivos protegidos.

## Acompanhamento posterior — persistência pendente

Após autorização específica para corrigir exclusivamente a persistência, A3
recebeu um gravador periódico externo ao core. A reprodução antes marcada com
`xfail` agora exige sucesso. Os resultados acima permanecem como registro da
auditoria original; a correção, seus testes e limites de durabilidade estão em
[PENDING_SAMPLE_PERSISTENCE_070.md](PENDING_SAMPLE_PERSISTENCE_070.md).
