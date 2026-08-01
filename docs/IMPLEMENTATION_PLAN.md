# Plano de implementação

## Funcionalidades e fases

### Fase 1 - análise e preservação

- Inventariar e ler todos os arquivos existentes.
- Registrar arquitetura atual, riscos e decisões.
- Criar `AGENTS.md` e documentação inicial.
- Mover uma cópia fiel do protótipo para `legacy/`.

### Fase 2 - fundação

- Criar SPA React/TypeScript/Vite, design system responsivo, tema claro/escuro, roteamento e sessão autenticada.
- Criar FastAPI em camadas, configuração por ambiente, SQLAlchemy, migrations e dados iniciais idempotentes.
- Implementar JWT, bcrypt e RBAC para Administrador, Operador e Visualizador.
- Criar Dockerfiles, Compose, health checks e `.env.example`.

### Fase 3 - aquisição

- Definir `DeviceAdapter` e payload canônico sem presumir protocolo físico.
- Implementar simulador configurável e cenários; preparar JSON serial, CSV serial desabilitado e falha controlada.
- Implementar ciclo conectar/iniciar/parar/desconectar, persistência de sessão e medições, alertas com cooldown e eventos.
- Publicar envelopes tipados por WebSocket com heartbeat e fila limitada.

### Fase 4 - operação

- Dashboard em tempo real com indicadores, séries, janela temporal, pausa visual e 16 canais.
- Gestão de dispositivos, canais, sessões, medições paginadas, alertas e eventos.
- Estados de loading/erro/vazio, feedback, responsividade e navegação por teclado.

### Fase 5 - análise e relatórios

- Detalhe e comparação de sessões, estatísticas, lacunas e violações.
- Dashboard histórico agregado.
- Exportações CSV, XLSX e PDF filtradas e geradas no backend.

### Fase 6 - qualidade

- Testar unidades, parsers, simulador, alertas, estatísticas, autenticação, permissões, sessões, paginação, API e fluxo WebSocket viável.
- Testar login, dashboard, filtros, canais, alertas e falhas no frontend.
- Validar lint, type checking, testes, build e configuração Docker.
- Completar documentação operacional e comercial.

## Riscos e mitigação

| Risco | Impacto | Mitigação |
|---|---:|---|
| Protocolo físico desconhecido | Alto | Contrato de adaptador, parsers isolados, fixture NDJSON e homologação posterior |
| Sessões longas | Alto | Índices, paginação, lotes, agregação e limite de pontos |
| Queda do dispositivo | Alto | Estados explícitos, eventos, adaptador de falha e reconexão configurável |
| Alert storm | Médio | Cooldown por regra/métrica/canal |
| SQLite sob escrita concorrente | Médio | Uso apenas local; PostgreSQL recomendado em produção |
| Relatório grande | Médio | Filtros, resumo padrão e geração server-side |
| Um processo de aquisição | Médio | Restrição documentada; coordenação distribuída como evolução |
| Credenciais de demonstração | Médio | Seed configurável e troca obrigatória em produção |

## Critérios de aceite verificáveis

- `docker compose up --build` expõe frontend e backend saudáveis.
- Login de demonstração retorna token e rotas negam perfil insuficiente.
- Dispositivo simulado conecta; sessão inicia, pausa, continua e finaliza.
- Leituras em mW/W/kW são normalizadas e persistidas com valor/unidade originais.
- WebSocket atualiza dashboard; perda de conexão é indicada.
- Dezesseis canais são configuráveis e seus limites geram alertas com cooldown.
- Sessões e medições aparecem em consultas paginadas.
- Séries temporais respeitam janela e limite de pontos.
- CSV, XLSX e PDF são baixáveis para sessão autorizada.
- Fluxos essenciais possuem testes automatizados; lint, tipos e build passam.
- Tudo que exige hardware está isolado e identificado como não homologado.

## Definição de pronto

Uma fase só é considerada concluída quando código, testes e documentação correspondentes existem e as verificações executáveis passam. Recursos de hardware podem ficar em estado `prepared/not-validated`, nunca apresentados como homologados.
