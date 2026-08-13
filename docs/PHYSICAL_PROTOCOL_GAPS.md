# Estado e lacunas dos protocolos físicos — 0.5.2-physical-alpha

Os comandos deixaram de ser um bloqueio documental geral. A implementação usa exclusivamente
fontes oficiais listadas em `docs/protocols/` e mantém `physical_validation=pending`.

## AT4532

Confirmado oficialmente: SCPI ASCII, LF, 8-N-1, sem CTS/RTS, baud rates suportados,
`IDN?`/`*IDN?` e `FETCH?`. Para a bancada LAB, 19200 baud, COM5 e 32 canais também foram
observados fisicamente. O Datalogger v9.11 e `ATSCPIv5.dll` confirmam estaticamente os literais
`idn?` e `fetch?`.

Lacuna específica: o User's Guide AT45xx não define o valor wire de termopar aberto, canal
desligado ou overflow. A build não chama qualquer valor de `open_sensor`; conserva o raw e usa
`invalid_out_of_range` quando fora da faixa publicada. Precisamos capturar uma resposta oficial
com um canal propositalmente aberto ou obter essa tabela do fabricante.

## GPM-8213

Confirmado oficialmente: USB CDC, 8-N-1, flow control off, CR+LF, `*IDN?`, configuração
`:NUMERIC:NORMAL:ITEM<x>`/`NUMBER` e leitura `:NUMERIC:NORMAL:VALUE?` em NR3 ASCII. O software
PowerMeterSeries e o driver LabVIEW confirmam os mesmos grupos funcionais. O serial USB
`GES913349` é a identidade estável e a COM é redescoberta.

Validado fisicamente: `*IDN?` em COM3 retornou
`GWInstek,GPM-8213,GES913349,V1.05\r\n`. A cadeia NUMERIC agora confirma `NUMBER?` e
`HEADER?` antes de `VALUE?` e classifica respostas stale por tipo.

Lacuna específica: a tabela USB CDC não atribui baud. O valor 9600 usado pela API pyserial é
somente placeholder host (é o default documentado de RS-232), não configuração homologada da
USB. A próxima sessão deve confirmar `NUMBER=8`, os oito cabeçalhos e os valores reais.

## Gate atual

- `AT4532 ready_for_physical_protocol_test = true`
- `GPM8213 ready_for_physical_protocol_test = true`
- `physical_validation = pending` para ambos
- beta/release de cliente: não autorizada
