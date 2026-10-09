# Estado atual AT4532 — 06/10/2026

A evidência nova substitui as hipóteses abaixo: três Celsius produziram três TCP-32 distintos. O runtime 0.7.0 passa a usar Celsius a cada 5 s, com janela de recepção de 4 s, sem FETCH. Consulte [a decisão e os limites da candidata](AT4532_CELSIUS_TRIGGER_070.md). Não restaurar FETCH sem nova evidência física. Estabilidade contínua ainda pendente de bancada.

---

## Histórico anterior à evidência de 06/10/2026

# AT4532 — estado físico atual da 0.6.6

> Documento curto de continuidade. Registro histórico; a decisão vigente está no link acima. Histórico detalhado da correção anterior: `docs/AT4532_FRAMING_066.md`.

## Estado da candidata

**Evidência nova em 01/10/2026:** no ZIP
`AT4532-observation-20261001-093505-613.zip`, a janela passiva de 10 s teve RX=0;
Celsius foi seguido por um TCP-32 válido de 694 bytes (~16 ms até primeiro RX).
FETCH, enviado 9,343 s após último RX, teve RX=0 por 10 s. A guarda de 1 s
não explica esse silêncio. Não está estabelecido que Celsius seja comando de
aquisição. Próxima etapa autorizada: somente caracterização passiva de 5 s +
três Celsius separados por observações de 5 s, sem FETCH. Ferramenta independente,
evidência detalhada e interpretação: [AT4532_REPEATED_CELSIUS.md](AT4532_REPEATED_CELSIUS.md).
Driver, GPM e aquisição de produção preservados nesta etapa. Bancada nova pendente.

- **Bancada reprovada em 29/09/2026.** Os dois novos ZIPs mostram um TCP-32
  recuperado antes de qualquer FETCH transmitido na conexão. No completo,
  FETCHs às 18:15:27.874 e 18:15:32.093 UTC retornaram zero bytes; a guarda
  pós-RX de 1 s foi respeitada. Não aumentar a guarda por hipótese.
- Em 30/09/2026 foi autorizada exclusivamente uma build interna de engenharia
  para caracterização e validação da nova prontidão combinada, sem promoção
  para client-preview final, tag, release ou homologação.
- Versão: `0.6.6-client-preview`.
- A candidata ainda **não está homologada fisicamente**.
- A correção anterior de framing deve ser preservada.
- O GPM-8213 não deve ser alterado sem nova evidência específica.

## Hardware e protocolo confirmados

- AT4532 associado manualmente à porta correta da bancada.
- 19200 baud, 8-N-1.
- `TCP-32` / CP936.
- 32 canais primários.
- `Open` = sensor aberto/indisponível (`null`), nunca zero.
- `*IDN?` pode não responder fisicamente; medição `TCP-32` válida permanece a evidência operacional dentro da política segura já implementada.

## Problema anterior já corrigido

A 0.6.5 podia encontrar apenas `TCP-32` no buffer antes de um novo TX, descartar esses 6 bytes e entregar os 688 bytes restantes ao parser. A primeira candidata 0.6.6 corrigiu essa mutilação.

Evidência atual esperada:

```text
discarded_partial_bytes = 0
full_frame_length = 694
prefix = TCP-32
terminator = CRLF
```

Não reverter a política de preservação/recomposição de boundary documentada em `AT4532_FRAMING_066.md`.

## Evidência física anterior à correção focal

Em 29/09/2026, na primeira candidata 0.6.6, o FETCH de 12:26:18.334 UTC
recebeu 694 bytes válidos às 12:26:19.365 (1031 ms). O próximo FETCH ocorreu
462 ms após RX e expirou. O snapshot inicial registrou sete tentativas, um
sucesso, seis timeouts, uma tentativa de reconexão e lacuna de 28,4 s.

O encerramento posterior registrou 76 tentativas, nove sucessos, 67 timeouts,
22 tentativas de reconexão, 13 falhas de reconexão, 13 frames completos
descartados e lacuna máxima de 110,7 s. Não houve unknown_response nem descarte
de bytes parciais nesse encerramento.

Os probes de leitura/completo recompuseram fragmentos de 6–7 bytes em frames
TCP-32/CP936 completos de 694 bytes, mas descartaram essas medições antes de
outro FETCH. O descarte é comprovado; polling agressivo permanece hipótese
física, não prova de um tempo mínimo exigido pelo firmware. O teste exclusivo
de identidade falhou por timeout de IDN, sem executar FETCH.

## Correção focal implementada

