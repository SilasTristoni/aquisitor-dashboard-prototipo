# AT4532 — protocolo físico de engenharia

Status: comandos `vendor_documented`; `FETCH?` observado fisicamente em 2026-08-25 como frame
`TCP-32`; identidade ainda `unconfirmed` porque `*IDN?` retornou zero bytes.

## Decisão

O protocolo principal é SCPI ASCII sobre RS-232/USB-serial. A página oficial associa o guia
AT45xx ao AT4532 e declara RS-232 bidirecional, USB-232, SCPI e MODBUS. SCPI foi escolhido
porque o mesmo guia documenta diretamente identidade e `FETCH?` multicanal; MODBUS não é
necessário para o primeiro ciclo e não foi implementado sem mapa de registradores específico.

Fonte primária: **AT45xx Multi-channel Temperature Meter User's Guide**, English Rev.A6,
seções 8.1–8.4 e 9.1–9.5, páginas impressas 24–30.

- Produto: https://www.anbai.cn/products/xmd/AT4532?AspxAutoDetectCookieSupport=1
- Guia: https://www.anbai.cn/app_file/products/AT4532/ug_en_AT4532.pdf

## Transporte confirmado

| Campo | Valor | Evidência |
|---|---:|---|
| Baud suportado | 9600, 19200, 38400, 57600, 115200 | seção 8.3 |
| Baud usado no LAB | 19200 | observado no instrumento/software e suportado pela seção 8.3 |
| Data bits | 8 | seção 8.3 |
| Parity | none (`N`) | seção 8.3 |
| Stop bits | 1 | seção 8.3 |
| Flow control | nenhum; CTS/RTS não usados | seção 8.1 |
| Encoding TX | ASCII | seção 2.3.6 |
| Encoding RX | ASCII no formato simples; CP936/GBK estrito no `TCP-32` observado | byte `A1 E6` representa `℃` |
| Terminador | LF, byte `0A` | seção 9.1 |
| Endereço | não aplicável a SCPI serial | — |
| Timeout recomendado | não informado | timeout de 2 s é política do app, não parâmetro homologado |

## Comandos implementados

### Identidade

- Nome funcional: `identity`
- Comando exato: `*IDN?`
- Bytes TX: `2A 49 44 4E 3F 0A`
- Encoding/terminador: ASCII + LF
- Exemplo TX: `*IDN?\n`
- RX documentado: `<MODEL>,<Revision>,<SN>,<Manufacturer><NL>`
- Parser: exatamente quatro campos; o primeiro deve ser `AT4532`
- Unidade: não aplicável
- Erros: timeout, frame parcial, não-ASCII, contagem errada, modelo inesperado
- Fonte: User's Guide Rev.A6, seção 9.5.5, p.30

Evidência física de 2026-08-25: na associação manual COM5, `*IDN?` terminou em timeout com
zero bytes. Isso não é identidade confirmada. Nos modos de leitura/completo, a build de engenharia
pode continuar exclusivamente quando a porta atual coincide com a associação manual persistida e
19200/8-N-1 coincide com os parâmetros documentados. Nesse caso, `SYST:UNIT CEL` e `FETCH?`
continuam; a conexão somente é aceita como `verified_by_measurement` se `FETCH?` produzir 32
posições interpretáveis e ao menos uma temperatura numérica. Portas candidatas por VID/PID não
recebem esse fallback.

### Temperaturas multicanal

- Nome funcional: `temperatures`
- Comando exato: `FETCH?`
- Bytes TX: `46 45 54 43 48 3F 0A`
- Encoding/terminador: ASCII + LF no formato simples; CP936/GBK + LF no `TCP-32` físico
- Exemplo TX: `FETCH?\n`
- Exemplo RX oficial: `+1.00000e-05, +1.00000e-05, +1.00000e-05\n`
- Campos: de 1 a 32 números ASCII separados por vírgula; a quantidade acompanha os canais
- Unidade: unidade configurada no instrumento; a integração exige Celsius no ensaio
- Parser simples: frame único, LF obrigatório, CR anterior ao LF tolerado e de 1 a 32
  posições; compatibilidade mantida
- Campos numéricos: positivos, negativos, zero, decimais e notação científica finita
- Campo ainda desconhecido: preservado integralmente como `unknown_unavailable` somente no canal;
  não invalida valores numéricos dos outros canais
- Erros de frame: timeout, parcial, múltiplos frames, controle não ASCII ou mais de 32 campos
- Fonte: User's Guide Rev.A6, seção 9.5.3.1, p.30

#### Frame físico `TCP-32`

A captura física tem a forma `TCP-32,T:<timestamp>,<ambiente>,...`, cerca de 694 bytes e 69
campos na observação fornecida. O reconhecimento não usa apenas o tamanho ou um CSV longo:
exige prefixo exato, timestamp `T:` parseável, terceiro campo ambiente numérico, bloco primário
de exatamente 32 tokens estruturados e pelo menos uma temperatura válida. Os campos posteriores
ao bloco primário são preservados como `auxiliary_fields_raw`; nenhuma semântica foi atribuída.

Cada token primário tem a forma `<leitura>|<tipo de termopar>|℃`. `K` é o tipo do termopar,
não Kelvin. A posição 1 é CH01 e a posição 32 é CH32. A temperatura ambiente do terceiro
campo é metadado do frame e não participa do mapa nem das estatísticas dos termopares.

Na captura conhecida, CH01–CH24 retornaram `Open|K|℃` e CH25–CH32 retornaram valores
numéricos. `Open` é agora sentinela físico desse formato: resulta em `temperature_c=null` e
`quality=open_sensor`, preservando o token original. Zero continua sendo uma temperatura real.
O timestamp do equipamento é preservado como timestamp da leitura, junto com seu texto raw.

O RX sempre conserva HEX e uma representação reversível dos bytes. A decodificação tenta
ASCII estrito e, para `TCP-32`, CP936 estrito; `errors=ignore` não é usado. O diagnóstico registra
`wire_encoding`, tipo e total de campos, metadados, 32 tokens/canais, campos auxiliares, canais
abertos/válidos, timestamps e erros do parser.

### Unidade Celsius

- Nome funcional: `configure_celsius`
- Comando exato: `SYST:UNIT CEL`
- Bytes TX: `53 59 53 54 3A 55 4E 49 54 20 43 45 4C 0A`
- Encoding/terminador: ASCII + LF; comando set, sem RX esperado
- Finalidade: impedir que Fahrenheit/Kelvin seja persistido como Celsius
- Fonte: User's Guide Rev.A6, seção 9.5.2.3, p.30

## Limitações explícitas

O guia AT45xx não documenta o frame enriquecido nem os campos auxiliares, mas `Open|K|℃` foi
confirmado no RX físico fornecido. O significado dos campos posteriores aos 32 canais, sentinelas
além de `Open`, canal desligado e overflow continua desconhecido e não é inferido. Valores
numéricos fora da faixa publicada de -200 °C a 1800 °C são preservados no raw e marcados
`invalid_out_of_range`. MODBUS, checksum e registradores não foram implementados.

O diagnóstico registra TX/RX textual e HEX, encoding, timestamps, latência, classificação, raw `FETCH?`,
quantidade recebida, terminador, quantidade de frames, tokens, valor/qualidade individual de CH01
a CH32 e erro/timeout. Canais válidos são destacados dinamicamente, sem fixar quais ponteiras
devem estar conectadas.
