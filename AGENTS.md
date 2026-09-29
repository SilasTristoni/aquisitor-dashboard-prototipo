# ThermoPower Monitor - normas do repositório

## Objetivo

Evoluir o ThermoPower Monitor como produto industrial full-stack, mantendo a integração com hardware desacoplada e o simulador sempre utilizável.

## Convenções obrigatórias

- Código, nomes de arquivos, componentes, tipos e variáveis em inglês; textos da interface em português do Brasil.
- O frontend nunca acessa diretamente portas seriais. Toda aquisição passa pelo backend e pela interface `DeviceAdapter`.
- Potência é persistida em watts, preservando também valor e unidade originais. Temperatura é persistida em graus Celsius.
- Segredos e senhas reais não entram no repositório. Configuração sensível vem do ambiente.
- Endpoints de coleções usam paginação. Séries extensas usam agregação/downsampling no backend.
- Toda mudança de comportamento deve incluir ou atualizar testes proporcionais ao risco.
- Compatibilidade de PostgreSQL deve ser mantida, mesmo que SQLite seja o padrão de desenvolvimento.
- Alterações de esquema são feitas por migrations Alembic.
- Recursos dependentes do aquisitor real devem ser explicitamente marcados como pendentes de validação física.

## Aquisição física e integridade dos dados

- Nunca fabricar, interpolar ou reutilizar amostras físicas como se fossem novas leituras reais.
- Preservar timestamps recebidos e timestamps do equipamento quando disponíveis; lacunas reais permanecem lacunas.
- Falha de uma fonte não deve derrubar a outra. Recuperação/reconexão deve preservar `session_id`, contadores e histórico já persistido.
- O AT4532 usa associação física controlada, 19200 baud, 8-N-1, frame `TCP-32`, CP936 e 32 canais. `Open` representa sensor aberto/indisponível e deve resultar em `null`, nunca zero.
- `*IDN?` pode não responder fisicamente no AT4532. A validação por medição `TCP-32` só é permitida dentro da política de associação segura existente; não ampliar fallback para portas ambíguas.
- Nunca aceitar silenciosamente frame `TCP-32` mutilado e nunca inventar comandos SCPI, Modbus, registradores ou comportamento de firmware sem fonte/evidência válida.
- Não propor atualização de firmware como correção de software para o AT4532 sem necessidade externa explícita.
- A integração do GPM-8213 já possui validação física; não alterar protocolo, parser ou aquisição do GPM sem evidência específica de regressão.

## Escopo durante investigação física

- Ao corrigir aquisição física, não alterar UX, relatórios ou componentes não relacionados sem evidência de dependência real.
- Começar pelos arquivos explicitamente indicados no problema e expandir o escopo somente quando a evidência exigir.
- Não fazer refactor amplo, alteração cosmética ou mudança de arquitetura junto com uma correção física crítica.
- Diagnósticos físicos anexados e documentos `CURRENT_STATE` relevantes têm prioridade sobre hipóteses antigas ou resultados apenas sintéticos.

## Estratégia de trabalho e economia de execução

- Quando a tarefa fornece arquivos-alvo, não varrer o repositório inteiro sem necessidade.
- Ler primeiro este `AGENTS.md` e o documento de estado atual específico do problema, quando existir.
- Durante investigação: testes focados primeiro; não rodar suíte completa nem build a cada tentativa.
- Após a correção focal: executar gate/regressões físicas relevantes.
- Executar a suíte completa uma vez antes da entrega candidata.
- Executar frontend completo somente quando contratos/API/UI forem afetados.
- Gerar build Windows, smoke, manifesto e ZIP somente após código e testes relevantes estarem verdes.
- Não repetir comandos caros se os arquivos relevantes não mudaram.
- Não fazer commit/push/tag de release de experimentos intermediários sem solicitação explícita.

## Release e homologação

- `client-preview` não significa homologação física.
- Não declarar integração física aprovada com base apenas em fixtures, mocks, soak virtual ou testes automatizados.
- Homologação física exige bancada real com os equipamentos, incluindo estabilidade contínua e recuperação de falhas quando aplicável.
- Preservar builds anteriores; novas candidatas não devem sobrescrever artefatos já validados.

## Organização

- `frontend/`: React, TypeScript e Vite.
- `backend/app/api/`: rotas HTTP e WebSocket.
- `backend/app/core/`: configuração, segurança e infraestrutura transversal.
- `backend/app/models/`: modelos persistidos.
- `backend/app/schemas/`: contratos Pydantic.
- `backend/app/services/`: regras de negócio.
- `backend/app/adapters/`: fontes de aquisição.
- `backend/tests/`: testes automatizados do backend.
- `frontend/src/**/*.test.tsx`: testes do frontend.
- `legacy/`: cópia imutável do protótipo original.
- `docs/`: decisões técnicas, operação e escopo comercial.

## Qualidade antes de entregar

Execute, corrija e registre os resultados proporcionais ao escopo. Antes da entrega final, execute:

```bash
cd backend && pytest
cd frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build
docker compose config
```

Não altere o conteúdo de `legacy/` depois de criado.
