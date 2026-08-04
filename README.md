# ThermoPower Monitor

Plataforma full-stack para aquisição industrial combinada: até 32 temperaturas pelo Applent AT4532 e grandezas elétricas pelo GW Instek GPM-8213. As sessões são rastreáveis, aceitam uma ou as duas fontes, sincronizam timestamps e mantêm o protótipo original em `legacy/`.

## Funcionalidades entregues

- login JWT, hash bcrypt, expiração, rate limit básico e RBAC para Administrador, Operador e Visualizador;
- dashboard em tempo real por WebSocket, indicadores, janela temporal, pausa visual, curvas e mapa térmico de 32 canais;
- ciclo persistido de sessão: iniciar, pausar, continuar, finalizar, cancelar, duplicar e excluir conforme permissão;
- potência recebida em mW, W ou kW, preservada na forma original e normalizada em watts;
- configuração dos 32 termopares, offset, tipo, cor, localização, ordem e limites;
- importação assistida de TXT do GPM-8213 e XLSX do AT4532, com prévia e relatório de erros;
- série combinada com dois eixos, brush e pareamento por vizinho temporal mais próximo;
- medições paginadas e série temporal agregada no banco;
- regras e eventos de alerta com severidade, canal, reconhecimento e cooldown;
- eventos de conexão, sessão, configuração, login e falhas;
- estatísticas de média, mínimo, máximo, mediana, desvio padrão, amplitude, percentil 95, frequência e lacunas;
- relatórios CSV, XLSX e PDF gerados no backend;
- comparação de sessões, visão executiva e diagnóstico do sistema;
- simulador configurável com oito cenários;
- adaptadores `SimulatorAdapter`, `SerialJsonAdapter`, `SerialCsvAdapter` e `MockFailureAdapter`;
- tema claro/escuro, interface responsiva, navegação por teclado e estados de erro/vazio/loading;
- OpenAPI em `/docs`, migrations Alembic, testes automatizados e Docker Compose.

## Arquitetura e tecnologias

```text
React + TypeScript + Vite + Recharts
          REST / WebSocket
FastAPI + Pydantic + SQLAlchemy
          DeviceAdapter
SQLite local / PostgreSQL em produção
```

Leia [Arquitetura](docs/ARCHITECTURE.md), [Banco de dados](docs/DATABASE.md), [API](docs/API.md) e [Integração física](docs/DEVICE_INTEGRATION.md).

## Requisitos

- Python 3.11 ou superior (validado com 3.13.1);
- Node.js 22 ou superior (validado com 22.14.0);
- npm 10 ou superior;
- opcionalmente Docker Desktop com Compose.

## Execução local

Na raiz do repositório, crie o ambiente Python e instale o backend:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r backend\requirements.txt
cd backend
..\.venv\Scripts\python -m alembic upgrade head
..\.venv\Scripts\python -m uvicorn app.main:app --reload
```

Em outro terminal:

```powershell
cd frontend
npm install
npm run dev
```

Acesse `http://localhost:5173`. A API estará em `http://localhost:8000` e o Swagger em `http://localhost:8000/docs`.

No Windows, use `iniciar-windows.bat` na raiz. Na primeira execução ele cria o ambiente virtual, instala dependências, aplica migrações, abre backend e frontend e acessa `http://127.0.0.1:5173`. Se falhar, execute `diagnostico-windows.bat` e envie a saída ao suporte.

### Importação AT4532 + GPM-8213

1. Entre no sistema e abra **Importar arquivos**.
2. Selecione o XLSX térmico, o TXT elétrico ou ambos.
3. Gere a pré-visualização e confira período, mapeamento, linhas válidas e erros.
4. Defina nome, grade e tolerância (padrão 1 s / 1,5 s) e confirme.
5. Abra a sessão criada para analisar e exportar CSV, XLSX, PDF, PNG ou JPEG.

Os arquivos reais não devem ser versionados. Como `reference-input/` foi recebido vazio, a homologação dos layouts e da comunicação física depende do fornecimento das amostras e manuais.

Linux/macOS usam os equivalentes `source .venv/bin/activate` e `.venv/bin/python`.

## Usuário de demonstração

- E-mail: `admin@demo.thermopower.com`
- Senha: `ThermoPower@123`

Essas credenciais são exclusivamente iniciais. Defina `THERMOPOWER_DEMO_ADMIN_PASSWORD` e um segredo JWT forte em qualquer implantação. Não exponha a configuração padrão em rede.

