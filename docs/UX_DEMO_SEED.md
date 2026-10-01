# Ambiente local de auditoria UX/UI

Na raiz do repositório:

```powershell
.venv\Scripts\python.exe scripts\seed-ux-demo.py
```

O comando usa a mesma configuração do backend de desenvolvimento: variáveis
`THERMOPOWER_*` e `backend/.env`, com `backend/thermopower.db` como padrão. Não usa o banco
do executável Windows. Só aceita `THERMOPOWER_ENVIRONMENT=development` ou `test` e recusa
`client-preview`, `physical-alpha`, `windows-beta`, produção e executáveis empacotados.

O seed cria exclusivamente estes equipamentos, ambos com protocolo e conexão `simulator`,
sem porta e sem baud rate:

- **ThermoPower Simulator — GPM**
- **ThermoPower Simulator — AT4532**

Nenhum adaptador é instanciado, nenhuma COM é enumerada ou aberta e nenhum SCPI é enviado.
O seed não faz parte do client-preview e não é executado no startup da aplicação.
Cadastros físicos, sessões reais, senhas e permissões existentes são preservados.

## O que revisar

Abra a aplicação de desenvolvimento e procure **DEMO UX** em **Sessões**. Os dados têm
datas fixas entre **01 e 08/09/2026**, a partir das **10h de São Paulo**. Em relatórios por
período, selecione essa semana e os dois simuladores. As datas fixas permitem reproduzir
a mesma auditoria sem depender do dia de execução.

| Sessão | Conteúdo |
| --- | --- |
| Aquecimento e estabilização | 20 minutos, subida gradual e patamar térmico |
| Ciclos de termostato | 30 minutos, ciclos de potência e oscilação térmica |
| Pico térmico e alertas | Aviso reconhecido e alerta crítico pendente no canal 29 |
| Lacuna térmica e sensor aberto | 30 segundos sem amostras térmicas, elétrica contínua, canal 27 Open |
| Somente temperatura | 15 minutos sem potência fabricada |
| Ensaio cancelado pelo operador | Histórico de cancelamento com cinco minutos de dados |
| Ensaio longo de uma hora | 3.601 amostras por fonte, para zoom, downsampling e exportação |
| Análise visual — aquecimento, regime e desligamento | 40 minutos, 481 leituras por fonte, oito canais e três eventos manuais |

São **8 sessões**, **5.227 amostras elétricas**, **5.402 amostras térmicas**,
**172.864 valores/estados de canais**, **32 configurações de canal**, um perfil, duas regras,
dois alertas e eventos sintéticos. Canais 1–24 ficam Open; 25–32 têm temperaturas plausíveis.
Potência é armazenada em watts, preservando as representações originais em mW, W e kW.
Valores ausentes permanecem nulos; a lacuna não recebe dados repetidos.

Confira listagem e detalhes das sessões, metadados editáveis, curvas, legenda, mapa de canais,
qualidade, alertas, filtros de período, exportações e comparação entre fontes.
As sessões gravadas ficam finalizadas ou canceladas; não simulam uma aquisição em andamento.
Para revisar **Tempo real**, selecione manualmente um dos simuladores e use o simulador já
existente. Os dois cadastros usam esse mesmo adaptador genérico; o seed não cria emuladores
de protocolo físico nem altera o comportamento da aquisição.

## Repetição, acesso e banco

Os dados recebem o marcador `thermopower_ux_demo_v1`. Repetir o comando preserva os registros
e não duplica sessões. Cadastros com nomes reservados mas sem o marcador causam uma falha
explícita, sem sobrescrita. Toda a inserção de dados ocorre em uma transação.
Sessões de demonstração antigas recebem a cadência por fonte se esse metadado estiver
ausente, para que o relatório avalie corretamente os intervalos sintéticos de 1 e 5 segundos.

O usuário configurado em `THERMOPOWER_DEMO_ADMIN_EMAIL` é reutilizado. Se ainda não existir,
é criado com a senha de `THERMOPOWER_DEMO_ADMIN_PASSWORD`; sem essa variável, o comando gera
uma senha aleatória e grava somente em `build/ux-demo-access.txt`, ignorado pelo Git.
Senhas de usuários existentes não são redefinidas.

Um banco vazio recebe as migrations Alembic existentes antes dos dados. Um banco já existente
precisa estar na revisão atual; o seed não migra cadastros físicos antigos automaticamente.
SQLite deve ficar em `backend/` ou `build/` deste repositório. PostgreSQL é suportado usando
SQLAlchemy, mas limitado a localhost e bancos com sufixo `_dev` ou `_test`.

Dados e exportações são exclusivamente sintéticos e não constituem validação metrológica,
física ou de estabilidade dos equipamentos.


