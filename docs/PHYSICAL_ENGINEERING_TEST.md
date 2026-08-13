# Teste da build física de engenharia

Use somente `0.5.2-physical-alpha`. Não é beta de cliente e não declara homologação.

## Preparação

1. Feche Instrument V1.8.7 e Power Meter Series. O ThermoPower nunca encerra esses processos.
2. Abra **Equipamentos e portas USB** e atualize a descoberta.
3. O painel read-only continua disponível e declara que nenhum comando é enviado.
4. No **Teste de Protocolo Documentado**, confira equipamento, porta, 8-N-1, terminador,
   fonte e comando mostrados; confirme o TX somente se estiverem corretos.
5. Acompanhe TX/RX ASCII/HEX, timestamps, latência, parser e resultado normalizado.

## AT4532

1. Confirme COM5 e 19200; não associe COM2 apenas pelo mesmo VID/PID CH340.
2. Clique **Testar identificação** e valide modelo/serial/revisão retornados.
3. Clique **Testar leitura** e compare canais com o display do instrumento.
4. Abra deliberadamente um termopar e exporte o diagnóstico para descobrir o sentinela oficial.
5. Execute o teste completo; duas leituras devem ocorrer com ~3 s entre elas.

## GPM-8213

1. Confirme que o serial `GES913349` foi localizado, mesmo se a COM não for COM3.
2. Teste identidade e confira firmware/serial.
3. Confirme `number_requested=8`, `number_reported=8`, `headers_requested` e
   `headers_reported`; a ordem solicitada é `U,I,P,S,FU,LAMBDA,Q,FI`, mas a reportada prevalece.
   No firmware V1.05 observado, o retorno válido é `Urms,Irms,P,S,fU,PF,Q,fI`.
4. Teste leitura e compare Vrms, Irms, P, VA, VAR, PF, VHz e IHz com o display.
5. Execute o teste completo; duas leituras devem ocorrer com ~1 s entre elas.

## Ambos

Conecte ambos, inicie uma sessão com dispositivo térmico + elétrico, confirme o gráfico e o
WebSocket, desconecte/reconecte cada cabo separadamente e verifique que o outro fluxo continua.
Se algo divergir, clique **Exportar diagnóstico completo** antes de fechar o aplicativo.
