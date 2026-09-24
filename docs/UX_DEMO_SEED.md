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
datas fixas entre **01 e 07/09/2026**, a partir das **10h de São Paulo**. Em relatórios por
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

São **7 sessões**, **4.746 amostras elétricas**, **4.921 amostras térmicas**,
**157.472 valores/estados de canais**, **32 configurações de canal**, um perfil, duas regras,
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
