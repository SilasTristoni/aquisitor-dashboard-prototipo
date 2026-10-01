# AT4532 — segunda caracterização de engenharia

Uso interno, sem homologação física e sem alteração do driver de produção.
Executável independente: não inicia aplicação, banco, GPM, aquisição contínua,
descoberta de portas ou recuperação.

## Evidência anterior, 01/10/2026

Arquivo: `AT4532-observation-20261001-093505-613.zip`.
SHA-256: `b224d5a9975de0b4278058922edca73fe5b5be0b1fca6bd4eb467c278a98e310`.
Os três arquivos de evidência foram conferidos contra `SHA256SUMS.txt`.

- COM5, 19200, 8-N-1; entrada vazia; janela passiva de 10 s sem RX.
- Write Celsius iniciado em `12:35:16.689328 UTC`, concluído em
  `12:35:16.690359 UTC`.
- Primeiro RX em `12:35:16.699360 UTC`; último em `12:35:17.353777 UTC`.
  Relógio monotônico: aproximadamente 16 ms até o primeiro byte e 657 ms até
  completar o frame, desde o início do write. UTC e monotônico têm resoluções
  distintas nessa captura; não equiparar à latência elétrica no fio.
- Único frame: 694 bytes, TCP-32, CRLF, parser válido, 32 canais.
  SHA-256: `fbe43fa71f82b586735c42c5f5f906034401de867c50e3836fef644609dc2ac6`.
- Timestamp textual: `2026/10/01 09:40:17`; parser existente normaliza para
  `2026-10-01T12:40:17+00:00`. Não corrigir relógio nem assumir sincronização
  com o computador. CH01–24: `null` (Open); CH25–32:
  `25.76, 24.10, 23.15, 22.73, 23.03, 23.01, 23.08, 24.13 °C`.
- Write FETCH concluído em `12:35:26.689111 UTC`, 9,343 s após o último RX;
  nenhum byte nos 10 s seguintes.

Neste ensaio, a guarda pós-RX de 1 s não explica o silêncio após FETCH.
A associação temporal com Celsius não estabelece que seja um comando de
aquisição nem prova que repetições produzam medições novas.

## Executar o novo pacote na bancada

Fechar ThermoPower e qualquer programa que utilize a porta. Extrair o ZIP
inteiro e, na pasta extraída, executar:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\characterize-at4532-repeated-celsius.ps1 -Port COM5
```

Sequência fixa, aproximadamente 20 s:

1. Abrir somente a COM indicada, 19200 / 8-N-1, sem limpeza de buffers.
2. Observar passivamente 5 s.
3. Enviar `SYST:UNIT CEL\n` #1 e observar 5 s.
4. Enviar `SYST:UNIT CEL\n` #2 e observar 5 s.
5. Enviar `SYST:UNIT CEL\n` #3 e observar 5 s; fechar a porta.

Nenhum FETCH, IDN, comando adicional, retry ou reconnect. A proteção existente
de fronteira completa + 1 s após RX é preservada. Bytes pendentes provocam
espera adicional registrada em janelas `*_pre_tx`; após até 10 s sem fronteira
segura, aborta e conserva os bytes. Tráfego espontâneo/parcial pode ampliar o
tempo total; os horários reais são a evidência.

O launcher gera pasta e ZIP, inclusive quando a execução falha após criar a
pasta. Preservar a captura completa para revisão.

## Arquivos e interpretação

- `events.jsonl`: início/fim reais das chamadas write/read, UTC e monotônico,
  bytes hexadecimais, tamanhos, filas, janelas, flush, erros e fechamento.
- `frames.json`: frames completos válidos/inválidos, bytes originais, SHA-256,
  primeiro/último RX, validade/erro do parser, timestamp do equipamento
  normalizado e temperaturas quando válidos. Timestamp textual permanece no
  payload original. Frames idênticos são mantidos separadamente.
- `summary.json`: cada comando, horários do write, RX inicial/final, total de
  bytes, frames, latências comando → primeiro byte e → frame completo, bytes
  parciais e comparações de hash, timestamp e temperaturas por canal.
  Silêncio resulta em zero bytes e horários `null`; janela não executada fica
  explicitamente incompleta. RX pré-TX permanece separado.
- `build-info.json` e `SHA256SUMS.txt`: identificação das fontes e integridade.

Latências partem do início da chamada write e terminam no retorno da leitura
do primeiro/último byte. Não são instrumentação elétrica. Timestamps recebidos
não são corrigidos; nenhum canal é interpolado ou fabricado. `Open` é `null`.
Frame incompleto conserva bytes e não recebe falsa validação ou temperatura.

Comparar as três respostas: hashes idênticos indicam payload repetido; diferenças
somente no timestamp não provam renovação dos sensores. Avaliar também progressão
temporal e temperaturas, respostas múltiplas e tráfego passivo. A ferramenta
não declara aquisição nova nem altera produção com base no resultado.

## Desenvolvimento e empacotamento

```powershell
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m app.engineering.at4532_repeated_celsius --port COM5 --output build\nova-captura
```

O comando acima acessa a porta física e destina-se exclusivamente à bancada.
Os testes locais usam serial e relógio falsos:

```powershell
.\.venv\Scripts\python.exe -m pytest -c backend/pyproject.toml backend/tests/test_at4532_repeated_celsius.py backend/tests/test_at4532_characterization.py --basetemp=build/pytest-repeated-new --junitxml=build/repeated-tests.xml
.\.venv\Scripts\python.exe scripts/package-at4532-repeated-celsius.py --evidence build/repeated-tests.xml
```

O empacotador exige testes aprovados, gera apenas o executável independente,
inclui fontes e manifesto, faz smoke com porta deliberadamente inexistente e
confere o ZIP integralmente. Não usa `thermopower.spec`, não gera release,
não inclui seed, credenciais ou banco local e preserva pacotes anteriores.

## Validação local em 01/10/2026

- 15 testes focados aprovados: sequência/timing, fragmentação, frames idênticos,
  silêncio, frame inválido/parcial, proteção pré-TX, escrita incompleta,
  rejeição de comando adicional e persistência da evidência em falha.
- Backend completo: **271 aprovados**, 20 avisos existentes, 173,80 s,
  incluindo regressões físicas com fixtures e alterações anteriores de produto/seed.
- Ruff e verificação de whitespace aprovados. Compose validado com
  `build/tools/docker-compose.exe config --quiet`.
- Gates anteriores do frontend preservados: lint, typecheck, build e 46 testes
  aprovados; nenhuma alteração adicional de frontend nesta caracterização.
- Evidências: `build/repeated-celsius-focused-final.xml` e
  `build/repeated-celsius-full.xml`. A primeira tentativa focal teve dois erros
  de acesso à pasta temporária padrão; execução com `--basetemp` local aprovada.
- Nenhuma execução em porta física. O ZIP inclui `TEST-RESULTS.xml`, fontes,
  hashes e o resultado do smoke do executável com porta inexistente.
