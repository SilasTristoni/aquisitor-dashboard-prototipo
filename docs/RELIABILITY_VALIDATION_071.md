# Validação de confiabilidade — 12/11/2026

Base funcional: r5 `aef2b6fa2031a6780a9768bd876898124505d5a3`, versão
`0.7.1-engineering`. Integração em `integration/reliability-071`, originada da
master `862c8ce1`. Auditoria: `BRANCH_CONSOLIDATION_071.md`.

## Resultados

- Backend completo: **456 casos**, 452 aprovados e quatro falhas iniciais, em
  509,39 s. As falhas expuseram contenção do supervisor ocioso: latência, restauração
  da capacidade SQLite em duas fontes e consulta de relatório do DEMO.
- Após corrigir o supervisor ocioso: **93 regressões aprovadas**, em 146,39 s,
  incluindo todos os quatro casos, recuperação, fontes independentes, integridade,
  fechamento/reinício, perda de posse, indisponibilidade e 11 casos recuperados do stash.
- União dos casos aprovados das duas execuções: **469 testes backend distintos**.
  Não é uma única execução completa com 469 aprovações. Os XMLs permitem verificar
  que nenhum caso com falha ficou sem uma execução posterior aprovada.
- PostgreSQL isolado: migration até `0015_session_recovery`, backup administrativo
  obrigatório e exclusão/reliberação do advisory lock aprovados. A tentativa inicial
  usou usuário incorreto do cluster antigo; a execução válida usou cluster sintético
  novo, local, sem bancos de cliente.
- Frontend: suíte de 90 casos e regressões específicas do portal/recuperação. Os
  testes de autorização do portal isolam o novo aviso, que tem testes próprios.
- Lint, typecheck, build, build do viewer, Ruff, Compose config e diff check aprovados.
- Capturas reais da aplicação com API/WS sintéticos: recuperação, identidade e portal
  em 1366×768, 1920×1080 e 390×844; 12 cenários adicionais de tempo real, histórico,
  relatório e compartilhamento com duas desconexões GPM. Sem overflow ou erro de página.
  Inspeção visual do aviso desktop/mobile confirmou ações e confirmação legíveis.

Logs/JUnit/capturas: `build/reliability-consolidation/`.

## Carga acelerada

O script `scripts/validate-extended-acquisition.py` cria banco sintético novo e usa
o gravador real, com timestamps elétricos a 1 s, térmicos a 5 s e 32 canais, incluindo
um canal aberto. Injeta lotes limitados para acelerar o tempo; não executa 24 horas
de relógio nem acessa portas. Os relatórios são gerados em worker como nos handlers
síncronos da API.

| Métrica | 20 horas | 24 horas |
| --- | --- | --- |
| Leituras elétricas confirmadas | 72.000 | 86.400 |
| Leituras térmicas confirmadas | 14.400 | 17.280 |
| Valores de canais | 460.800 | 552.960 |
| Maior lote combinado observado | 120 | 120 |
| Tempo de gravação acelerada | 40,31 s | 47,61 s |
| Reabertura, integridade e identificação recuperável | 0,68 s | 0,81 s |
| Consulta de relatório | 10,04 s | 12,28 s |
| Prévia | 0,46 s | 0,57 s |
| Pontos totais na prévia | 2.619 | 2.619 |
| Série sincronizada limitada a 600 pontos | Regra coberta por testes | 7,85 s |
| PDF + PNG | 11,09 s | 17,94 s |
| RSS após gravação | 120,46 MB | 120,43 MB |
| Pico RSS amostrado, incluindo relatórios | 474,45 MB | 512,67 MB |
| CPU do processo, todas as etapas | 50,67 s | 73,33 s |
| Banco ao final | 57.896.960 bytes | 69.476.352 bytes |
| Maior intervalo do monitor do event loop, incluindo exportação | 0,69 s | 0,82 s |

O primeiro cenário de 20 h expôs pico de 1.156,69 MB ao materializar todos os objetos
ORM; após leitura em lotes, a execução completa, incluindo PDF/PNG, ficou nos valores
acima. O script inicial também precisou registrar o modelo de identidade corporativa
antes de criar seu banco isolado; a falha desse primeiro script não é apresentada
como exportação aprovada. Artefatos válidos estão em `extended-20-validated/` e
`extended-24/`, cada um com `metrics.json`, PDF, PNG e prévia.

A janela do frontend é limitada a 600 mensagens e a série sincronizada mantém
amostras vizinhas em cursor progressivo. Relatórios mantêm cópias dos valores
selecionados em memória, portanto continuam dependendo de volume e concorrência.
Esses tempos medem esta máquina e carga; não são garantias de tempo real físico.

## Preservação e limites

Comparação com r5: nenhum diff em `backend/app/adapters/`,
`services/acquisition.py`, `services/pending_persistence.py`, `services/storage_health.py`
ou `legacy/`. Foram incorporadas à master as correções físicas já existentes nas
branches, sem nova mudança de protocolo, parser, SCPI, COM, cadência ou reconexão.
`services/synchronization.py` é somente a consulta de apresentação; os testes
comparam a seleção por proximidade, tolerância e empate com a regra anterior.

Hashes de r2/r3/r4/r5 conferidos e preservados. Nenhum banco real da Britânia,
credencial ou configuração de produção foi acessado. Não há nova tag, mudança de
versão comercial ou deploy do portal. A branch USB virtual antiga permanece fora
da consolidação por incompatibilidade documentada; as branches e o stash permanecem.

Morte forçada do processo foi exercitada em subprocessos reais com banco temporário,
duas retomadas, mesmo identificador/início, sequências únicas e valores anteriores
preservados. Isso não prova recuperação de RAM nem comportamento de queda elétrica.
Estabilidade física de 20–24 h, energia real interrompida, drivers e equipamentos
continuam pendentes de homologação em bancada.

Atualização, operação, exclusão por banco e rollback: `SESSION_RECOVERY_071.md` e
seção 32 de `MANUAL_USUARIO.md`. O build/smoke Windows, commit final e estado local/
remoto da master são registrados no relatório de entrega em
`build/reliability-consolidation/DELIVERY.md` após a conclusão desses passos.
