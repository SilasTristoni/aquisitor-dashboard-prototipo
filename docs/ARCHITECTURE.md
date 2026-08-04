# Arquitetura do ThermoPower Monitor

## Estado encontrado

O repositório inicial é uma aplicação estática composta por `index.html`, `styles.css` e `app.js`. O JavaScript concentra UI, simulação, aquisição Web Serial, cálculos, alertas, histórico e exportação. O estado reside exclusivamente na memória do navegador e desaparece ao recarregar a página.

Pontos positivos preservados: identidade azul industrial, dashboard direto, normalização de unidades, simulador, eventos, alertas e exportações. A camada aditiva suporta 32 termopares e separa as séries térmica e elétrica sem remover o contrato legado.

O fluxo integrado é `adapter/importer → TemperatureReading|ElectricalReading → tabelas independentes → sincronização por vizinho temporal → API/gráfico/exportação`. A associação `session_devices` permite que apenas uma fonte exista sem fabricar valores para a outra.

Problemas que impedem uso comercial:

- ausência de autenticação, autorização, persistência e auditoria;
- acesso à serial acoplado ao navegador e dependente de Chrome/Edge;
- nenhuma validação contratual do payload ou isolamento de protocolo;
- crescimento ilimitado de amostras em memória;
- alertas e estatísticas apenas locais e recalculados a cada renderização;
- ausência de paginação, migrations, API, testes, logs estruturados e tratamento global de erros;
- mojibake visível em alguns ambientes por tratamento inconsistente de UTF-8;
- sessões não possuem ciclo de vida persistido nem recuperação após falha;
- nenhuma estratégia de produção, backup, retenção ou integração física.

## Arquitetura alvo

```text
React/Vite SPA
  | REST (cadastros, consultas, comandos, relatórios)
  | WebSocket (medição/status/alerta/evento + heartbeat)
FastAPI
  | API -> services -> repositories/models
  | AcquisitionService -> DeviceAdapter
  |                   -> SimulatorAdapter
  |                   -> SerialJsonAdapter
  |                   -> SerialCsvAdapter (desabilitado)
  |                   -> MockFailureAdapter
SQLAlchemy -> SQLite (local) / PostgreSQL (produção)
```

O backend é a autoridade sobre autenticação, dispositivo, sessão, aquisição, normalização, alertas, estatísticas e persistência. O frontend mantém apenas estado de apresentação e cache das consultas.

## Decisões

- **API stateless com JWT:** simples para SPA e preparada para implantação distribuída. Token curto e identidade/role validados em cada rota.
- **SQLAlchemy 2 + Alembic:** portabilidade SQLite/PostgreSQL, migrations auditáveis e consultas parametrizadas.
- **Adaptadores assíncronos:** o protocolo físico não contamina regras de negócio. O contrato retorna um payload canônico validado.
- **Um worker de aquisição por dispositivo:** evita leituras duplicadas. A primeira entrega limita execução local a um processo; produção multi-instância exigirá coordenação externa.
- **WebSocket tipado:** envelopes possuem `type`, `timestamp` e `payload`; filas limitadas evitam crescimento causado por cliente lento.
- **Agregação no backend:** endpoints de séries aceitam janela e limite de pontos. Listagens usam paginação por página.
- **Estatística incremental:** contagem, soma, mínimo e máximo são atualizados durante aquisição; análises mais caras são calculadas sob demanda no backend.
- **Relatórios gerados no backend:** CSV, XLSX e PDF compartilham filtros e respeitam autorização.
- **Relatórios por período segmentados:** a consulta lê os fluxos independentes, separa sessões
  concorrentes e calcula estatísticas/energia antes do downsampling. Matplotlib/Agg gera os
  gráficos e ReportLab monta o documento multipágina.
- **Descoberta de hardware no backend:** a SPA não toca portas seriais. O serviço enumera e
  testa abertura sem comandos, associa por serial/VID+PID/porta e deixa explícita a confiança.
- **Runtime Windows autocontido:** PyInstaller inclui API, migrations e SPA; o launcher usa
  `%LOCALAPPDATA%` e o FastAPI serve os arquivos estáticos no modo empacotado.

## Segurança

Senhas usam bcrypt, tokens expiram, CORS é configurável e login possui limitação básica por IP/e-mail em memória. Pydantic valida entradas; SQLAlchemy parametriza SQL. Logs não registram senhas ou tokens. Em produção são obrigatórios HTTPS, segredo forte, PostgreSQL, proxy reverso e rate limiting compartilhado.

## Desempenho e confiabilidade

Medições possuem índices por sessão/tempo. Aquisição usa lotes curtos e o WebSocket publica apenas o ponto atual. Gráficos solicitam séries agregadas; tabelas nunca recebem a sessão completa sem paginação. Retenção e particionamento são políticas de implantação e estão documentados, não executados automaticamente.

## Limites arquiteturais atuais

- Protocolo, driver, identificadores, framing e tolerâncias do equipamento real são desconhecidos.
- Serial é validável somente com porta e amostras reais.
- Alta disponibilidade e múltiplos workers exigirão Redis/filas ou locking distribuído.
- Assinatura digital, trilha regulatória e requisitos metrológicos dependem do mercado de destino.
