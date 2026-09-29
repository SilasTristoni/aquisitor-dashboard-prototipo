# AT4532 — estado físico atual da 0.6.6

> Documento curto de continuidade. Use este arquivo como primeira referência em novas investigações do AT4532. Histórico detalhado da correção anterior: `docs/AT4532_FRAMING_066.md`.

## Estado da candidata

- Versão: `0.6.6-client-preview`.
- A candidata ainda **não está homologada fisicamente**.
- A correção anterior de framing deve ser preservada.
- O GPM-8213 não deve ser alterado sem nova evidência específica.

## Hardware e protocolo confirmados

- AT4532 associado manualmente à porta correta da bancada.
- 19200 baud, 8-N-1.
- `TCP-32` / CP936.
- 32 canais primários.
- `Open` = sensor aberto/indisponível (`null`), nunca zero.
- `*IDN?` pode não responder fisicamente; medição `TCP-32` válida permanece a evidência operacional dentro da política segura já implementada.

## Problema anterior já corrigido

A 0.6.5 podia encontrar apenas `TCP-32` no buffer antes de um novo TX, descartar esses 6 bytes e entregar os 688 bytes restantes ao parser. A primeira candidata 0.6.6 corrigiu essa mutilação.

Evidência atual esperada:

```text
discarded_partial_bytes = 0
full_frame_length = 694
prefix = TCP-32
terminator = CRLF
```

Não reverter a política de preservação/recomposição de boundary documentada em `AT4532_FRAMING_066.md`.

## Falha física atual

Nos diagnósticos físicos mais recentes da primeira candidata 0.6.6:

```text
FETCH #1
TX 12:26:18.334
RX 12:26:19.365
query duration ≈ 1031 ms
bytes = 694
TCP-32 válido
parser OK
```

O próximo `FETCH?` foi enviado aproximadamente:

```text
~462 ms após o fim do RX anterior
```

Esse segundo FETCH entrou em timeout. A sequência seguinte apresentou múltiplos timeouts e reconexão.

Resumo observado:

```text
fetch_attempts = 7
successful_fetches = 1
fetch_timeouts = 6
consecutive_fetch_timeouts = 6
reconnect_count = 1
maximum_gap ≈ 28.4 s
```

Portanto a aquisição contínua do AT ainda não está aprovada.

## Evidência adicional

Durante ressincronização, os diagnósticos também mostraram fragmentos iniciais de 6–7 bytes que foram completados em frames válidos:

```text
full_frame_length = 694
prefix = TCP-32
terminator_found = true
```

A política atual pode classificar esses frames completos como tardios e descartá-los antes de enviar outro `FETCH?`. Isso deve ser reavaliado: um frame completo, válido, fresco e ainda não consumido pode representar uma medição física real recuperável, desde que não seja associado cegamente ao comando mais recente nem duplicado.

## Hipótese prioritária a investigar

A lógica de cadência permite efetivamente algo equivalente a:

```text
max(previous_fetch_started + 1 s,
    previous_fetch_completed + 0.4 s)
```

Na bancada isso resultou em novo TX apenas ~462 ms após o RX anterior, seguido de timeout.

Hipótese prioritária: polling pós-RX agressivo, combinado com tratamento inadequado de frames completos recuperados durante `resync`.

Isso ainda deve ser comprovado pela implementação/testes; não transformar `1 s após RX` em verdade física sem validação.

## Direção da próxima correção

Prioridade:

1. estabilidade contínua;
2. nenhuma perda/mutilação;
3. nenhuma duplicação;
4. nenhuma reconexão desnecessária;
5. somente depois maximizar a frequência sustentável.

Investigar inicialmente apenas:

- `backend/app/adapters/specific.py`
- `backend/app/adapters/transports.py`
- `backend/app/services/protocol_probe.py`
- testes AT4532/transporte diretamente relacionados.

Pontos de projeto a avaliar:

- guarda pós-RX mais segura e instrumentada;
- consumo de frame `TCP-32` válido/fresco encontrado durante resync;
- pequena fila/buffer de frames completos do AT, se necessária;
- deduplicação por timestamp do equipamento + conteúdo/hash;
- timeout isolado sem assumir perda física da COM;
- reconnect apenas para erro físico/porta desaparecida ou falha persistente real;
- evitar novo `*IDN?` em toda recuperação transitória após validação por medição naquela conexão lógica;
- mesma política de framing/recuperação em `Testar leitura`, `Teste completo` e aquisição contínua.

## Testes focados exigidos antes da suíte completa

- resposta de ~1030 ms sem novo FETCH ~400 ms após RX;
- frame de 694 bytes fragmentado e completado durante resync;
- late/recovered frame válido consumido exatamente uma vez;
- deduplicação do mesmo frame;
- timeout isolado recuperado sem reconnect físico;
- perda real da COM causando reconnect;
- regressão do GPM preservada.

Depois dos testes focados: gate físico automatizado; depois backend completo; frontend completo somente se contrato/UI for afetado; build Windows apenas no final.

## Próximo aceite físico

A nova candidata só pode avançar após bancada real:

1. `Testar leitura`;
2. `Teste completo`;
3. AT sozinho por 5 min;
4. AT + GPM por 10 min;
5. sessão combinada;
6. soak físico de 30–60 min.

Critérios mínimos:

```text
discarded_partial_bytes = 0
unknown_response causado por framing = 0
duplicate_samples = 0
reconnects desnecessários = 0
```

A frequência exata não é prioridade sobre estabilidade. Uma cadência menor, porém contínua e auditável, é preferível a forçar 1 Hz causando timeouts.
