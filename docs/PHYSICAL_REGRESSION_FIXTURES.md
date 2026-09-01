# Gate de regressão física

Toda engineering build executa primeiro a seleção Pytest
`physical_regression_fixtures` e depois a suíte completa. O primeiro gate existe para impedir que
uma mudança em um aquisitor seja empacotada quando quebrar evidência física do outro.

## GPM-8213 V1.05

A fixture obrigatória reproduz, em uma única cadeia transacional, identidade
`GWInstek,GPM-8213,GES913349,V1.05`, configuração de oito itens, RX abreviado
`:NUM:NORM:NUMB 8`, ITEM1–ITEM8, cabeçalho `Urms,Irms,P,S,fU,PF,Q,fI` e valores
`127.58,0.24002,17.688,30.622,59.993,0.5776,24.997,NAN`. O resultado normalizado deve manter
Vrms, Irms, W, VA, Hz, PF e VAR nas grandezas corretas e converter apenas IHz `NAN` em `null`.

O parser também aceita `8` e o eco longo semanticamente equivalente. Prefixos arbitrários que
apenas terminem em um número são rejeitados. Descoberta pelo serial USB `GES913349` e polling de
aproximadamente um segundo permanecem protegidos.

## AT4532

A fixture obrigatória reproduz timeout de identidade na associação manual exata COM5,
19200/8-N-1, `SYST:UNIT CEL` e um `FETCH?` `TCP-32` codificado em CP936. O frame possui timestamp,
metadado ambiente, 32 tokens primários e campos auxiliares opacos. CH01–CH24 usam
`Open|K|℃`; CH25–CH32 usam as oito temperaturas físicas fornecidas. O gate verifica bytes/HEX,
encoding, estrutura, `null/open_sensor`, tipo K, unidade Celsius, mapeamento posicional e ausência
de off-by-one.

A série temporal de aquecimento altera somente CH29 entre 21,5 °C, 25,0 °C e 29,0 °C,
preservando o timestamp de cada frame. CH29 não recebe tratamento especial no código de produto.
O formato simples ASCII anterior continua coberto separadamente.

O briefing descreve a captura física como tendo aproximadamente 694 bytes e informa sua estrutura
e os tokens de canal, mas não fornece o dump integral dos bytes nem o conteúdo integral dos campos
auxiliares. Por isso as fixtures exercitam auxiliares opacos sem lhes atribuir significado. A build
registra o RX integral no ZIP de diagnóstico durante a próxima homologação; esse diagnóstico não
deve ser versionado.

## Fontes combinadas e falha parcial

O gate combinado usa a leitura elétrica de 17,688 W e os oito canais térmicos válidos. Ele exige
estatísticas térmicas calculadas somente sobre CH25–CH32, timestamps/polling independentes e sessão
com ambas as fontes. Cenários GPM OK/AT erro e AT OK/GPM erro exigem resultado `partial`; a fonte
saudável continua conectada, publicando e persistindo suas próprias amostras.

## Execução

```powershell
cd backend
..\.venv\Scripts\python -m pytest -m physical_regression_fixtures
..\.venv\Scripts\python -m pytest
```

O script `scripts/build-windows-engineering.ps1` executa ambos os comandos e interrompe o pacote
se qualquer um falhar.
