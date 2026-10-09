# AT4532 Britânia — decisão física de 06/10/2026

O perfil AT4532/TCP-32 passa a adquirir com `SYST:UNIT CEL`, no mesmo adaptador,
transporte, parser, probes e runtime de produção 0.7.0. Não há driver paralelo.
O comando é documentado como configuração de unidade; seu uso periódico como
trigger é evidência física deste equipamento, não inferência sobre o manual.
Não restaurar loop FETCH sem nova evidência física. Estabilidade contínua da
candidata ainda depende da próxima bancada; não há homologação ou release.

## Evidência analisada

Os quatro ZIPs de 06/10 foram lidos integralmente (JSON/JSONL/logs), incluindo
estados, transações, erros, contadores e captura controlled repeated-celsius.
Os dois pacotes físicos possuem manifestos verificados. Os dois pacotes de
suporte não possuem manifesto; logs antigos têm linhas parciais por rotação.
Contagens do JSONL inteiro abrangem vários processos e não são contagens de uma sessão.

| ZIP (ThermoPower-Diagnostico-) | SHA-256 |
|---|---|
| 2026-10-06T20-24-13-478Z.zip | 7d04b18ddb71262867c3357131c3d22b7279390cbb5e0ddb74efc75d14c85ca1 |
| 2026-10-06T21-50-11-215Z.zip | 21e8cff0227c2e31b6dda09e4fb165ebd4fa0c10ddc82ffe52f65cbc4d02e76f |
| 2026-10-06T21-59-01-872Z.zip | b7f6a558c47f6e2ddc31d7eb07807be0c4ed2a71609b656978e05c9580787506 |
| 2026-10-06T21-59-36-263Z.zip | d8ecd2f64de1973316c40a67fa1b0c4e198086f0cd738cdbb6aca62d2436df87 |

Captura `20261006-215339-452b8162`, COM5, 19200/8-N-1: passivo 5 s, RX=0.
Três Celsius, separados por 5,019953 e 5,028783 s, geraram um frame cada:

| Frame | Timestamp original | Primeiro byte | Frame completo | SHA-256 |
|---|---|---|---|---|
| 1 | T:2026/10/06 18:58:52 | 10,619 ms | 1,525090 s | b599824c10c3180ab9ae6257fad47ef35179c456d916164cab8adc80909f9a80 |
| 2 | T:2026/10/06 18:58:57 | 9,493 ms | 1,487176 s | a62c63d6bb02ac5abcfb66ebc8a5e0d722dd32d7062d18a8b3972c62e8ba16ec |
| 3 | T:2026/10/06 18:59:02 | 11,894 ms | 1,792747 s | 1b31a42f5762c2992bd35824909654bb42c3ffae66ffb9fa72cc92411314399f |

Todos: 694 bytes, TCP-32, CP936, CRLF, 69 campos, 32 canais primários.
CH01–24 Open; CH25–32 numéricos. Temperaturas mudam entre cada par, além dos
timestamps e hashes. Fixtures preservam bytes e metadados exatos em
`backend/tests/fixtures/at4532_repeated_celsius_20261006.json`.
O relógio do equipamento está cerca de cinco minutos adiantado em relação ao PC;
os dois timestamps permanecem preservados, sem correção ou fabricação.

O snapshot final da aquisição antiga registra 17 tentativas FETCH, 1 leitura,
16 timeouts, 4 reconexões e lacuna máxima de 123,263 s, com COM aberta e zero RX
na última falha. GPM permanece saudável. A única leitura antiga não comprova
FETCH: Celsius imediatamente anterior pode ter iniciado aquele frame. A
caracterização isolada resolve a atribuição, pois não transmite FETCH.

## Política implementada

- `READY` → aguardar TX anterior + intervalo e fronteira segura → Celsius →
  `WAITING_FRAME` → validar TCP-32/dedupe → uma leitura nova → `READY`.
- `AT4532_TRIGGER_INTERVAL = 5.0`; configuração por
  `THERMOPOWER_AT4532_TRIGGER_INTERVAL_SECONDS`, finita e mínimo 5 s nesta etapa.
  Intervalos menores exigem nova bancada. Frequência esperada segue o valor configurado.
- Timeout de frame 4 s, mais de 2 s de margem sobre o maior frame observado.
  Leitura incremental até CRLF, sem timeout curto entre chunks nem reset de entrada.
- TX ancorado no write real, guarda pós-RX de 1 s preservada. Ressincronização
  pode adiar um ciclo; fragmento incompleto bloqueia TX. Frame recuperado é
  consumido uma vez com `tx_sent=false`, nunca atribuído a um novo comando.
- CP936, parser estrito, Open=null, timestamp original e recebido, fila limitada,
  rejeição de regressão temporal e dedupe (timestamp + hash) preservados.
  Resposta simples sem prefixo TCP-32 não valida o perfil Celsius.
- Timeout isolado → conexão `degraded`, porta preservada, próximo ciclo seguro.
  Uma retentativa lógica limitada também atende probes; nunca transmite antes
  da janela segura. O leitor contínuo permanece vivo após falhas.
- Reconexão por erro serial/COM fechada ou watchdog: pelo menos três falhas
  consecutivas e lacuna maior que a janela dura (mínimo 30 s na cadência padrão;
  pode aumentar com latência observada). Backoff limitado a 30 s.
- Instância já validada por TCP-32 não repete IDN ao reconectar. Associação
  manual e autorização existentes permanecem obrigatórias, sem ampliar fallback.
- Leitura, teste completo e aquisição usam a mesma engine. Completo exige
  timestamp E hash distintos; em sessão ativa aguarda novas observações.
- Common-start independente permanece com preparação de 15 s, sem pareamento
  artificial de 1500 ms. GPM não foi alterado.
- Instrumentação e exportação física única preservadas. `trigger_*` identifica
  os novos contadores; `fetch_*` permanece como alias histórico de tentativas
  de medição, não evidência de transmissão do comando FETCH.

## Validação e entrega

Testes usam os três frames físicos reais e serial simulada. O soak acelera o
relógio monotônico e deriva timestamps sintéticos **apenas na fixture**, nunca
na produção: 720 amostras, 723 ciclos, 3619,6 s simulados, fragmentos com duração
1,4–2 s, dois timeouts isolados e uma perda real simulada de COM. Resultado:
zero frames mutilados, bytes parciais descartados, amostras duplicadas, respostas
desconhecidas por framing ou reconexões desnecessárias; uma reconexão necessária.

Gates e manifesto do código acompanham a candidata; o ZIP só é promovido após
testes e smoke do executável/exportações. O teste automatizado não opera hardware.
Artefato único: `ThermoPower-0.7.0-engineering-AT4532-celsius-trigger.zip`.
Próxima bancada: leitura, completo, AT sozinho, AT+GPM em sessão, recuperação e
exportação de **um diagnóstico físico completo**. Sem push, tag ou release.
