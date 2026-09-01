# Estado e lacunas dos protocolos físicos — 0.5.5-physical-alpha

Os comandos deixaram de ser um bloqueio documental geral. A implementação usa exclusivamente
fontes oficiais listadas em `docs/protocols/` e fixtures derivadas das respostas físicas recebidas.

## AT4532

Confirmado oficialmente: SCPI ASCII, LF, 8-N-1, sem CTS/RTS, baud rates suportados,
`IDN?`/`*IDN?` e `FETCH?`. Para a bancada LAB, 19200 baud, COM5 e 32 canais também foram
observados fisicamente. O Datalogger v9.11 e `ATSCPIv5.dll` confirmam estaticamente os literais
`idn?` e `fetch?`.

Na evidência física mais recente, `*IDN?` em COM5 não respondeu. A 0.5.5 mantém isso como
`identity_status=unconfirmed`, mas permite que o operador execute a medição documentada quando a
porta coincide com a associação manual persistida e os parâmetros seriais conhecidos. A conexão
contínua só é liberada após `FETCH?` válido com 32 posições e ao menos um canal numérico.

O `FETCH?` respondeu fisicamente com um frame enriquecido `TCP-32`: prefixo, timestamp, metadado
ambiente, bloco primário de 32 canais e campos auxiliares. O byte `A1 E6` é `℃` em CP936/GBK;
CH01–CH24 retornaram `Open|K|℃` e CH25–CH32 retornaram temperaturas. O parser preserva bytes,
HEX, encoding, tokens e auxiliares, sem misturar ambiente ou auxiliares com canais. `Open` resulta
em `null/open_sensor`, nunca zero. Formato ASCII simples continua suportado.

Lacunas restantes: o User's Guide não descreve o significado dos campos auxiliares do `TCP-32`,
nem sentinelas diferentes de `Open`, canal desligado ou overflow. Esses valores permanecem raw;
valores numéricos fora da faixa publicada usam `invalid_out_of_range`. O dump integral original
de aproximadamente 694 bytes não foi anexado ao repositório e deve ser coletado pelo diagnóstico
na homologação, sem incluir dados da cliente no Git.

## GPM-8213

Confirmado oficialmente: USB CDC, 8-N-1, flow control off, CR+LF, `*IDN?`, configuração
`:NUMERIC:NORMAL:ITEM<x>`/`NUMBER` e leitura `:NUMERIC:NORMAL:VALUE?` em NR3 ASCII. O software
PowerMeterSeries e o driver LabVIEW confirmam os mesmos grupos funcionais. O serial USB
`GES913349` é a identidade estável e a COM é redescoberta.

Validado fisicamente: `*IDN?` em COM3 retornou
`GWInstek,GPM-8213,GES913349,V1.05\r\n`. A cadeia NUMERIC agora confirma `NUMBER?` e
`HEADER?` antes de `VALUE?` e classifica respostas stale por tipo.

O RX V1.05 de `NUMBER?` é `:NUM:NORM:NUMB 8\r\n`. A causa da falha na 0.5.4 foi uma lacuna
herdada: o parser e os testes cobriam apenas `8` ou o eco SCPI longo, embora o resultado da build
declarasse o gate aprovado. A fixture curta real agora é obrigatória e prefixos não equivalentes
continuam rejeitados.

Validado fisicamente até aquisição contínua no firmware V1.05, inclusive HEADER real
`Urms,Irms,P,S,fU,PF,Q,fI` e grandezas normalizadas coerentes. A tabela USB CDC não atribui baud;
o valor 9600 usado pela API pyserial é
somente placeholder host (é o default documentado de RS-232), não configuração homologada da
USB. A próxima sessão deve confirmar `NUMBER=8`, os oito cabeçalhos e os valores reais.

## Gate atual

- `physical_regression_fixtures = required`
- `GPM8213 physical_validation = passed`
- `AT4532 FETCH physical_observation = TCP-32/CP936`
- `AT4532 identity_status = unconfirmed`
- `AT4532 protocol_status = verified_by_measurement` somente após frame válido
- beta/release de cliente: não autorizada
