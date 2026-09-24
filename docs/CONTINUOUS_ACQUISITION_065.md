# Aquisição contínua — 0.6.5-client-preview

## Causa e evidências

O encerramento estava no software: `UnexpectedResponseTypeError` deriva de
`ProtocolResponseError`, mas o leitor contínuo tratava somente `SerialTransportError`.
A exceção de classificação escapava para `AcquisitionService._read_loop`, que encerrava
o leitor e fechava a serial. Além disso, três timeouts causavam reabertura sem considerar
o tempo desde o último RX válido. Uma falha no handshake de recuperação também podia
escapar ou alterar a flag do leitor.

A origem física de cada `unknown_response` ainda não está comprovada. Pode ser investigada
com os bytes, HEX, terminador e horários agora registrados; os testes sintéticos não provam
ruído, fragmentação ou atraso no instrumento real. Os parsers e evidências dos commits
`da409182c31e815eaaca871eec8ba768f6488dba` e
`7edca141a9341d401c89201d03f2d8440e880de3` foram preservados.

## Arquitetura

- Um runtime, adaptador, transporte e leitor por fonte. Uma reserva global normaliza o nome
  da porta e impede outro transporte, diagnóstico, adaptador JSON ou descoberta USB de abri-la.
  A reserva permanece durante o backoff e só é liberada na desconexão definitiva solicitada.
  O Windows continua garantindo a exclusividade entre processos; a aplicação deve executar
  com um único worker de aquisição, como no launcher existente.
- O lock da consulta protege a espera de cadência e o FETCH inteiro. O lock do transporte
  protege abertura, TX/RX e fechamento. Cancelamento aguarda a operação de I/O terminar antes
  de permitir fechar a porta, evitando um worker antigo lendo uma conexão nova.
- Respostas inválidas e timeouts isolados são contados e descartados. Nenhuma amostra
  artificial é publicada ou gravada. O runtime mantém a última leitura e a sessão; o GPM
  conserva seu próprio leitor. A próxima leitura válida inclui `communication_gap` para auditoria.
- `disconnected`, `connecting`, `connected`, `degraded` e `recovering` são os estados internos.
  `degraded` aparece como **Conectado**. `recovering` aparece como **Reconectando automaticamente...**.
  Três tentativas reais malsucedidas de reconexão sinalizam falha persistente, mas as tentativas
  continuam. O operador não precisa clicar em Conectar novamente quando o instrumento retorna.
- O watchdog usa relógio monotônico desde o último frame válido. O ciclo considerado é o maior
  entre polling configurado, tempo de fio + guarda e duração média observada + guarda.
  Recuperação interna: `max(5 s, 2 × ciclo)`; reabertura: `max(15 s, 6 × ciclo)`.
  A 19200 baud, 694 bytes × 10 bits consomem aproximadamente 361,46 ms; a guarda existente
  continua em 400 ms. A cadência permanece
  `max(início anterior + intervalo, fim do RX anterior + guarda)`.
- Porta fechada ou erro físico inicia recuperação sem esperar o watchdog. O backoff é
  1, 2, 4, 8, 16 e 30 segundos, limitado a 30 segundos. Reabrir e responder IDN não basta:
  a recuperação só termina após um FETCH válido. O fallback mantém a associação manual
  autorizada e a validação estrutural dos 32 canais.
- `Open` é estado de sensor. Após comprovação por leitura, até um frame com todos os canais
  `Open` permanece conectado; ele informa indisponibilidade dos sensores sem inventar temperaturas.
  A conexão inicial por fallback ainda exige pelo menos um canal numérico válido.
- O leitor monta bytes até LF/CRLF, com prazo total e limite de tamanho. Fragmentos USB não
  são tratados como frames completos. Frame sem terminador é entregue ao parser para rejeição;
  bytes tardios anteriores ao próximo TX ficam registrados como descarte de buffer. Não foi
  inventado delimitador por silêncio nem tamanho fixo de TCP-32 sem evidência física.
- Testar identificação/leitura/teste completo e diagnóstico serial usam snapshots da sessão
  ativa. Não enviam IDN/FETCH extra e não consomem o buffer do leitor. Os horários apresentados
  permitem distinguir a última evidência de uma leitura nova.

## Diagnóstico e métricas

O contador de FETCH, válidos, descartados, timeouts, respostas desconhecidas, reaberturas,
falhas de reconexão, maior lacuna e duração média é acumulado durante toda a conexão lógica.
A maior lacuna continua crescendo durante a indisponibilidade, sem depender de um novo RX.
Os últimos 256 comandos ficam em memória, limitando o consumo em ensaios longos.
Cada transação inclui RX raw/HEX, bytes recebidos, primeiro/último byte, duração, sequência,
terminador e descarte anterior ao TX. Falhas também são registradas nos logs existentes.

`GET /api/v1/devices/{id}/acquisition-diagnostics?after_sequence=0&page_size=100`
é somente leitura e paginado por sequência de FETCH. Retorna `history_truncated` se o coletor
ficou atrasado além do histórico disponível. Não conecta equipamentos. O ZIP diagnóstico de
uma fonte ativa usa o snapshot atual, sem exigir interromper a aquisição para executar probe.

## Validação automatizada

`backend/tests/test_continuous_serial_soak.py` testa os adaptadores reais com transportes
controlados e relógio acelerado. Não é homologação física.

