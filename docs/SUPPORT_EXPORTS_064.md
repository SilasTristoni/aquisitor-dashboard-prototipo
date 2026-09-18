# Suporte e exportações — 0.6.4-client-preview

## Evidência e causa reproduzida

Os anexos da sessão 16 foram lidos sem alteração. A planilha informa versão 0.6.3,
136 leituras elétricas, nenhuma térmica, potência média 116,4273994852941 W,
pico 778,14 W e energia 4,611226186549982 Wh. Os dois PDFs anexados são relatórios
técnicos; o PNG compacto já mostra os indicadores térmicos como “—”.

O renderizador executivo existente aceita sessões elétrica, térmica e combinada no
ambiente Python. O defeito reproduzido está no empacotamento: `thermopower.spec`
incluía `matplotlib.backends.backend_agg`, mas não `matplotlib.backends.backend_pdf`.
O PDF técnico usa ReportLab e gráficos PNG; o executivo PDF pede o backend PDF
dinamicamente ao Matplotlib. Por isso, o primeiro pode funcionar enquanto o segundo falha.

O executável anterior disponível neste host, 0.6.0, foi iniciado com banco isolado
e 136 amostras elétricas sintéticas. Sua API retornou HTTP 500 / “Erro interno
inesperado”; o log confirmou `ModuleNotFoundError: No module named
'matplotlib.backends.backend_pdf'`. O arquivo PYZ desse pacote contém Agg e não PDF.
A configuração de empacotamento da 0.6.3 mantém a mesma omissão. Isso comprova o
defeito, mas o log original do clique na sessão 16 não foi fornecido e não permite
atribuir categoricamente aquele evento histórico à mesma exceção.

A correção declara o backend PDF entre os módulos obrigatórios. O smoke Windows
passa a gerar, pelo executável, PDF/PNG executivos e PDF/XLSX técnicos nos três
tipos de sessão. Não basta a rota existir no OpenAPI. Gráficos, cálculos, protocolos,
parsers, aquisição serial e sincronização não foram modificados.

A reprodução local da planilha externa gerou PDF executivo de uma página e PNG,
mantendo média e energia com diferença inferior a 1e-9. Os três indicadores térmicos
continuam ausentes. Arquivos de cliente e artefatos dessa reprodução ficam fora do Git
e do pacote distribuído, em `build/session-16-review`.

## Logs e rastreabilidade

`app/core/observability.py` concentra contexto, sanitização e logs JSON por linha.
O launcher configura os handlers antes das migrations e os reinstala depois delas;
a API também configura logs na inicialização. O diretório padrão Windows é:

```text
%LOCALAPPDATA%\ThermoPower Monitor\logs\
  thermopower.log
  errors.log
```

A reconfiguração também reativa os loggers da aplicação desabilitados pelo
`fileConfig` do Alembic. Um teste em subprocesso reproduz a configuração real
e confirma que uma falha posterior do launcher chega ao `errors.log` com código
e traceback; antes da correção, esse arquivo ficava vazio.

Cada arquivo gira a 5.000.000 bytes, com cinco backups. `errors.log` recebe ERROR
e níveis superiores; o arquivo geral recebe INFO e superiores. É possível indicar
`THERMOPOWER_APP_DATA_DIR` para execução isolada, ou `THERMOPOWER_LOG_DIRECTORY`.
O processo de aquisição continua único, conforme a arquitetura já existente.

Os registros incluem timestamp ISO UTC, nível, categoria, versão, commit/build,
operação, endpoint sem query string, sessão/equipamento quando conhecidos, usuário
por ID, exception type e correlation_id. Exceções têm traceback somente no log.
Mensagens existentes de aquisição continuam disponíveis, agora no envelope JSON.

O middleware cria códigos `TP-EXP-…` para exportações e `TP-APP-…` para outras
requisições. Não confia em identificadores fornecidos pelo cliente. Em erro
inesperado, o mesmo código é devolvido no corpo e no cabeçalho `X-Correlation-ID`,
gravado nos logs e indexado em `system_events`. A interface oferece nova tentativa
e exportação do diagnóstico. Falhas de exportação não modificam as amostras.

