# ThermoPower 0.7.1 r5 — indisponibilidade histórica do GPM

Base de desenvolvimento: r4 `30dbddcc71453d388d6100be7bcd86bf2b4f6c48`, não aprovada.
Auditoria anterior ao código: `AVAILABILITY_R5_AUDIT.md`.

## Comportamento entregue

Tempo real, sessões históricas, prévia de relatórios, gráficos PDF/PNG/JPEG,
resumo executivo e viewer compartilhado usam os intervalos confirmados pelo backend.
O traço cinza identifica a transição da última medição disponível até a referência
0 W, permanece horizontal no intervalo confirmado e retorna à primeira leitura
real que encerrou a recuperação. Leituras reais permanecem azuis, inclusive 0 W real.
As coordenadas cinzas são uma camada de apresentação, nunca registros de medição.

Timeout de protocolo, atraso e lacuna sem origem conhecida não produzem esse traço.
Pausas encerram a evidência no último instante confirmado, sem unir a referência
através da pausa. Temperaturas preservam lacunas, sem conversão para zero.
Médias, picos, energia, tabelas CSV/XLSX e amostras persistidas não recebem zeros
visuais. O downsampling preserva as medições reais nas fronteiras de retorno.

## Evidência persistida e seus limites

A migration aditiva `0014_source_availability` cria somente a tabela de intervalos,
associados à sessão e ao dispositivo. Não altera medições nem reprocessa sessões.
O observador lê o estado em memória do GPM a cada 0,5 s, sem emitir comandos seriais.
Exige recuperação com erro de porta/driver/serial ou desconexão explícita; estado
`recovering` sozinho ou erro de protocolo/timeout isolado não são suficientes.
O término por reconexão exige uma leitura real finita posterior ao início.

O início é o instante em que o backend observou a indisponibilidade, não uma
estimativa retroativa do instante em que o cabo foi retirado. A confirmação periódica
limita a extensão do traço. Reinício do processo, falha de armazenamento ou interrupção
da observação não autoriza estender o zero por um intervalo desconhecido. Um hiato
de observação superior a 2 s encerra a evidência anterior; novas confirmações geram
outro intervalo. Não há reconstrução automática de eventos perdidos.

O histórico é persistido independentemente de o navegador estar aberto. A API
autenticada de disponibilidade é paginada. Recortes de relatórios e compartilhamentos
limitam os intervalos ao período autorizado. Detalhes são apresentados fora das curvas.

## Sessões antigas

**Sessões anteriores sem intervalos confiáveis não podem ser reconstruídas.** Isso
inclui a sessão `/sessoes/70` se seu banco só contiver medições, lacunas e os eventos
genéricos antigos. Esse banco não foi acessado nesta execução; não afirmamos que a
sessão 70 foi corrigida retroativamente. Ela não receberá zeros ou eventos inventados.
Nesses casos a interface informa a ausência de intervalos confirmados e mantém lacunas.

Novos ensaios com a r5 preservam os intervalos para posterior abertura no histórico,
relatórios e publicação. Sessões atravessando a atualização só terão evidência do
trecho observado pela r5. Encerre ensaios e faça backup antes de atualizar.

## Portal e compatibilidade

O contrato permanece `schema_version: 1`. A extensão opcional `availability` fica
dentro de cada série, sem IDs internos, credenciais ou payload serial. Snapshots
antigos continuam válidos. O contrato real da r4 foi testado aceitando a extensão;
viewers antigos a ignoram. Permissões e autenticação permanecem inalteradas.

O pacote inclui `portal-viewer/`, compilado com o mesmo componente validado. Essa
compilação usa `/api/v1` na mesma origem. Para hospedagem com API em outra origem,
gere o viewer com `VITE_PORTAL_API_ORIGIN` HTTPS adequada antes da publicação.
O conteúdo foi preparado e testado localmente: **nenhum portal externo foi implantado
ou atualizado**. O viewer em produção precisa receber a atualização autorizada para
mostrar os traços novos. Publicações antigas sem esses metadados não passam a ter
evidência automaticamente; uma republicação só pode incluir intervalos realmente
existentes na sessão.

O Windows não contém credenciais predefinidas do Render. Configurações anteriores
podem ser reutilizadas pelo cofre do mesmo usuário Windows. Configuração administrativa
permanece restrita a administradores; operadores autorizados continuam publicando.

## Atualização e rollback

1. Feche a instalação, encerre ensaios e preserve cópia completa dos dados e configurações.
2. Preserve os ZIPs/pastas r2, r3 e r4; extraia a r5 em pasta nova.
3. Confirme o banco efetivo (`THERMOPOWER_DATABASE_URL` prevalece; caso contrário,
   `THERMOPOWER_APP_DATA_DIR/data/thermopower.db`, ou o diretório local padrão).
4. O launcher verifica revisão, integridade e espaço. Antes de migration SQLite
   pendente, faz cópia consistente incluindo WAL confirmado, verifica integridade e
   grava manifesto SHA-256 em `migration-backups` ao lado do banco. Falha bloqueia
   a migration. PostgreSQL exige backup nativo verificado e migration administrativa.
5. Confira login, sessões anteriores, exportação e um ensaio sintético antes de bancada.

**R2/r3/r4 e 0.7.0 não conhecem a revisão 0014. Não aponte esses executáveis para
o banco atualizado.** Para rollback, feche a r5, preserve integralmente seu banco
atual e restaure um backup compatível anterior em outra pasta. Ensaios posteriores
ao backup permanecem no banco r5, que não deve ser sobrescrito. Não existe fusão
automática; preserve acesso pela r5 aos registros novos. Não apague nem edite
`alembic_version` e não execute downgrade manual em dados reais.

## Validação e preservação

Evidências reproduzíveis em `build/integrated-r5/`: o gerador usa o observador real
com estados sintéticos, persiste dois intervalos (60–100 s e 180–220 s), inclui pausa
260–270 s e produz prévia, PDF/PNG e tabelas. Screenshots capturam a aplicação real
em 1366×768, 1920×1080 e 390×844. A inspeção visual deve confirmar as duas descidas,
as duas referências de 0 W e os dois retornos no histórico, além das demais telas.

Drivers AT4532/GPM, protocolos, comunicação serial e política de recuperação foram
preservados. Identidade corporativa, DEMO, layout e permissões integradas permanecem.
Nenhum dado real da Britânia foi acessado ou alterado. Homologação física continua
pendente de bancada. Sem push, merge, deploy ou release pública.

Resultados, commit, SHA-256 e tamanho final: `build/integrated-r5/DELIVERY.md`.

Verificação anterior ao empacotamento: 88 testes frontend; suíte backend completa
executada, seguida de 56 regressões focadas aprovadas após corrigir atividade do
observador quando não há GPM ativo; migration PostgreSQL aprovada separadamente.
Doze cenários visuais da aplicação e três do viewer independente passaram nas três
resoluções. As capturas do histórico e as páginas dos PDFs foram inspecionadas:
duas descidas, duas referências horizontais de 0 W e dois retornos estão visíveis;
a pausa permanece lacuna. Isso não substitui homologação física nem aceite da Amanda.