- Guarda pós-RX de **1,0 s**, parametrizada no adaptador, podendo ser aumentada.
  O transporte AT ancora a guarda no último byte físico recebido, inclusive
  durante resync, e reavalia a fronteira após esperar antes de transmitir FETCH.
  Logs e metadados registram guarda, espera e intervalo físico RX→TX.
- Fila exclusiva do AT de **oito frames completos**. O parser estrito valida
  cada candidato; um frame válido e elegível é consumido antes de novo FETCH.
  A transação recuperada registra `tx_sent=false`, `timestamp_tx=null` e
  `response_source=recovered_frame`; não é atribuída a um novo comando.
- Frescor limitado a **cinco segundos monotônicos desde o primeiro byte
  observado**, preservando o horário original do último byte recebido. Não
  depende da coincidência entre relógio do PC e relógio do equipamento.
- Bytes já presentes na abertura são recompostos, mas ficam inelegíveis para
  publicação como medição fresca de idade desconhecida. Expiração, rejeição,
  descarte e estouro da fila são contados. Fechar a COM não transporta a fila
  para a nova conexão física.
- Deduplicação por timestamp do equipamento + SHA-256 do frame, com histórico
  limitado a 256 entradas na mesma instância lógica, preservado nas reconexões.
  Timestamps anteriores ao último aceito são rejeitados conservadoramente.
  Conteúdo diferente no mesmo timestamp não é automaticamente duplicata.
- Uma tentativa adicional de recuperação lógica limitada é compartilhada por
  conexão, Testar leitura, Teste completo e aquisição contínua. Timeout isolado
  não força reconexão. O watchdog continua tratando silêncio persistente e
  perda física da COM, preservando sessão e contadores.
- Após validação TCP-32, a recuperação da mesma instância não repete IDN:
  exige nova medição válida. A associação segura não foi ampliada e o teste
  exclusivo de identidade mantém seu comportamento.
- Preservados parser estrito, Open=null, retenção de fragmentos, bloqueio de TX
  em fronteira incompleta, ausência de reset de entrada e auditoria de perdas.
  Não houve alteração funcional adicional durante o gate completo, nem
  alteração de GPM, frontend, UX, relatórios ou AGENTS.md.

## Validação automatizada em 29/09/2026

Resultados virtuais; **não constituem homologação física**.

| Verificação | Resultado |
| --- | --- |
| Testes focados | 75 aprovados; soak inicialmente excluído |
| Soak e cenários de estabilidade | 16 aprovados |
| Gate completo `physical_regression_fixtures` | 115 aprovados, 118 fora do marcador |
| Backend completo | 233 aprovados |
| Frontend | ESLint, TypeScript, 41 testes e Vite aprovados |
| Qualidade final | Ruff backend e git diff --check aprovados |
| Infraestrutura de pacote | Compose, Alembic upgrade/check e pip check aprovados |

O soak pelo transporte real sobre serial simulada usou respostas de 700–1200 ms,
fragmentação, respostas tardias, ressync, silêncio, duplicatas e perda física:

```ini
unique_published_frames = 1000
recovered_frames_consumed = 10
duplicate_frames_rejected = 13
fetch_timeouts = 17
silent_timeouts = 7
necessary_reconnects = 1
malformed_frames = 0
discarded_partial_bytes = 0
duplicate_samples = 0
unknown_response_from_framing = 0
unnecessary_reconnects = 0
recovered_queue_overflows = 0
maximum_gap_ms = 6200
```

As dez respostas tardias foram consumidas uma vez cada; as 13 cópias repetidas
foram descartadas explicitamente. Os quatro cenários AT+GPM existentes
(invalid, timeout, closed, partial) preservaram a sessão e persistiram 200
amostras por fonte em cada cenário. A reconexão ocorreu somente quando exigida
pela falha simulada correspondente.

Fixtures antigas de 1 Hz foram ajustadas à guarda conservadora. A fixture
all-open passou a gerar timestamps distintos em vez de repetir a mesma amostra.
Uma captura de testes frontend foi interrompida por tratamento de stderr no
PowerShell; somente os testes sem resultado foram retomados. Lint, typecheck e
build não foram repetidos. Permanecem avisos Matplotlib/Pyparsing e React Router.

