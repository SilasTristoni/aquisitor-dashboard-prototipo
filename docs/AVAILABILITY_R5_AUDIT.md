# Auditoria anterior à correção r5

Base limpa: `30dbddcc71453d388d6100be7bcd86bf2b4f6c48`, branch
`feat/product-experience-071`. A r4 não está aprovada.

1. `Gpm8213Adapter.start_reading` guarda `connection_state` e `recovery_status`
   em memória. A recuperação fecha a porta e tenta reconectar; sucesso de identificação
   não encerra a recuperação até chegar leitura válida. Não há persistência dos pares.
2. `AcquisitionService` grava `SystemEvent` para conexão/desconexão e erro terminal.
   A desconexão genérica não leva `session_id`; recuperação interna não produz par
   de eventos confiável com início/fim. Logs textuais não serão convertidos em prova.
3. `PeriodReportDataService` entrega `gaps` inferidos da cadência e anotações manuais.
   SessionDetailPage, preview de relatórios e SharedSessionPage não recebem intervalos
   confirmados de disponibilidade. PDF/PNG segmentam séries reais, sem esse contrato.
4. r3/r4 usam `useSourceHistory` no navegador ao vivo. A r4 apenas corrige domínio,
   filtragem de canais e poluição visual. Isso não reconstrói histórico nem ligação
   de retorno à primeira medição real. A imagem enviada mostra essa limitação.
5. O resultado exigido precisa de camada visual comum: descida, referência 0 W e
   retorno, alimentada por intervalos persistidos, separada das medições oficiais.
6. Sessões antigas sem registros confiáveis não permitem reconstrução. Não haverá
   backfill baseado em lacunas, zeros ou erros genéricos. Nenhum banco real foi aberto.

Decisão: tabela aditiva por migration para intervalos de indisponibilidade observada;
observador independente lê apenas estado em memória já produzido pelo backend, sem
comandos seriais ou alterações de drivers/recuperação. Erro de protocolo/timeout
isolado não basta: exigimos evidência de porta indisponível/erro serial com recuperação
ou desconexão explícita. Início é o instante observado, sem retroagir para a última
amostra. Fim é a primeira leitura real após a recuperação; pausas e interrupções do
observador encerram a evidência no último instante confirmado. Uma interrupção do
processo não autoriza prolongar o zero até o fim da sessão.

Extensão opcional dentro de cada `series` do snapshot v1: consumidores antigos
ignoram o campo, novos consumidores aceitam ausência dele. Sem novos campos internos
no payload público, sem alteração de permissões, credenciais ou documentos tabulares.