A auditoria de exportação registra usuário por ID, sessão quando única, tipo,
início, conclusão, resultado, arquivo quando gerado e código. O registro `reports`
continua indicando sucesso/falha. Campos adicionais usam o JSON existente de
`system_events`; não há mudança de esquema nem migration nova. Filtros por código
usam expressões JSON SQLAlchemy portáveis para SQLite e PostgreSQL. Os eventos são
paginados e podem ser filtrados por período, nível, categoria, sessão e equipamento.

Se o banco não puder registrar a auditoria, os arquivos de log conservam a falha;
essa contingência também é registrada. Rotação limita a retenção local: exportar
o diagnóstico logo após o problema evita perder registros antigos.

## Pacote de suporte

`GET /api/v1/support/package` exige autenticação. Aceita `session_id` e
`correlation_id`, mas funciona sem sessão ativa. Consultar os estados não abre,
fecha nem transmite comandos nas portas seriais. Uma consulta de estado que falha
é registrada como indisponível, sem impedir a exportação das outras fontes.

```text
ThermoPower-Diagnostico-AAAAMMDD-HHMMSS.zip
  README.txt
  build-info.json
  error-summary.json
  logs/thermopower.log
  logs/errors.log
  system/runtime.json
  hardware/devices.json
  hardware/acquisition-summary.json
  session/session-summary.json
```

São incluídos até 2 MB recentes de cada log, considerando os backups, até cem
erros relacionados e resumos das fontes. A seleção de campos permite modelo,
porta, protocolo, parâmetros seriais não sensíveis, estado, contagens, cadência,
timeouts e reconexões. Exclui o banco, documentos, séries brutas, cadastro de
usuários e metadados livres do ensaio. Nome da máquina e variáveis de ambiente
não são exportados.

A sanitização é aplicada antes da gravação e novamente ao montar o ZIP: chaves
de senha/token/segredo/credencial, Bearer, JWT, credenciais em URLs, e-mails,
perfil de usuário em caminhos Windows e valores de segredos configurados no
ambiente são redigidos. A identificação operacional usa IDs. O ZIP preserva o
formato JSON dos logs atuais e também aceita logs antigos em texto.

## Operação e documentação

Ajuda oferece Guia do usuário, Sobre o ThermoPower e Exportar diagnóstico.
Sobre identifica versão, build, ambiente e data. A orientação inicial em quatro
passos pode ser dispensada permanentemente no navegador. Eventos apresentam o
resumo humano antes dos detalhes técnicos recolhidos.

`docs/MANUAL_USUARIO.md` contém os 31 tópicos solicitados para o operador.
`scripts/build-user-guide.py` gera o PDF de cinco páginas. O empacotador inclui
`Manual do Usuário - ThermoPower Monitor.pdf` na raiz e a cópia servida por Ajuda.
O smoke verifica o download autenticado do manual e a abertura do ZIP de suporte.

## Baseline e verificações

Antes de alterar código: 161/162 testes de backend e 63/64 do subconjunto físico
passaram; ambos falharam na mesma comparação de 6000 ms com 6000,001 ms. A fixture
chamava o relógio real seis vezes. Agora usa uma única origem para produzir seis
intervalos exatos; não houve alteração na medição da cadência do produto.
Frontend: 35 testes, lint, TypeScript e build aprovados.

A nova cobertura inclui as três combinações de fontes, arquivo PDF/PNG válido,
código de erro rastreável em evento/log/ZIP, persistência da sessão após erro,
autenticação do suporte, diagnóstico sem sessão, rotação, sanitização, ajuda,
filtros e nova tentativa. A build usa banco isolado para Alembic upgrade/check e
preserva pacotes anteriores, recusando sobrescrever uma versão já existente.

Os resultados finais de empacotamento e o SHA-256 são registrados após os gates.
A homologação física anterior permanece como referência; esta rodada não executa
um novo ensaio com instrumentos reais.
