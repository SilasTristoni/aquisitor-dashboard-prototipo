# Integração com dispositivos

## Contrato

Toda fonte implementa `DeviceAdapter`:

```python
async def connect() -> None
async def disconnect() -> None
async def start_reading() -> AsyncIterator[DeviceReading]
async def stop_reading() -> None
def parse_message(raw: bytes | str) -> DeviceReading
async def get_status() -> DeviceStatus
async def get_device_information() -> DeviceInformation
```

O contrato legado `DeviceReading` continua disponível para simulador e clientes existentes, agora com até 32 canais. Novas integrações usam contratos independentes em `app/domain/readings.py`:

- `TemperatureReading`: timestamp do equipamento, timestamp de recepção, ambiente e até 32 `TemperatureChannelReading`;
- `ElectricalReading`: tensão, corrente, potências ativa/aparente/reativa, fator de potência e frequências de tensão/corrente;
- ambos preservam payload, valor/unidade original, valor normalizado e qualidade.

## Adaptadores iniciais

- `SimulatorAdapter`: operacional, determinístico quando recebe seed, configurável e capaz de injetar falhas.
- `SerialJsonAdapter`: parser operacional; abertura da porta depende da biblioteca/porta e de homologação com hardware.
- `SerialCsvAdapter`: estrutura e parser preparados, desabilitados por padrão até o fabricante definir ordem, delimitador e framing.
- `MockFailureAdapter`: falha em estágios selecionáveis para testes de recuperação.
- `At4532SerialAdapter` e `Gpm8213UsbSerialAdapter`: transport/protocol/parser/normalizer
  separados. O GPM-8213 V1.05 foi validado fisicamente. No AT4532, o `FETCH?` físico confirmou
  o frame `TCP-32`/CP936 e o sentinel `Open`; `*IDN?` continua sem resposta e os campos
  auxiliares permanecem semanticamente desconhecidos.
- `RealSerialDiagnosticService`: abre/lê/fecha bytes raw em modo estritamente read-only e nunca produz medições.
  Se a abertura ou o fechamento falhar depois de criar a conexão, a referência é mantida para nova
  tentativa; a porta não é declarada liberada antecipadamente. A descoberta USB segue a mesma
  regra e não abre outra conexão enquanto houver um fechamento pendente para a porta.
- `At4532XlsxImporter` e `Gpm8213TxtImporter`: operacionais com detecção de cabeçalho e unidades.

## JSON provisório

O adaptador aceita provisoriamente uma mensagem UTF-8 por linha:

```json
{"power":850,"powerUnit":"W","temperatures":[31.2,31.8,32.1]}
```

Também aceita `mW` e `kW`. Esse é um contrato de desenvolvimento, não o protocolo definitivo do aquisitor.

## Informações necessárias para homologação

- fabricante, modelo, firmware e identificadores USB;
- classe do dispositivo (COM/CDC, HID, Modbus ou proprietário);
- driver e sistemas operacionais suportados;
- baud rate, bits, paridade, stop bits e controle de fluxo;
- framing, encoding, checksum/CRC, endianess e timeout;
- escala, unidade e faixa de cada grandeza;
- representação de sensor aberto, saturação e erro;
- frequência nominal, clock do equipamento e ordenação dos canais;
- comandos de iniciar/parar/configurar e respostas esperadas;
- capturas de tráfego e arquivos reais de exemplo.

## Plano de validação física

1. Registrar porta e informações do equipamento sem iniciar coleta.
2. Capturar bytes brutos de uma bancada conhecida.
3. Comparar valores com instrumento de referência.
4. Validar framing parcial, mensagens concatenadas, CRC e reconexão.
5. Executar soak test de pelo menos uma sessão representativa.
6. Medir perda de amostras, jitter, clock drift e comportamento após suspensão do computador.
7. Documentar matriz firmware/driver/SO e assinar protocolo homologado.

Até concluir a validação de bancada e o soak test, a integração serial deve ser apresentada como
**build física de engenharia, não homologada para cliente**. As fixtures de regressão incorporam
as respostas físicas disponíveis além dos exemplos dos manuais oficiais; o dump integral real dos
34 campos auxiliares do AT4532 ainda precisa ser capturado. Arquivos do fabricante baixados para
inspeção ficam fora do pacote distribuído.

## Descoberta USB / COM

`UsbDeviceDiscoveryService` enumera os campos reportados pelo sistema operacional e pode abrir
e fechar a porta imediatamente, sem transmitir bytes, para distinguir disponibilidade de uso
por outro processo. Aquisições ativas do próprio ThermoPower são marcadas ocupadas sem nova
abertura. A associação usa, nesta ordem, número de série USB, par VID/PID salvo e nome da porta.

Descrições contendo literalmente AT4532 ou GPM-8213 geram apenas `possible_*`. O CH340
`1A86/7523` continua sendo só candidato sem confirmação manual; o GPM usa a combinação oficial
`2184/0052` e, principalmente, o serial único `GES913349`. Porta aberta ou driver instalado não
equivalem a uma resposta SCPI válida.

No AT4532, os metadados de associação USB, validação física e autorização por medição pertencem
ao backend. `POST/PUT /devices` não pode forjá-los; a associação vem do endpoint de descoberta e a
autorização persistente só nasce de um probe TCP-32 válido cuja porta também foi fechada com
sucesso. Se esse fechamento falhar, o adapter permanece retido para nova tentativa antes do próximo
probe e no encerramento do backend; enquanto a porta não for liberada, a autorização não é gravada.
Alterar porta, fingerprint USB ou parâmetros 8-N-1 invalida essa autorização.
