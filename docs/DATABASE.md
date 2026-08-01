# Banco de dados

## Estratégia

SQLite é o padrão local. PostgreSQL 17 é usado pelo Compose e recomendado para produção. SQLAlchemy mantém os modelos portáveis; Alembic aplica o esquema inicial.

## Entidades

- `users`: identidade, hash de senha, perfil e ativação;
- `devices`: identificação, conexão, protocolo e metadados;
- `channel_configurations`: 16 configurações por equipamento;
- `measurement_sessions`: ciclo de vida e contexto da coleta;
- `measurements`: timestamp, potência original/normalizada e qualidade;
- `temperature_measurements`: valor por medição/canal;
- `alert_rules` e `alert_events`: regra, cooldown e ocorrência reconhecível;
- `system_events`: trilha operacional;
- `reports`: auditoria de geração.

Índices compostos cobrem sessão+timestamp, medição+canal, equipamento+canal e evento+categoria. Exclusões em cascata são usadas nas relações de alto volume.

## Migrations

```bash
cd backend
alembic upgrade head
alembic revision --autogenerate -m "descricao"
```

Em produção, faça backup antes de migrations e teste restauração. O SQLite não é recomendado para múltiplos operadores gravando simultaneamente.

## Sessões longas

A aquisição persiste lotes, listagens têm limites rígidos e gráficos usam buckets SQL. Para volumes maiores, recomenda-se PostgreSQL com política de retenção, particionamento por tempo e backup/PITR conforme SLA.
