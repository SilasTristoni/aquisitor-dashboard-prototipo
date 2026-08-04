# Banco de dados

## Estratégia

SQLite é o padrão local. PostgreSQL 17 é usado pelo Compose e recomendado para produção. SQLAlchemy mantém os modelos portáveis; Alembic aplica o esquema inicial.

## Entidades

- `users`: identidade, hash de senha, perfil e ativação;
- `devices`: identificação, conexão, protocolo e metadados;
- `channel_configurations`: até 32 configurações por equipamento, incluindo ordem visual;
- `session_devices`: associa uma sessão às fontes `temperature`, `electrical` ou `combined`;
- `temperature_samples` e `temperature_channel_values`: amostra térmica e valores normalizados por canal;
- `electrical_samples`: grandezas elétricas normalizadas e mapas de valores/unidades originais;
- `session_channel_configurations`: snapshot imutável dos canais no início da sessão;
- `channel_profiles` e `channel_profile_values`: perfis reutilizáveis de configuração;
- `measurement_sessions`: ciclo de vida e contexto da coleta;
- `measurements`: timestamp, potência original/normalizada e qualidade;
- `temperature_measurements`: valor por medição/canal;
- `alert_rules` e `alert_events`: regra, cooldown e ocorrência reconhecível;
- `system_events`: trilha operacional;
- `reports`: auditoria de geração por sessão ou período, filtros, estado e erro saneado.

Índices compostos cobrem sessão+timestamp, medição+canal, equipamento+canal e evento+categoria. Exclusões em cascata são usadas nas relações de alto volume.

## Migrations

`0002_dual_device_integration` é aditiva. Ela mantém as tabelas legadas, associa sessões antigas ao equipamento original, copia potência e temperatura para as novas estruturas e completa canais ausentes até T32 como desativados. A rotina usa operações SQLAlchemy portáveis entre SQLite e PostgreSQL.

`0003_period_reports` preserva relatórios existentes, preenche `scope_type=session`, torna
`session_id` opcional e acrescenta período, fuso, título, filtros, status e mensagem de erro.
O `batch_alter_table` mantém a alteração compatível com SQLite; os tipos e índices também são
válidos em PostgreSQL. No downgrade, relatórios de período sem sessão são removidos antes de
restaurar a restrição antiga.

```bash
cd backend
alembic upgrade head
alembic revision --autogenerate -m "descricao"
```

Em produção, faça backup antes de migrations e teste restauração. O SQLite não é recomendado para múltiplos operadores gravando simultaneamente.

## Sessões longas

A aquisição persiste lotes, listagens têm limites rígidos e gráficos usam buckets SQL. Para volumes maiores, recomenda-se PostgreSQL com política de retenção, particionamento por tempo e backup/PITR conforme SLA.
