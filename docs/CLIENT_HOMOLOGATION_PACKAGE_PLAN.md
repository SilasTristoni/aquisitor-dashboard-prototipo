# Plano do pacote de homologação da cliente — 0.5.0-beta

## Estado atual

O ThermoPower Monitor já possui aplicação React/FastAPI, persistência SQLite com migrations
Alembic, simulador de aquisição, relatórios, launcher PyInstaller, instalador Inno Setup e
descoberta COM baseada em pySerial. A descoberta abre e fecha uma porta sem escrever bytes;
os adaptadores físicos AT4532 e GPM-8213 recusam conexão enquanto os protocolos não forem
confirmados com os instrumentos e seus manuais.

## Riscos e controles

- **Falso aceite físico:** simulação, nome de porta, abertura da COM e associação manual nunca
  produzem homologação. A interface e os contratos mantêm estados separados de simulação,
  detecção pelo sistema, disponibilidade, associação, sugestão, identidade confirmada,
  protocolo validado, aquisição validada e homologação.
- **Comando indevido:** o diagnóstico físico é somente leitura e não transmite bytes. As classes
  físicas específicas continuam bloqueadas.
- **Mistura de dados:** o laboratório usa processo, configuração, faixa visual, banco e diretório
  próprios em `%LOCALAPPDATA%\ThermoPower Virtual Lab`.
- **Vazamento no suporte:** o exportador trabalha com uma lista positiva de dados, mascara
  caminhos/usuários e rejeita chaves com aparência de senha, segredo, JWT ou token.
- **Dependência opcional do Windows:** PnP via PowerShell/CIM é complemento tolerante a falhas;
  pySerial permanece como fallback e a aplicação principal não depende do PowerShell.
- **Porta ocupada:** a inspeção respeita aquisições ativas, usa timeout zero e cache curto para
  evitar aberturas repetidas.

## Arquitetura do laboratório virtual

`PortDiscoveryProvider` isola a origem da enumeração. O provider Windows usa
`list_ports.comports`; o provider virtual lê o estado de `VirtualUsbLabService`; o provider de
teste recebe uma coleção determinística. Cada porta carrega `source` e `simulated`.

`VirtualUsbLabService` mantém perfis AT4532 e GPM-8213, plug/unplug, mudança de COM, porta
ocupada, driver ausente, metadados opcionais, ambiguidade, reconexão e falhas. Endpoints de
laboratório só são registrados operacionalmente quando `lab_mode` é habilitado por ambiente
de desenvolvimento/teste ou pelo launcher dedicado. Dispositivos virtuais associados usam
adaptadores virtuais pela mesma cadeia de conexão, WebSocket, sessão, persistência e relatório.

O transporte serial é independente do parser: `RealSerialTransport`, `PySerialLoopTransport` e
`FakeSerialTransport` exercitam abertura, fechamento, escrita, leitura, timeout, fragmentos,
concatenação e reconexão. Loopback é sempre identificado como teste de software e nunca como
USB físico.

## Arquitetura do diagnóstico físico

`UsbDiagnosticService` cria `UsbSnapshot` por meio da descoberta segura e, quando disponível,
de inventário PnP complementar. `UsbSnapshotDiff` compara identidades estáveis (serial,
VID/PID/HWID e porta), separa adições, remoções, alterações e mudança de COM com o mesmo serial.
Capturas ficam em armazenamento local do aplicativo e podem ser nomeadas conforme as seis
etapas do roteiro da cliente.

O exportador cria HTML, PDF, JSONs, versão, log recente sanitizado, README e manifesto SHA-256
em um ZIP. A prévia usa os mesmos dados sanitizados que serão exportados.

## Fluxo de build

1. Validar raiz, branch, arquivos obrigatórios e árvore `legacy/`.
2. Restaurar dependências Python e npm.
3. Executar Ruff, Pytest, ESLint, typecheck e testes frontend.
4. Gerar frontend e os executáveis `ThermoPowerMonitor` e `ThermoPowerVirtualLab`.
5. Executar os três smokes.
6. Gerar instalador opcional, ZIP portátil, ZIP do laboratório e PDFs da cliente.
7. Montar `release/ThermoPower-Monitor-0.5.0-beta`, calcular SHA-256 e validar ZIPs.

O workflow Windows reproduz o fluxo e cria artefatos; tags `v*-beta` criam apenas release draft.

## Fluxo da cliente

1. Instalar ou extrair o portátil e entrar com a credencial de homologação fornecida.
2. Validar a plataforma no atalho separado **ThermoPower Virtual Lab**.
3. No aplicativo principal, abrir **Equipamentos > Diagnóstico** e capturar o estado sem
   equipamentos.
4. Repetir as capturas com AT4532, GPM-8213, ambos, programas dos fabricantes abertos e após
   trocar as portas USB.
5. Revisar a prévia, consentir e exportar o pacote para suporte.
6. Devolver somente o ZIP de diagnóstico e observações do roteiro.

## Matriz de testes

| Área | Casos mínimos | Evidência |
| --- | --- | --- |
| Descoberta | vazio, real, virtual, sem metadados, ambíguo | testes unitários/API |
| Hot-plug | plug, unplug, nova COM, serial persistente, busy, driver | testes e smoke lab |
| Aquisição | AT, GPM, ambos, missing/error, queda/reconexão | testes e sessão virtual |
| Serial | loop://, timeout, parcial, concatenada, encerramento | testes unitários |
| Diagnóstico | snapshots, diff, PnP indisponível, porta ocupada | testes e smoke diagnóstico |
| Privacidade | máscara, lista positiva, ZIP sem segredos | inspeção automatizada |
| Produto | login, migration, frontend, sessão, PDF/JPEG | suites e smoke principal |
| Pacote | executáveis, instalador, ZIPs, hashes | build Windows/CI |

## Dados exportados

São exportados versão e ambiente do aplicativo, versão/arquitetura do Windows, metadados COM e
PnP relacionados, disponibilidade da porta, associação/sugestão, snapshots, diferenças e trecho
sanitizado do log. Não são exportados banco, medições completas, credenciais, JWT, segredo,
inventário de rede, documentos pessoais ou caminhos pessoais completos.

## Segurança

O diagnóstico não escreve na serial, não envia SCPI, não redefine equipamento, não muda
configuração do Windows, não instala driver e não requer administrador. O uso de laboratório é
opt-in, visível e recusado em ambiente de produção. O aviso permanente é: “A detecção confirma
somente que o Windows enumerou um dispositivo. Não confirma a leitura ou homologação do
instrumento.”

## Limitações

Porta virtual não comprova VID/PID, driver, framing, checksum, escala, precisão, firmware ou
comportamento elétrico real. Estados `identity_confirmed`, `protocol_validated`,
`acquisition_validated` e `homologated` exigem registro de teste físico válido e não são gerados
automaticamente pelo laboratório.

## Critérios de aceite

O pacote é aceito quando suites, migrations, build e três smokes passam; executáveis, instalador,
ZIPs, PDFs e hashes existem; laboratório usa armazenamento isolado e percorre a cadeia real da
aplicação; diagnóstico não transmite bytes; exportação contém os arquivos previstos e nenhum
segredo; estados virtuais/reais são inequívocos; workflow publica artefatos/draft; documentação e
release registram honestamente que a aquisição física continua pendente de validação em bancada.
