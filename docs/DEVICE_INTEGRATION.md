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

`DeviceReading` é o contrato canônico: timestamp de recepção, potência original, unidade original, potência normalizada em watts, até 16 temperaturas em °C e indicador de qualidade. O parser rejeita valores não finitos, unidades desconhecidas, potência negativa e canais fora de limites defensivos configuráveis.

## Adaptadores iniciais

- `SimulatorAdapter`: operacional, determinístico quando recebe seed, configurável e capaz de injetar falhas.
- `SerialJsonAdapter`: parser operacional; abertura da porta depende da biblioteca/porta e de homologação com hardware.
- `SerialCsvAdapter`: estrutura e parser preparados, desabilitados por padrão até o fabricante definir ordem, delimitador e framing.
- `MockFailureAdapter`: falha em estágios selecionáveis para testes de recuperação.

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

Até essa validação, a integração serial deve ser apresentada como **preparada, não homologada**.
