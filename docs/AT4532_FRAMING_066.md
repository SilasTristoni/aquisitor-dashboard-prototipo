# Fronteira serial AT4532 — 0.6.6-client-preview

**Candidato de engenharia; homologação física pendente.** Esta rodada corrige a
mutilação de frames. Não altera o parser, comandos SCPI, polling, timeout de FETCH,
interface, relatórios ou protocolo do GPM-8213.

## Evidência e causa técnica

Em 28/09/2026, a build 0.6.5 (`57068aea`) descartou seis bytes pendentes
`54 43 50 2D 33 32` (`TCP-32`) antes de enviar FETCH. Os 688 bytes restantes,
começando em `,T:`, foram associados à nova consulta e rejeitados corretamente.
Os seis bytes capturados mais os 688 bytes capturados formam um TCP-32/CP936 válido,
com 694 bytes, 32 canais e terminador CRLF. O caso ocorre em probes e conexões.

O defeito está na suposição de que `in_waiting` contém uma resposta antiga inteira.
Ele pode conter apenas o início de um frame ainda em transmissão. A origem exata
da resposta pendente não é identificável pelas capturas; não se atribui automaticamente
o frame do segundo ZIP ao FETCH que sofreu timeout no primeiro.

O descarte pré-TX remonta a `992cf11`, anterior à tag `v0.6.3-client-preview`.
Os quatro arquivos centrais de transporte/adaptador/probe/aquisição são idênticos
entre essa tag e a build 0.6.4 `34c59ab`. `32f05c4` alterou I/O, locks e recuperação
na 0.6.5, mas não introduziu o descarte. O commit que desencadeou a recorrência
física não está estabelecido; não se declara uma causa temporal sem bancada.

## Política implementada

- Exclusiva do `At4532SerialTransport`; o transporte GPM conserva sua política.
- Antes de TX, bytes pendentes são lidos sob o mesmo lock da consulta. Nenhum novo
  comando é enviado enquanto o frame anterior está sendo completado.
- A ressincronização tem orçamento total de **2 s**, separado do timeout de FETCH,
  com limite de **65.536 bytes** por operação. O orçamento mantém a ordem de grandeza
  da leitura existente e cobre o frame observado de 1,266 s; sua suficiência depende
  de validação física. Não prolonga o timeout da resposta da nova consulta.
- Somente LF encerra um frame AT. Depois de um frame completo, observa-se até
  **50 ms sem novos bytes**, dentro do mesmo orçamento, para detectar outro frame
  já em chegada. Silêncio não é aceito como terminador de um frame parcial.
- Frames tardios completos são registrados integralmente em HEX e descartados como
  unidades. Não são publicados, persistidos ou reutilizados como resposta ao novo TX.
- Sem LF, os bytes ficam retidos entre tentativas. A operação retorna
  `incomplete_late_frame`, com `tx_sent=false`; nenhuma resposta artificial `,T:`
  é criada. Uma resposta parcial da consulta retorna `incomplete_frame` e é retida
  no worker, inclusive quando a coroutine é cancelada.
- Após timeout, mesmo com `in_waiting=0`, a próxima operação aguarda a janela de
  settle/resync. Configuração, probe, aquisição e fechamento utilizam essa política.
- O AT não executa `reset_input_buffer`, inclusive na abertura. Bytes já disponíveis
  são preservados para a primeira ressincronização.
- Um timeout ou frame incompleto isolado não reabre a COM. Erro físico/porta fechada
  permite recuperação; falha de protocolo exige pelo menos **três falhas consecutivas**
  e expiração do watchdog existente. Backoff de 1–30 s e exclusividade permanecem.
- No fechamento explícito ou recuperação irrecuperável, ainda se tenta completar o
  frame. Se isso não for possível, os bytes abandonados são registrados e contados
  em `discarded_partial_bytes`. Esse evento é uma falha visível, não um sucesso de
  ressincronização nem um resultado aceitável no ensaio normal.

A janela limitada não prova que o instrumento jamais enviará bytes depois dela.
Não há identificador de requisição no protocolo que autorize essa inferência.
Casos que excedam a janela precisam de evidência de bancada; não se inventa tamanho
fixo, resposta ou associação de amostras para escondê-los.

## Diagnóstico