| Cenário | Resultado exigido |
| --- | --- |
| A: 1.000 FETCH válidos | 1.000 amostras únicas; zero reconexões |
| B: 100 válidos, um inválido, 100 válidos | 200 válidos; um descarte; zero reconexões |
| C: 100 válidos, um timeout, 100 válidos | 200 válidos; um timeout; zero reconexões |
| D: perda real da porta no transporte | recuperação automática; mesma sessão |
| E: frame parcial seguido de completo | parcial descartado; stream continua |
| F: AT + GPM, quatro tipos de falha térmica | 200 amostras de cada fonte gravadas na mesma sessão |

Também são verificados backoff após cinco aberturas malsucedidas, três timeouts abaixo do
watchdog sem reabertura, todos os sensores Open, lease durante recuperação, descoberta USB,
cancelamento do worker, fragmentação e descarte de bytes atrasados. Testes de interface
verificam estados de recuperação, leituras preservadas e ausência de reconexão manual.

### Resultados registrados em 24/09/2026

Suíte completa do backend: **196 testes aprovados**, incluindo os cenários abaixo.
Gate de regressão de protocolos: **79 aprovados**. Frontend: **41 testes aprovados**,
lint, TypeScript e build aprovados. Os avisos de depreciação são de Matplotlib/Pyparsing.
O XML `TEST-RESULTS.xml` do pacote contém as propriedades `stability_metrics` dos testes.

| Cenário | FETCH | Válidos | Descartes | Timeouts | Unknown | Reconexões | Maior lacuna | Duração média da consulta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A: contínuo | 1.000 | 1.000 | 0 | 0 | 0 | 0 | 1.000 ms | 375 ms |
| B: inválido isolado | 201 | 200 | 1 | 0 | 1 | 0 | 2.000 ms | 375 ms |
| C: timeout isolado | 201 | 200 | 1 | 1 | 0 | 0 | 3.400 ms | 383,085 ms |
| D: porta fechada | 201 | 200 | 1 | 0 | 0 | 1 | 4.375 ms | 375 ms |
| E: frame parcial | 201 | 200 | 1 | 0 | 1 | 0 | 2.000 ms | 375 ms |

São tempos do transporte controlado e relógio acelerado, sem instrumento conectado.
O cenário F foi aprovado para resposta inválida, timeout, frame parcial e porta fechada:
**200 amostras térmicas e 200 elétricas por execução**, preservando a mesma sessão.
Também foi aprovado o retorno após **cinco tentativas malsucedidas de reabertura**.

### Arquivos e commits

| Commit | Alteração |
| --- | --- |
| `32f05c4` | `backend/app/adapters/{specific,transports,acquisition_diagnostics,serial}.py`, serviços `acquisition`, `protocol_probe`, `serial_diagnostic`, `usb_discovery`, rotas e testes de estabilidade |
| `69d94b5` | Dashboard, teste de dispositivos, contratos TypeScript e testes da interface |
| `ed5d2a4` | `scripts/seed-ux-demo.py`, testes e guia da demonstração local |
| `2edb171` | Versão 0.6.5, empacotamento, coletor HTTP e roteiro de bancada |
| `6b5afcc` | Cadência das fontes sintéticas nos relatórios e teste de repetição do seed |

O seed adicional é exclusivo de development/test e não usa adapters nem portas seriais.
Sua execução local criou sete sessões; repetições criaram zero duplicatas. As nove
verificações do seed passaram, incluindo a cadência de relatório, e a API local carregou
listagem, detalhes e prévia com as contagens esperadas. Veja [UX_DEMO_SEED.md](UX_DEMO_SEED.md).

## Roteiro físico — pendente

1. Abra a nova versão, associe o AT4532 à COM5, 19200 baud, 8-N-1 e conecte uma vez.
   Mantenha o software do fabricante fechado. Associe o GPM à sua porta e conecte-o.
2. Confirme os canais e temperaturas reais e inicie um ensaio combinado. Anote seu ID.
3. Em Diagnóstico, acompanhe os contadores. Use os testes de comunicação durante o ensaio:
   eles devem apresentar a sessão existente, sem interromper nenhuma fonte.
4. Mantenha 60 minutos (mínimo 30). Para coleta contínua de todos os frames, execute, da raiz:

   ```powershell
   .\.venv\Scripts\python scripts/monitor-serial-stability.py --device-id ID_AT --gpm-id ID_GPM --minutes 60 --output build/bench-065
   ```

   O script pede o token de acesso sem exibi-lo. Também aceita `THERMOPOWER_MONITOR_TOKEN`
   no ambiente. Use `--url http://127.0.0.1:8000/api/v1` no desenvolvimento; no executável,
   confira a porta mostrada no navegador (normalmente 8765). Ele não abre serial nem conecta
   automaticamente uma fonte parada. Salva `observations.jsonl` e `summary.json`, inclusive
   ao ser interrompido com Ctrl+C. Não sobrescreve uma pasta de ensaio anterior.
5. Em um ensaio separado, desconecte o cabo USB do AT por 5–10 segundos e recoloque-o.
   Repita com ausência superior a um minuto. Observe retorno automático, mesmo ID de sessão,
   gráfico preservado e GPM adquirindo. Não clique novamente em Conectar.
6. Exporte o ZIP diagnóstico e os dados da sessão. Verifique contagem de FETCH, descartes,
   timeouts, unknown responses, reconexões, maior lacuna e média de resposta. Confira que
   não há duplicação de amostras ou preenchimento de lacunas com valores antigos.
7. Aceite somente sem encerramento inesperado, intervenção manual, duplicação de sessão ou
   reset de gráfico, com GPM independente e retorno automático do AT após falha transitória.
   Registre tempos observados para eventual ajuste dos limites do watchdog.

Nesta estação a COM5 não foi enumerada; apareceram somente COM3 e COM4 Bluetooth.
Nenhum resultado automatizado deve ser apresentado como ensaio físico de 30/60 minutos.
