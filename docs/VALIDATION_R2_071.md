# Validação da candidata integrada r2

## Código e escopo

- Backend: `company_routes.py`, `company_identity.py`, migration 0013 e registro
  do router em `main.py`; incorporação de identidade em PDF e opt-in congelado nos
  compartilhamentos. `alembic/env.py` suporta os identificadores históricos longos
  em PostgreSQL. Contrato do portal aceita somente a identidade opcional validada.
- Frontend: configuração/identificação corporativa, autorização por compartilhamento,
  viewer, apresentação de eventos por fonte e layout responsivo.
- Ferramentas: DEMO isolado, seed complementar, revisão visual, testes sem acesso
  externo e empacotamento r2 sem sobrescrever a candidata anterior.
- Testes: identidade/isolamento, eventos visuais, migrations e expectativas atualizadas
  de versão. Nenhuma correção de revogação baseada na suspeita retirada.

## Resultados antes do empacotamento

- Backend completo: 434 casos executados; 430 passaram na primeira execução.
  Quatro expectativas antigas falharam (versão/ambiente/migration). Após corrigir
  somente os testes, os casos físicos afetados passaram na reexecução do arquivo;
  os cinco testes finais de migrations passaram, incluindo a nova regressão real
  de PostgreSQL. Cobertura final: 435 casos distintos aprovados no conjunto das execuções.
- Frontend: 83 testes; lint, TypeScript e build aprovados.
- Portal independente: 39 casos com SQLite/PostgreSQL; quatro testes frontend;
  lint, TypeScript, build e integração sintética no navegador aprovados.
- Visual: 90 combinações de cenários e larguras 1440/768/390 px; sem overflow
  horizontal ou erros de página. Telas de empresa, pausa e indisponibilidade
  repetidas após ajustes. Capturas em `build/integrated-r2/audit`.
- DEMO: dez sessões determinísticas; nove exportações PDF/XLSX/CSV; lacuna sem
  amostras elétricas artificiais; quatro eventos distintos de desconexão/reconexão.
  Instância HTTP validada com banco próprio e publicação desabilitada.
- Migrations: instalação, downgrade 0013→0012 e upgrade em SQLite e PostgreSQL,
  preservando histórico sintético; identidade persistida nos dois bancos.
- Ruff e `docker compose config --quiet` aprovados. Auditoria do portal sem achados.

O relatório local de entrega complementa estes resultados com smoke do executável,
validação dos arquivos extraídos, manifesto e SHA-256 do ZIP.

## Comparação com o core físico

Adapters, transporte, parser, aquisição, engine Celsius e launcher Windows sem
alterações. A comparação de hashes registra 27 entradas idênticas entre 31; as
quatro diferenças correspondem a `main.py` (repetido em duas referências, somente
registro do router), `period_reporting.py` e `period_documents.py` (marca corporativa).
Não houve acesso a equipamentos nem homologação física.

## Riscos e compatibilidade

A tabela 0013 não altera medições nem relatórios existentes. Em PostgreSQL, somente
o controle do Alembic é ampliado para suportar revisões históricas. O rollback exige
executável anterior e backup anterior à migration; não abrir o banco 0013 com o
executável antigo. Eventos visuais são observados enquanto a tela está aberta.
O logotipo oficial da Britânia permanece pendente de fornecimento/autorização.
Render precisa ser atualizado para snapshots com marca; não houve deploy.

Evidências locais: `build/integrated-r2/`. Avisos de depreciação de dependências e
aviso de tamanho de bundle do viewer não impediram a validação.