Contadores da conexão lógica: `late_frames`, `completed_late_frames`,
`incomplete_late_frames`, `discarded_complete_frames`, `discarded_partial_bytes`,
`resynchronizations` e `resynchronization_failures`. Permanecem acumulados durante
reaberturas do mesmo transporte. `incomplete_late_frames` conta tentativas que
terminaram com fragmento retido; o mesmo fragmento pode exigir mais de uma tentativa.

Cada evento registra `bytes_present_before_resync`, `retained_partial_bytes`,
`bytes_completed` (bytes lidos nessa janela), `full_frame_length`, `prefix`,
`terminator_found`, `elapsed_ms`, `boundary_clean` e os bytes integrais dos frames
ou do fragmento retido. Há histórico limitado aos últimos 32 eventos no ZIP do probe,
além dos logs e da fronteira da consulta. Os contadores aparecem no status da aquisição
e no coletor HTTP. `tx_sent=false` e `timestamp_tx=null` distinguem tentativas bloqueadas
de comandos transmitidos; `fetch_attempts` inclui tentativas bloqueadas.

## Regressões automatizadas

`backend/tests/test_at4532_input_boundary.py` usa o transporte real sobre uma serial
controlada, com `in_waiting`, bloqueio de `read(n)` e relógio virtual. Inclui:

- fixture física de 694 bytes e rejeição explícita do sufixo `,T:`;
- divisões 1+693, 2+692, **6+688**, 50+644, 347+347 e múltiplos chunks;
- resposta tardia após timeout, inclusive começando quando `in_waiting` ainda é zero;
- resposta parcialmente recebida antes do timeout, completada na ressincronização;
- TX bloqueado por fragmento incompleto, conclusão posterior, múltiplos frames;
- fechamento após timeout, auditoria de fragmento irrecuperável e cancelamento;
- Testar leitura e Teste completo usando o mesmo transporte;
- regressão separada CRLF/timeout/descarte do GPM;
- soak de 1.000 leituras válidas únicas, dez respostas tardias e uma perda física
  simulada com reconexão necessária. Nenhum frame tardio vira medição.

Validação anterior ao empacotamento em 28/09/2026: **219 testes do backend aprovados**,
incluindo os 22 casos novos; **41 testes frontend aprovados**, Ruff, ESLint, TypeScript,
Vite e configuração Compose aprovados. O Compose foi executado com o binário oficial
standalone disponível em `build/tools/docker-compose.exe`.

A primeira execução completa teve 208 aprovados e oito erros de preparação por
`WinError 5` no diretório temporário global do Pytest. A repetição com `--basetemp`
exclusivo em `build/` passou integralmente; não houve alteração de teste para ocultar
falhas. Os avisos restantes são de Matplotlib/Pyparsing e React Router.

O soak pelo transporte real usou 1.011 tentativas: **1.000 leituras únicas, dez
timeouts com dez frames tardios completos isolados e uma perda física simulada**.
Houve uma reconexão necessária, zero desnecessárias, zero `unknown_responses`,
zero frames mutilados e zero `discarded_partial_bytes`. São resultados virtuais.

O empacotador repete os gates após o versionamento e só promove o ZIP depois dos
smokes do executável e da verificação integral do manifesto SHA-256. Os resultados
desse gate final ficam em `TEST-RESULTS.txt` e `TEST-RESULTS.xml` dentro do pacote.

## Homologação física obrigatória

Na máquina da cliente, com o software do fabricante fechado:

1. Testar leitura; exportar diagnóstico.
2. Teste completo; exportar diagnóstico.
3. AT sozinho por cinco minutos.
4. AT + GPM por dez minutos.
5. Iniciar sessão combinada e conferir persistência, canais, Open e valores reais.
6. Soak de 30–60 minutos, com `monitor-serial-stability.py`, registrando os dois
   dispositivos e mantendo os ZIPs e as observações integrais.

Aceitar apenas com zero mutilações/prefixos perdidos, zero `unknown_response`
causado por framing, zero `discarded_partial_bytes`, zero reconexões desnecessárias,
sem repetição de frames ou dados fabricados. Verificar separadamente retorno após
perda física da COM e continuidade do GPM. Não declarar homologação com testes virtuais.

A divergência observada entre cadastro de 3.000 ms e adapter/probe de 1 s permanece
documentada e **não foi alterada**. Sua avaliação depende da bancada após esta correção.