## Validação das funcionalidades de produto

Sessão recomendada: **DEMO UX — Análise visual — aquecimento, regime e desligamento**,
em **08/09/2026, 10:00–10:40 (America/Sao_Paulo)**. Dados explicitamente sintéticos:

- 10:00–10:10: aquecimento, potência próxima de 1.180 W;
- 10:10–10:25: regime estável, potência próxima de 780 W;
- 10:25–10:40: potência zero após desligamento e resfriamento térmico perceptível;
- termopares ativos T25–T32, com T32 como ambiente;
- eventos de exemplo às 10:10, 10:25 e 10:30.

Nenhum período oficial vem salvo: selecione o patamar e salve durante a validação.
Nenhuma share pública é criada pelo seed. Repetir o comando preserva eventos editados,
período oficial escolhido, compartilhamentos e senhas existentes.

O seed também cria **viewer.ux@demo.thermopower.com**, exclusivamente como viewer de
desenvolvimento. Para conta nova, a senha vem de `THERMOPOWER_UX_VIEWER_PASSWORD` ou
é gerada aleatoriamente. Ela é gravada em `build/ux-demo-access.txt`, ignorado pelo Git;
nenhuma senha existente é redefinida. Admin/operator existentes mantêm todos os campos.
Uma colisão do e-mail reservado com outro perfil ou conta inativa é rejeitada.

Roteiro manual sem hardware:

1. Abra o frontend local e entre como admin existente. Em Sessões, procure o nome
   recomendado. Não é necessário conectar fontes nem iniciar aquisição.
2. Escolha **Selecionar no gráfico**, marque 10:10–10:24:55 por cliques, Brush ou campos
   e aplique. Confira a área destacada, campos, potência média próxima de 780 W,
   médias térmicas e exportações. Compare com sessão completa e com o resfriamento.
3. Salve o período aplicado como **Regime permanente**, reabra a sessão e confira a
   preferência. Volte temporariamente a Sessão completa sem apagar o período salvo.
4. Edite um evento, adicione outro com horário dentro da sessão e confira marcador e
   relatório. Remova o evento criado por você; um horário fora da sessão deve ser rejeitado.
5. Saia e entre como viewer: consulte gráficos, eventos, período oficial, comparação e
   downloads. Não devem aparecer controles de operação, edição ou compartilhamento.
6. Como admin, crie manualmente um link com senha, expiração e somente PDF permitido.
   Abra em janela anônima; teste senha errada/correta, ausência de XLSX/CSV, contadores,
   cópia após recarregar e revogação. O seed não faz esta etapa automaticamente.
7. Para integridade histórica, compare o cenário recomendado com **Lacuna térmica e
   sensor aberto**. O banner de cadência em tempo real usa estados de runtime e não é
   acionado por sessões históricas; sua apresentação é coberta pelos testes frontend,
   sem necessidade de hardware ou alteração de thresholds.

O arquivo continua fora de `thermopower.spec` e das importações da aplicação. A execução
empacotada (`sys.frozen`) é rejeitada, inclusive nas funções de geração de dados/usuário.

## Ambiente preparado em 01/10/2026

Banco local `backend/thermopower.db`, já na revisão `0010_session_shares`.
Sessão recomendada nesta instalação: **#13**, acessível em
`http://127.0.0.1:5173/sessoes/13`. Os IDs podem variar em outros bancos.

Foram verificados pelo frontend/proxy local: login de admin e viewer, detalhe da sessão,
preview de 10:10–10:24:55 com média de **780,12 W**, oito canais, sugestão de estabilidade,
três eventos, zero compartilhamentos e resposta 403 para viewer na gestão de links.
Uma segunda execução criou zero sessões e preservou contas/senhas.

Os processos locais usam frontend Vite na porta 5173 e backend na 8000. O backend foi
iniciado com `--lifespan off` para esta validação sobre banco já migrado/populado, evitando
a rotina normal de startup que revisa cadastros físicos. Nenhuma rota de conexão, probe,
início ou controle de aquisição foi chamada. Para reiniciar esta mesma validação:

```powershell
# Terminal 1, a partir da raiz
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --lifespan off
```

```powershell
# Terminal 2, a partir da raiz
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Validação: **262 testes backend aprovados**; os **13 testes focados do seed** incluem
preservação, idempotência, fases da curva, estabilidade calculada pelo relatório,
eventos, ausência de shares, restrições de ambiente e login real do viewer.
O teste de login cobre a rejeição que motivou trocar o domínio reservado `.test`
pelo endereço de demonstração aceito pela API. Ruff e `git diff --check` aprovados.
Frontend/API/migrations não tiveram alterações nesta preparação; seus gates anteriores
não foram repetidos. Nenhum build Windows ou push foi realizado.
