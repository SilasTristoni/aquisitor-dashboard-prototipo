# GPM-8213 — protocolo físico de engenharia

Status: `vendor_documented`. Identidade validada fisicamente em 2026-08-11; medição
NUMERIC permanece com `physical_validation = pending`.

## Evidência física recebida

- Porta observada: COM3; identidade estável: serial USB `GES913349`.
- TX: `*IDN?\r\n`.
- RX real, 35 bytes: `GWInstek,GPM-8213,GES913349,V1.05\r\n`.
- Firmware validado: `V1.05`.
- O PowerMeterSeries físico registrou a ordem Vrms, Irms, P, VA, VHz, PF, VAR e IHz. A ordem
  solicitada passou a ser `U,I,P,S,FU,LAMBDA,Q,FI`; `HEADER?` continua soberano.
- O firmware V1.05 respondeu fisicamente `Urms,Irms,P,S,fU,PF,Q,fI`. O raw é preservado;
  internamente esses aliases são canonicalizados, sem exigir igualdade textual com o solicitado.
- Uma resposta de identidade antiga chegou durante `VALUE?`; ela agora é classificada como
  `unexpected_response_type`/`possible_stale_response` antes do parser numérico.

## Fontes primárias

- Produto/downloads: https://www.gwinstek.com/en-US/products/detail/GPM-8213
- **GPM-8213 User Manual**, versão G_20230828, 2024-05-15:
  https://www.gwinstek.com/en-US/download/downloadFile/11551
- **Power Meter Remote Viewer Guide**, V1.0, páginas 5–10:
  https://www.gwinstek.com/en-US/products/downloadSeriesDownNew/20891/1553
- Driver LabVIEW oficial 2014:
  https://www.gwinstek.com/en-US/products/downloadSeriesDownNew/13734/1553
- Driver USB CDC oficial:
  https://www.gwinstek.com/en-US/products/downloadSeriesDownNew/16678/1553

O PowerMeterSeries oficial contém literalmente `*IDN?`, `:NUMERIC:VALUE?`,
`:NUMERIC:HEADER?`, `:NUMERIC:NUMBER` e `:NUMERIC:ITEM`. O driver LabVIEW contém VIs
`Initialize`, `Configure Item Number`, `Configure Item` e `Read Measurement`, coerentes com o
manual. Isso é evidência auxiliar; a sintaxe implementada vem do User Manual.

## Transporte confirmado

| Campo | Valor | Evidência |
|---|---:|---|
| Interface física | USB Device Type B, classe CDC, COM virtual | Remote Control, p.65 |
| RS-232 baud | 1200–115200; default 9600 no guia do software | manual p.65; guia p.6 |
| Baud na USB CDC | não especificado na tabela USB | 9600 é somente placeholder da API host |
| Data bits | 8 | manual p.65 |
| Parity | none (`N`) | manual p.65 |
| Stop bits | 1 | manual p.65 |
| Flow control | off | manual p.65 |
| Terminador | CR+LF | Command Syntax p.72; default no guia do software p.6 |
| Encoding/framing | SCPI ASCII | Command Overview p.69–74 |
| Timeout recomendado | não informado | timeout de 2 s é política do app |

## Comandos implementados

Todos usam ASCII e TX terminado em `0D 0A`.

| Função | Comando exato | Resposta/parser | Unidade | Fonte |
|---|---|---|---|---|
| Identidade | `*IDN?` | `GWINSTEK,GPM-8213,<serial>,<firmware>`; 4 campos/modelo estrito | — | p.75 |
| Quantidade | `:NUMERIC:NORMAL:NUMBER 8` | comando set, sem RX esperado | — | p.97 |
| Verificar quantidade | `:NUMERIC:NORMAL:NUMBER?` | 1–34; aceita valor ou eco SCPI e exige resultado 8 | — | p.97 |
| Vrms | `:NUMERIC:NORMAL:ITEM1 U` | item 1 da resposta NR3 | V | p.97–99 |
| Irms | `:NUMERIC:NORMAL:ITEM2 I` | item 2 | A | p.97–99 |
| P | `:NUMERIC:NORMAL:ITEM3 P` | item 3 | W | p.97–99 |
| VA | `:NUMERIC:NORMAL:ITEM4 S` | item 4 | VA | p.97–99 |
| VHz | `:NUMERIC:NORMAL:ITEM5 FU` | item 5 | Hz | p.97–99 |
| PF | `:NUMERIC:NORMAL:ITEM6 LAMBDA` | item 6 | adimensional | p.97–99 |
| VAR | `:NUMERIC:NORMAL:ITEM7 Q` | item 7 | VAR | p.97–99 |
| IHz | `:NUMERIC:NORMAL:ITEM8 FI` | item 8 | Hz | p.97–99 |
| Cabeçalhos | `:NUMERIC:NORMAL:HEADER?` | nomes dos itens 1..NUMBER na ordem configurada | — | p.102 |
| Leitura | `:NUMERIC:NORMAL:VALUE?` | NR3/`NAN`, associado pelo cabeçalho validado | conforme itens | p.96 |

TX de identidade: `2A 49 44 4E 3F 0D 0A`. TX de leitura:
`3A 4E 55 4D 45 52 49 43 3A 4E 4F 52 4D 41 4C 3A 56 41 4C 55 45 3F 0D 0A`.

Sequência transacional obrigatória: `NUMBER 8`, `NUMBER?`, `ITEM1..ITEM8`, `HEADER?` e somente
então `VALUE?`. O parser associa `HEADER[i]` a `VALUE[i]`; não depende de posições cegas.
`NAN` produz `None`/qualidade `missing` somente para a grandeza afetada. Respostas parciais,
não-ASCII, modelo diferente, valor infinito ou tipo incompatível são rejeitadas antes da
normalização.

Fixture física de referência do PowerMeterSeries: `U,I,P,S,FU,LAMBDA,Q,FI` com
`126.86,2.0199,256.07,256.25,59.989,0.9993,-9.5985,59.988`. Ela protege especialmente
contra inversão de frequência, fator de potência e potência reativa, preservando o sinal de VAR.

Aliases confirmados no RX V1.05: `Urms→voltage`, `Irms→current`, `P→power`,
`S→apparent_power`, `fU→voltage_frequency`, `PF→power_factor`,
`Q→reactive_power` e `fI→current_frequency`. A comparação é case-insensitive.

Na abertura, buffers RX/TX são limpos e os bytes RX pendentes são registrados. Cada query drena
e preserva bytes comprovadamente anteriores ao TX, faz flush do TX, aguarda um frame CRLF e
classifica `identity_response`, `item_count`, `header_list` ou `numeric_measurement`. Não há
delay declarado como propriedade do instrumento; a serialização é política do host.

## Identidade USB e polling

O INF oficial associa `VID_2184&PID_0052` ao driver `usbser`. A aplicação localiza primeiro o
serial `GES913349`, atualiza a COM atual e só então abre a porta. A consulta ocorre a cada ~1 s.
Não há dependência permanente de COM3. Identidade/SCPI básico foram confirmados no firmware
V1.05; quantidade, cabeçalhos e valores reais continuam pendentes do próximo ensaio.
