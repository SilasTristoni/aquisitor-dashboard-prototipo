# Plano de integração AT4532 + GPM-8213

## Objetivo

Evoluir o ThermoPower Monitor sem substituir a arquitetura existente, permitindo que uma sessão associe, de forma independente, um Applent AT4532 (até 32 termopares) e um GW Instek GPM-8213 (grandezas elétricas).

## Compatibilidade

- As tabelas `measurements` e `temperature_measurements` permanecem disponíveis para sessões e clientes legados.
- As novas tabelas separam amostras térmicas e elétricas e preservam timestamps do equipamento e de recebimento.
- Sessões existentes são associadas ao equipamento original e seus dados são copiados para as estruturas novas pela migração, sem remoção dos dados de origem.
- SQLite e PostgreSQL são suportados pela mesma migração Alembic.

## Entregas

1. Modelos, contratos e migração para dois equipamentos, amostras separadas, 32 canais e snapshot da configuração.
2. Importadores com pré-visualização e confirmação para TXT do GPM-8213 e XLSX do AT4532.
3. Sincronização por vizinho temporal mais próximo, grade padrão de 1 s e tolerância configurável de até 3 s.
4. APIs e interface para configurar sessões, importar arquivos e visualizar série combinada em dois eixos.
5. Exportação e diagnóstico Windows, testes automatizados e documentação operacional.

## Limitação de homologação

O diretório `reference-input/` disponibilizado está vazio. Os parsers serão validados com fixtures sintéticas e regras configuráveis, sem inferir comandos SCPI. A homologação final de layouts e comunicação física depende dos arquivos de amostra e manuais reais.
