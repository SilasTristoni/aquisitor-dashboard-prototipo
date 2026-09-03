# Pacote portátil Windows — 0.5.6-physical-alpha

## Objetivo e limites

Este pacote é uma build de engenharia para homologar em Windows 10/11 x64 a aquisição física
independente e combinada do GPM-8213 e do AT4532. Ele não é beta, instalador final nem release de
cliente. O ZIP e o executável são artefatos locais ignorados pelo Git.

O GPM-8213 GES913349/V1.05 já possui cadeia física validada, inclusive a resposta abreviada
`:NUM:NORM:NUMB 8`. O AT4532 possui `FETCH?` físico TCP-32/CP936 validado por medição; sua
identidade permanece `unconfirmed` porque `*IDN?` retorna timeout. Os 34 campos posteriores ao
bloco primário de 32 canais são preservados sem semântica inventada.

## Gerar a engineering build

Pré-requisitos no computador de build:

- Windows x64;
- Python 3.11 ou superior e `.venv` criado;
- Node.js LTS/npm;
- dependências de `backend/requirements.txt` e PyInstaller 6.15.0.

Na raiz do repositório:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\build-windows-engineering.ps1
```

Se as dependências já estiverem instaladas e conferidas:

```powershell
.\scripts\build-windows-engineering.ps1 -SkipDependencyInstall
```

O script interrompe antes do empacotamento se falhar Ruff, a suíte física obrigatória, Pytest
completo, Alembic, `pip check`, Docker Compose quando disponível, ESLint, typecheck, testes do
frontend ou Vite. Depois do PyInstaller ele executa automaticamente o smoke hermético do pacote,
monta o manifesto SHA-256, extrai o ZIP em diretório temporário e verifica novamente cada arquivo.
Somente então promove os artefatos validados, com rollback da versão-alvo caso a promoção falhe.

Saídas esperadas:

- `engineering\ThermoPower-0.5.6-physical-alpha\`;
- `engineering\ThermoPower-0.5.6-physical-alpha.zip`.

A pasta contém `ThermoPowerMonitor.exe`, `_internal\`, `ENGINEERING-BUILD.txt`,
`PROTOCOL-SOURCES.txt`, `TEST-RESULTS.txt` e `SHA256SUMS.txt`. Builds de engenharia anteriores são
preservadas.

## Executar no computador de homologação

1. Confira o SHA-256 do ZIP informado no relatório da build.
2. Extraia o ZIP por completo, preservando a pasta `_internal` ao lado do executável.
3. Feche os softwares dos fabricantes e qualquer terminal que possa manter COM3/COM5 abertas.
4. Execute `ThermoPowerMonitor.exe` sem privilégios administrativos, salvo política local em
   contrário.
5. Entre com as credenciais locais de homologação:
   - e-mail: `homologacao@demo.thermopower.com`
   - senha: `ThermoPower-HML@2026`

Essas credenciais pertencem apenas à build de engenharia local. Segredos reais e ambientes
compartilhados devem usar variáveis `THERMOPOWER_*` próprias.

## Roteiro físico obrigatório

1. Confirme o GPM-8213 GES913349 descoberto dinamicamente por serial USB e associado à COM atual.
2. Rode o probe GPM e confira IDN V1.05, `NUMBER?` classificado como `item_count`, HEADER, VALUE e
   `IHz=null` para `NAN`.
3. Associe manualmente o AT4532 à COM5 pela descoberta. Não autorize COM2 apenas por também ser
   CH340.
4. Rode o probe AT e confira timeout de identidade como warning, `SYST:UNIT CEL`, `FETCH?`,
   `wire_encoding=cp936`, 69 campos, 24 canais `Open`, 8 canais válidos e 34 auxiliares brutos.
5. Conecte as duas fontes. Confira potência em ciclo aproximado de 1 s e temperaturas em ciclo
   aproximado de 3 s, sem duplicação de amostras térmicas.
6. Inicie uma sessão combinada e valide cartões, contagens por fonte, média somente dos canais
   válidos e máximo térmico.
7. Desconecte uma fonte por vez e confirme que a outra continua adquirindo e persistindo.
8. Finalize a sessão, exporte o diagnóstico e confirme o fechamento das portas COM.

## Dados, logs e diagnóstico

Por padrão, a execução portátil mantém os dados locais em:

```text
%LOCALAPPDATA%\ThermoPower Monitor\
  data\thermopower.db
  logs\thermopower.log
  reports\
  jwt-secret.key
```

O diagnóstico deve preservar RX bruto, HEX, encoding, timestamps, tokens CH01–CH32, campos
auxiliares, erros de parser e status separado de cada fonte. Não publique ZIPs de diagnóstico,
XLSX físicos, executáveis ou builds de engenharia no Git.

## Limitações conhecidas

- A próxima execução na máquina da cliente ainda deve homologar os valores contra instrumentos de
  referência; os testes automatizados reproduzem as evidências físicas já capturadas.
- A identidade do AT4532 continua não confirmada enquanto `*IDN?` não responder.
- Os 34 campos auxiliares TCP-32 continuam semanticamente desconhecidos e são apenas preservados.
- A ausência de Docker no host não impede a build; nesse caso o gate opcional é registrado como não
  disponível.

## Solução de problemas

- **Porta ocupada:** feche softwares do fabricante e terminais seriais antes de repetir.
- **AT associado à porta errada:** refaça a associação pela descoberta; o fallback é invalidado se a
  impressão digital da porta mudar.
- **Aplicação não iniciou:** consulte `logs\thermopower.log` e `thermopower-crash.log`.
- **Banco não migrou:** preserve o SQLite e os logs; não edite o banco manualmente.
- **Antivírus bloqueou:** forneça os hashes ao time de segurança; não desative a proteção.
