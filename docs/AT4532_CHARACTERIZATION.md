# AT4532 — observação de engenharia

Pacote interno para investigação. Não é release, candidata final ou homologação.
A aquisição contínua do AT permanece sob investigação; sua máquina de recuperação
não foi alterada nesta etapa. A preparação combinada agora usa prontidão por fonte.

## Captura física

1. Feche o ThermoPower e qualquer programa que esteja usando COM5. Confirme no
   instrumento a porta correta e 19200/8-N-1. Não execute duas capturas ao mesmo tempo.
2. Na pasta extraída, execute no PowerShell:
   `powershell -ExecutionPolicy Bypass -File .\characterize-at4532.ps1`
3. Aguarde aproximadamente 40 s (até 70 s se for preciso esperar fronteiras seguras).
4. Envie o ZIP `AT4532-observation-*.zip` criado ao lado do executável, informando
   o estado/tela do instrumento e se havia software conectado anteriormente.

Janelas: abertura e escuta passiva por 10 s; somente `SYST:UNIT CEL` e 10 s de escuta;
um `FETCH?` e 10 s de escuta; segundo `FETCH?` e 10 s de escuta somente se um frame
válido com temperatura foi observado após o primeiro. Não há IDN, reset de buffers,
repetição automática ou reconnect. Uma fronteira parcial ou RX contínuo pode bloquear
o próximo TX: o motivo e todos os bytes observados ficam registrados.
No Windows, a ferramenta também omite o PurgeComm implícito da abertura pyserial.
Essa exceção é exclusiva desta ferramenta; não altera a abertura da aquisição normal.

`events.jsonl` contém início/fim de abertura e writes, flush de saída (não reset),
leituras byte a byte com UTC/monotônico, `in_waiting`, intervalos entre RX, janelas,
fragmentos pendentes e frames completos. `frames.json` contém bytes/HEX, SHA-256,
prefixo, terminador, tamanho, resultado do parser e horário interno do equipamento.
Os arquivos têm manifesto SHA-256. Horários são observações no driver pelo PC;
não são timestamps elétricos do fio. Fragmentos USB são inferíveis pelas transições
de `in_waiting` e intervalos de leitura; o sistema operacional pode agregá-los.
O programa não altera o relógio do equipamento nem atribui causalidade a um frame
só por ter sido observado depois de um comando. A abertura pode afetar DTR/RTS;
seus estados são registrados, sem manipulá-los durante a captura.

No ambiente de desenvolvimento, com PYTHONPATH=backend:
`python -m app.engineering.at4532_characterization --port COM5 --output nova-pasta`

## Validar início combinado

Após encerrar a ferramenta, abra `ThermoPowerMonitor.exe`, conecte as fontes e inicie
um ensaio combinado. T0 é definido no início da preparação; cada fonte precisa de
uma leitura nova e saudável, sem pareamento por proximidade. Todas as amostras
preparatórias elegíveis seguem para a sessão com seus horários reais. Se uma fonte
permanecer silenciosa, o início expira e a outra aquisição continua.

Exporte os diagnósticos normais do aplicativo e anexe o ZIP da captura controlada.
A interface estática foi reutilizada: textos antigos de “sincronização” não significam
que exista requisito de chegada simultânea no backend desta build.
Dados locais seguem o diretório habitual do ThermoPower; preserve os dados da bancada.

## Aceite pendente

Testes automatizados não comprovam o comportamento do AT real. São necessários
10/10 testes completos consecutivos, 5 min AT contínuo, 10 inícios combinados,
10 min com ambos os contadores aumentando e depois 30–60 min combinado.
Qualquer falha mantém a candidata reprovada; este pacote serve somente à investigação.
