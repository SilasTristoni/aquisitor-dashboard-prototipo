# Recuperação de ensaios e execução prolongada

Implementação incremental sobre a candidata 0.7.1 r5 (`aef2b6f`), sem mudança da
versão comercial. A auditoria de branches está em `BRANCH_CONSOLIDATION_071.md`.

## Operação

Ao reiniciar o backend, ensaios que permaneceram em execução ou pausados são
reconciliados antes de a API aceitar conexões. O operador vê um aviso nas telas
Tempo real e Sessões com nome, identificador, início, última medição confirmada,
contagens por fonte e equipamentos associados. A página administrativa do portal
continua independente das consultas de sessões.

Retomar exige confirmação e reutiliza `resume_session`/`attach_session` existentes.
O identificador, início, histórico e sequências persistidas são mantidos. Cada fonte
é reconectada independentemente: uma pode continuar se a outra estiver indisponível.
Se nenhuma conectar, o ensaio continua recuperável. Não há comandos físicos no
startup da recuperação. Um equipamento ocupado por outro ensaio bloqueia a retomada.

Encerrar como interrompido preserva medições e exportações e grava o estado
`interrupted_closed`. O término é o instante da decisão do operador; o início
original não muda. A linha temporal inclui o período sem aquisição. Finalizações
normais continuam `finished` e não geram recuperação.

Fechar normalmente a aplicação com um ensaio aberto cria uma suspensão controlada
(`suspended`, motivo `controlled_shutdown`), exibida com texto próprio. Uma morte
inesperada gera `interrupted`. O software não atribui a causa a queda de energia:
falha de processo, desligamento do computador e outras interrupções podem produzir
o mesmo estado observável.

## Persistência, identidade e concorrência

A migration aditiva `0015_session_recovery` cria `application_instances` e
`session_recovery`. Os eventos de decisão ficam em `system_events`, com operador,
instância e horário. Uma intenção é confirmada no banco antes da conexão física,
permitindo recuperar também uma queda ocorrida durante a própria retomada.

O processo mantém exclusão por banco durante todo o lifespan:

- SQLite local: lock de um byte mantido por handle do sistema operacional no arquivo
  adjacente `.acquisition.lock`; ele é liberado pelo Windows/Linux ao morrer o processo.
  A existência do arquivo não significa que o lock esteja ocupado. Não o remova.
- PostgreSQL: advisory lock de sessão em conexão dedicada; uma segunda instância é
  recusada. Se essa conexão falhar, o supervisor recusa novas recuperações/inícios
  e solicita pausa das fontes locais pelo serviço existente.

Uma instância válida com heartbeat atrasado não perde posse por timeout. Não há
tomada automática baseada somente no relógio. A aplicação de aquisição deve usar
**um worker por banco**; múltiplos workers e SQLite em compartilhamento de rede não
são modos suportados por este mecanismo. O portal externo tem processo e banco
próprios e não participa desse lock.

Heartbeat/checkpoints de aquisições vinculadas ocorrem a cada 5 s, com consultas MAX indexadas e timeout de
lock SQLite de 25 ms. O último checkpoint indica observação de dados já confirmados,
não uma promessa sobre dados ainda em memória. Na inicialização e na consulta de
recuperação, as contagens são recalculadas no banco. Migração e backup continuam
pelos mecanismos existentes; não há backfill de amostras.

O gravador original permanece intacto: lotes, tentativa de flush a cada 2 s,
rollback, backpressure e retries limitados para falhas de armazenamento. SQLite usa
`synchronous=FULL` explícito em cada conexão; o modo de journal da instalação é
preservado. Isso solicita sincronização durável de commits, mas depende das garantias
do disco/controlador/SO. Não é promessa de recuperação de amostras ainda em RAM.

## Lacunas e relatórios

Eventos de retomada delimitam épocas de aquisição nas cópias usadas para análise.
Uma interrupção curta também quebra a integração de energia, os ciclos calculados
e os segmentos PDF/PNG; as prévias recebem lacunas para potência e temperatura.
Não são adicionados zeros, linhas de medição, timestamps físicos ou amostras ao banco.
Os traços visuais de zero da r5 continuam exclusivos de desconexões GPM confirmadas;
queda do processo não se torna desconexão física presumida.

Ao reconectar o WebSocket, a pequena janela de tempo real é renovada, evitando ligar
cache antigo a leituras posteriores. O histórico completo continua disponível no
banco. O contrato WebSocket e as regras físicas de timestamps não foram alterados.

Relatórios já usam handlers síncronos executados pelo FastAPI fora do event loop.
As consultas ORM de amostras passam a ler lotes de 500 elétricas/256 térmicas,
evitando manter centenas de milhares de objetos de canais simultaneamente. A busca
de estabilização consulta apenas a janela de 180 s, com os mesmos critérios. A série
sincronizada de apresentação usa cursor progressivo e mantém a regra anterior de
amostra mais próxima/tolerância/empate; isso não muda a sincronização de aquisição.
As prévias mantêm o downsampling existente, sem alterar as medições originais.

## Armazenamento e limites

O supervisor consulta capacidade do volume local e tamanho do banco/journal a cada
30 s: aviso abaixo de 512 MiB e crítico abaixo de 100 MiB. Mudanças para capacidade
baixa são registradas como evento de diagnóstico. Falhas de escrita e esgotamento
de retries continuam expostos por fonte, e a interface alerta o operador. Nenhuma
medição é excluída automaticamente. Espaço livre não prova ausência de quota ou
falha do dispositivo; os erros de escrita continuam sendo tratados pelo gravador.
Capacidade do servidor PostgreSQL exige monitoramento do servidor, sem inferência
a partir do disco da máquina cliente.

Não encerre a aplicação com amostras pendentes por falha de disco se houver como
restaurar a escrita. Se a gravação da decisão falhar, a retomada tenta pausar e
desvincular pelas rotinas existentes, preservando buffers que não puderem ser
confirmados. Um shutdown cuja escrita falhe pode aparecer no próximo início como
interrupção inesperada, pois a marca de encerramento não foi confirmada.

Relatórios ainda mantêm cópias dos valores selecionados em memória; o custo cresce
com o período e com a concorrência de exportações. Os ensaios acelerados representam
20/24 horas de timestamps e volume, não 20/24 horas contínuas de operação física.
Persistência após morte forçada do processo não comprova queda elétrica real.
Homologação de bancada AT4532/GPM e validação operacional contínua permanecem pendentes.

## Atualização

Encerre ensaios e faça backup antes de migrar. O launcher preserva o backup SQLite
pré-migration, incluindo o WAL confirmado. PostgreSQL exige backup administrativo.
Executáveis até r5 não conhecem a revisão 0015: não os aponte para o banco atualizado.
Para rollback, mantenha o banco novo e restaure o backup anterior em outra pasta;
não sobrescreva ensaios posteriores, não edite `alembic_version` e não force downgrade.

O pacote Windows não contém credenciais predefinidas do Render. Configurações
anteriores podem ser reutilizadas pelo cofre do mesmo usuário Windows.

Resultados, métricas, screenshots e estado final Git serão registrados em
`build/reliability-consolidation/DELIVERY.md` e no relatório final da consolidação.
