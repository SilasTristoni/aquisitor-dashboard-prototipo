# AT4532 — protocolo físico de engenharia

Status: `vendor_documented`, com `physical_validation = pending`. Consulta documental: 2026-08-11.

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
| Encoding | ASCII | seção 2.3.6 |
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

### Temperaturas multicanal

- Nome funcional: `temperatures`
- Comando exato: `FETCH?`
- Bytes TX: `46 45 54 43 48 3F 0A`
- Encoding/terminador: ASCII + LF
- Exemplo TX: `FETCH?\n`
- Exemplo RX oficial: `+1.00000e-05, +1.00000e-05, +1.00000e-05\n`
- Campos: de 1 a 32 números ASCII separados por vírgula; a quantidade acompanha os canais
- Unidade: unidade configurada no instrumento; a integração exige Celsius no ensaio
- Parser: número finito, frame único e LF obrigatório; normalizador completa até 32 posições
- Erros: timeout, parcial, múltiplos frames, campo vazio/não numérico, mais de 32 campos
- Fonte: User's Guide Rev.A6, seção 9.5.3.1, p.30

### Unidade Celsius

- Nome funcional: `configure_celsius`
- Comando exato: `SYST:UNIT CEL`
- Bytes TX: `53 59 53 54 3A 55 4E 49 54 20 43 45 4C 0A`
- Encoding/terminador: ASCII + LF; comando set, sem RX esperado
- Finalidade: impedir que Fahrenheit/Kelvin seja persistido como Celsius
- Fonte: User's Guide Rev.A6, seção 9.5.2.3, p.30

## Limitações explícitas

O guia AT45xx encontrado não define o sentinela retornado por `FETCH?` para termopar aberto,
canal desligado ou overflow. Por isso nenhum número é traduzido arbitrariamente para
`open_sensor`. Valores fora da faixa publicada de -200 °C a 1800 °C são preservados no raw e
marcados `invalid_out_of_range`; a distinção `open_sensor` depende da resposta física ou de
documentação oficial adicional. MODBUS, checksum e registradores não foram implementados.