## Demonstração do simulador

1. Faça login.
2. Em **Tempo real**, selecione `Aquisitor simulado`.
3. Clique em **Conectar** e **Iniciar sessão**.
4. Escolha um cenário: operação normal, aquecimento gradual, superaquecimento, pico de potência, sensor com defeito, perda de conexão, mensagens inválidas ou sessão longa.
5. Finalize a sessão, abra o histórico e gere CSV, XLSX ou PDF.

## Docker

Copie `.env.example` para `.env`, troque os segredos e execute:

```bash
docker compose up --build
```

A aplicação ficará em `http://localhost:8080`. O Compose inicia PostgreSQL, executa migrations, sobe a API e publica o frontend via Nginx. Consulte [Deployment](docs/DEPLOYMENT.md).

## Testes e qualidade

```powershell
cd backend
..\.venv\Scripts\python -m ruff check .
..\.venv\Scripts\python -m pytest

cd ..\frontend
npm run lint
npm run typecheck
npm test -- --run
npm run build
```

A suíte do backend contém um fluxo completo de login → simulador → sessão → dados → alerta → finalização → histórico → três relatórios. Mais detalhes em [Testing](docs/TESTING.md).

## Configuração

Variáveis usam o prefixo `THERMOPOWER_`. As principais são:

- `DATABASE_URL`: SQLite ou URL SQLAlchemy do PostgreSQL;
- `JWT_SECRET`: chave de assinatura;
- `CORS_ORIGINS`: lista JSON de origens;
- `DEMO_ADMIN_EMAIL` e `DEMO_ADMIN_PASSWORD`;
- `MEASUREMENT_BATCH_SIZE` e `WEBSOCKET_QUEUE_SIZE`.

Veja `.env.example`; nunca versione `.env`.

## Integração serial e formato provisório

O backend, não o navegador, é responsável pela porta. O parser JSON provisório espera UTF-8, uma mensagem por linha:

```json
{"power": 850000, "powerUnit": "mW", "temperatures": [31.2, 31.8, 32.1]}
```

O protocolo não é definitivo. Marca, modelo, framing, checksum, driver e semântica de erros precisam ser homologados com o equipamento. `SerialCsvAdapter` permanece bloqueado para conexão até a ordem das colunas ser aprovada.

## Estrutura

```text
backend/             FastAPI, modelos, serviços, adaptadores, migrations e testes
frontend/            React/TypeScript, páginas, componentes e testes
docs/                arquitetura, API, banco, testes, implantação e escopo
docker/              notas operacionais
legacy/              protótipo original preservado
docker-compose.yml   stack PostgreSQL + API + Nginx
.env.example         configuração segura de referência
AGENTS.md             normas de evolução
```

## Solução de problemas

- **Login não funciona:** confirme se a API está em `:8000` e se a migration/seed executou.
- **Erro `501 Unsupported method ('POST')` ao entrar:** existe um `python -m http.server 8000` antigo em execução. Feche a janela do protótipo legado e reinicie backend e frontend. O sistema novo não deve ser iniciado pelos scripts dentro de `legacy/`.
- **WebSocket reconectando:** confirme o proxy de `/api/`, o token e a origem CORS.
- **Sem medições no histórico:** uma sessão precisa estar em execução; lotes são descarregados a cada dois segundos ou na finalização.
- **Serial não abre:** confirme porta, driver, permissão do processo e baud rate. O hardware real ainda não foi homologado.
- **Banco bloqueado:** SQLite é apenas para desenvolvimento; use PostgreSQL para operação concorrente.

## Limitações atuais

- integração física preparada, mas não homologada sem aquisitor e documentação do fabricante;
- aquisição distribuída/múltiplas réplicas requer coordenação externa (por exemplo Redis/worker dedicado);
- retenção automática, backup gerenciado, assinatura digital e requisitos metrológicos/regulatórios não estão ativados;
- filtros avançados de temperatura e seleção arbitrária de colunas existem no desenho, mas a primeira entrega expõe paginação, potência, período e alternância de 4/16 canais;
- React Router 6 mantém advisories moderados ligados a redirects/SSR; a SPA usa apenas rotas internas constantes e não usa SSR, loaders ou redirects fornecidos pelo usuário. O risco deve ser reavaliado em upgrades.

O escopo implantável e os itens pendentes estão detalhados em [Escopo comercial](docs/COMMERCIAL_SCOPE.md).
