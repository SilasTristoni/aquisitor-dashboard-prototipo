# Estado e lacunas dos protocolos físicos — 0.5.4-physical-alpha

Os comandos deixaram de ser um bloqueio documental geral. A implementação usa exclusivamente
fontes oficiais listadas em `docs/protocols/` e mantém `physical_validation=pending`.

## AT4532

Confirmado oficialmente: SCPI ASCII, LF, 8-N-1, sem CTS/RTS, baud rates suportados,
`IDN?`/`*IDN?` e `FETCH?`. Para a bancada LAB, 19200 baud, COM5 e 32 canais também foram
observados fisicamente. O Datalogger v9.11 e `ATSCPIv5.dll` confirmam estaticamente os literais
`idn?` e `fetch?`.

Na evidência física mais recente, `*IDN?` em COM5 não respondeu. A 0.5.4 mantém isso como
`identity_status=unconfirmed`, mas permite que o operador execute a medição documentada quando a
porta coincide com a associação manual persistida e os parâmetros seriais conhecidos. A conexão
contínua só é liberada após `FETCH?` válido com 32 posições e ao menos um canal numérico.

Lacuna específica: o User's Guide AT45xx não define o valor wire de termopar aberto, canal
desligado ou overflow. A build não chama qualquer valor de `open_sensor`: tokens desconhecidos
ficam `unknown_unavailable` apenas no canal correspondente, o frame raw é conservado e os demais
canais continuam válidos. Valores numéricos fora da faixa publicada usam `invalid_out_of_range`.
O texto `Open` foi confirmado apenas no XLSX do Instrument V1.8.7, não no RX SCPI.

## GPM-8213

Confirmado oficialmente: USB CDC, 8-N-1, flow control off, CR+LF, `*IDN?`, configuração
`:NUMERIC:NORMAL:ITEM<x>`/`NUMBER` e leitura `:NUMERIC:NORMAL:VALUE?` em NR3 ASCII. O software
PowerMeterSeries e o driver LabVIEW confirmam os mesmos grupos funcionais. O serial USB
`GES913349` é a identidade estável e a COM é redescoberta.

Validado fisicamente: `*IDN?` em COM3 retornou
`GWInstek,GPM-8213,GES913349,V1.05\r\n`. A cadeia NUMERIC agora confirma `NUMBER?` e
`HEADER?` antes de `VALUE?` e classifica respostas stale por tipo.

Validado fisicamente até aquisição contínua no firmware V1.05, inclusive HEADER real
`Urms,Irms,P,S,fU,PF,Q,fI` e grandezas normalizadas coerentes. A tabela USB CDC não atribui baud;
o valor 9600 usado pela API pyserial é
somente placeholder host (é o default documentado de RS-232), não configuração homologada da
USB. A próxima sessão deve confirmar `NUMBER=8`, os oito cabeçalhos e os valores reais.

## Gate atual

- `AT4532 ready_for_physical_protocol_test = true`
- `GPM8213 physical_validation = passed`
- `AT4532 physical_validation = pending`
- beta/release de cliente: não autorizada
