# Consolidação e confiabilidade — 11/11/2026

Auditoria anterior à implementação: árvore limpa em `feat/product-experience-071`,
commit `aef2b6fa2031a6780a9768bd876898124505d5a3` (candidata r5). `fetch --all --prune`
concluído; `master` e `origin/master` em `862c8ce1`. Versão comercial preservada.
Referências completas, commits exclusivos e arquivos por branch foram registrados
em `build/reliability-consolidation/branch-audit.json`.

| Referência | Commit | Decisão |
| --- | --- | --- |
| feat/product-experience-071 | aef2b6f | Incorporar os 13 commits posteriores à master, incluindo r5 e correções anteriores |
| origin/feat/product-experience-071 | 83116a2 | Já contida na sequência local |
| fix/physical-reliability-070 e origin | 7059784 | Três commits posteriores à master, todos contidos na r5 |
| security/audit-070 | 9727c71 | Dois commits posteriores à master, contidos na r5 |
| feature/at4532-celsius-trigger e origin | 401e582 | Já ancestral da master e da r5 |
| feature/at4532-gpm8213-integration e origin | a1f9e7f | Já incorporada por merge histórico |
| feature/period-reports-usb-discovery-windows-package e origin | e9e74f4 | Já incorporada por merge histórico |
| origin/feature/client-homologation-virtual-usb-lab | 718c094 | Não incorporar: alternativa 0.5.0 incompatível com os contratos físicos atuais |

A branch USB virtual diverge de `fca55a4`, possui um commit exclusivo e está 38
commits atrás da master. A prévia `git merge-tree` identifica conflitos em 26
arquivos, inclusive adaptadores, aquisição, descoberta, launcher e build. Seu plano
pressupõe adaptadores físicos bloqueados, diagnóstico sem SCPI e um segundo launcher
virtual. Hoje há protocolos validados, simulador utilizável, DEMO isolado, diagnóstico
seguro e empacotamento integrado. Não se importa essa arquitetura antiga ou seus
scripts de release. A branch permanece intacta para referência, sem ser declarada
homologada ou integrada. Evidência: `virtual-lab-merge-preview.txt`.

O stash histórico `f80f5a1` também foi examinado, sem aplicação ou remoção. A aceitação
SCPI `:NUM:NORM:NUMB` já existe no parser atual. Três funções de teste do stash
(11 casos parametrizados, incluindo preservação do RX abreviado) não estavam na
r5 e foram recuperadas sem modificar o parser. A contagem estática de testes no script antigo não é uma
alteração funcional a reaplicar. O outro worktree, em `fix/physical-reliability-070`,
não foi alterado. Não havia mudanças locais não commitadas a preservar.

Criada `integration/reliability-071` a partir da master e avançada por fast-forward
até a r5. Nenhum conflito foi resolvido escolhendo versões antigas. A master só será
atualizada após validação final, nova conferência remota e revisão do diff físico.

## Investigação da recuperação

A persistência existente já confirma lotes durante a aquisição, com tentativa a
cada 2 segundos, rollback, backpressure e tratamento de disco cheio. Deques de
observação são limitadas; o preparo de início tem limite de 4.096 leituras. Não será
criado outro gravador ou fluxo serial. Dados somente em RAM não são recuperáveis.

O estado running/paused sobrevive a uma queda, mas os runtimes não. A conexão atual
associa automaticamente uma sessão nesses estados: a reconciliação precisa ocorrer
antes de aceitar requisições, exigindo decisão do operador para sessões órfãs.
Os métodos existentes `resume_session`/`attach_session` restauram o maior sequence
persistido e suportam fontes independentes. Serão reutilizados sem alterar o core.

O serviço novo terá exclusão entre instâncias por banco (lock de arquivo local no
SQLite; advisory lock dedicado no PostgreSQL), identidade persistente e heartbeat.
Expiração de heartbeat sozinha não autoriza tomar uma sessão de outra instância.
O SQLite manterá journal existente e synchronous FULL explícito. A gravação não
dependerá da finalização normal. Encerramento controlado e interrupção inesperada
terão motivos distintos, com decisão auditada.