Evidências locais: `build/gate-066-soak.xml`, `build/gate-066-physical.xml`,
`build/gate-066-full.xml` e `build/gate-066-frontend.log`.
Candidata Windows: `engineering/ThermoPower-0.6.6-client-preview-at4532-20260929`.
O empacotamento reutiliza esses gates e só promove o ZIP após os smokes normais,
manifesto SHA-256 e extração/verificação integral. As evidências acompanham o
pacote. A build identifica as fontes locais não commitadas por manifesto;
`iniciar-windows.bat` e sua modificação preexistente ficam fora da entrega.

## Limites que dependem da bancada

A guarda de 1 s e o frescor de 5 s são parâmetros candidatos de engenharia.
O instante de observação dos bytes não prova quando o firmware produziu a
medição. Retrocesso/reset do relógio do equipamento pode resultar em rejeição
conservadora; deduplicação é limitada à memória da instância e não promete
eliminação global de replays após reiniciar o aplicativo. Validar frequência
sustentável, recuperação, relógio e estabilidade AT+GPM nos equipamentos reais.


## Próximo aceite físico

A nova candidata só pode avançar após bancada real:

1. `Testar leitura`;
2. `Teste completo`;
3. AT sozinho por 5 min;
4. AT + GPM por 10 min;
5. sessão combinada;
6. soak físico de 30–60 min.

Critérios mínimos:

```text
discarded_partial_bytes = 0
unknown_response causado por framing = 0
duplicate_samples = 0
reconnects desnecessários = 0
```

A frequência exata não é prioridade sobre estabilidade. Uma cadência menor, porém contínua e auditável, é preferível a forçar 1 Hz causando timeouts.

## Engenharia de caracterização e prontidão — 30/09/2026

Ferramenta isolada em `app/engineering/at4532_characterization.py`, acessível
no executável por `--characterize-at4532`. Reutiliza o assembler de frames e
parser AT de produção, sem conectar o adaptador, IDN, polling, recovery ou
reconnect. Observa abertura passiva (5–10 s), configuração Celsius (10 s),
primeiro FETCH (10 s) e segundo FETCH (10 s) somente após frame saudável na
janela do primeiro. Fronteira parcial bloqueia TX; bytes e motivos permanecem
na evidência. Guarda de 1 s preservada, sem aumento arbitrário.

No Windows, pyserial 3.5 executa PurgeComm internamente ao abrir. A ferramenta
usa exclusivamente para engenharia uma abertura equivalente sem essa limpeza;
o transporte de produção permanece inalterado. DTR/RTS e intervalos de chamadas
ao driver são registrados. Não confundir esses horários com instrumentação
elétrica do fio. Uso: `docs/AT4532_CHARACTERIZATION.md`.

`prepare_common_start` agora define T0 antes de conectar fontes e captura também
leituras recebidas enquanto a outra fonte conecta. Uma observação nova, saudável
e não duplicada torna cada fonte pronta, independentemente de delta ou idade
relativa à outra. `sync_tolerance_ms` permanece aceito por compatibilidade de API,
mas não participa da autorização de início. Prazo global de preparação: 15 s;
limite explícito de 4096 amostras por fonte, com falha observável ao excedê-lo.
Cancelamento/timeout limpa preparação, preservando leitores independentes.
Ativação usa `started_at=T0`, mesmo session_id, horários originais e transferência
única das amostras preparatórias. Sem interpolação nem criação de pares.

Probe AT read informa uma medição válida, sem afirmar continuidade. Full exige
duas medições distintas; runtime ativo deve produzir novas observações após o
pedido, sem abrir outra COM ou reutilizar latest como prova de progressão.
O teste exclusivo de identidade e o protocolo/parser GPM foram preservados.

Validação focal consolidada: **172 testes distintos aprovados**, incluindo
GPM em T0+0,4 s e AT em T0+6 s, ordem inversa, preservação de amostras,
deduplicação, captura durante conexão, timeout, cancelamento pela rota,
probes, framing, recuperação e regressões existentes AT/GPM/sessões.
Cinco falhas iniciais da fixture (nome ausente) foram corrigidas e reexecutadas;
os XML originais e os resultados posteriores permanecem disponíveis.
Evidências: `build/characterization-focused-{protocols,core,tool}.xml`.
Backend completo e frontend não foram repetidos nesta etapa; frontend estático
reutilizado. O ZIP interno só é montado após esses testes e smokes do pacote.

O silêncio do AT após FETCH permanece sem causa física estabelecida. A nova
barreira não torna pronta uma fonte que nunca entrega nova leitura. Aceite
físico obrigatório: 10/10 completos AT; 5 min AT; 10 inícios combinados; 10 min
com ambos contadores aumentando; depois 30–60 min combinado. Qualquer falha
mantém a candidata reprovada.
