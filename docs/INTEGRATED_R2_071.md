# ThermoPower 0.7.1 — candidata interna integrada r2

Inclui identidade corporativa administrativa, opt-in de marca no compartilhamento,
DEMO isolado por scripts e apresentação explícita de indisponibilidade das fontes.
Não representa homologação física. Estabilidade contínua e recuperação na bancada
Britânia continuam pendentes.

## Banco efetivamente utilizado

O processo Windows PID 23640 que atendia 127.0.0.1:8765 foi identificado pelo listener.
Seu ambiente e a lista de arquivos abertos confirmaram:
`C:\Users\Silas\AppData\Local\ThermoPower Monitor\data\thermopower.db`.
Evidência local: `build/integrated-r2/active-database.json`.
O banco de aproximadamente 335 MB em Documentos não foi aberto nem alterado.
Não foi inferida a quantidade de registros do banco ativo.

O launcher usa `THERMOPOWER_APP_DATA_DIR` ou `%LOCALAPPDATA%\ThermoPower Monitor`.
`THERMOPOWER_DATABASE_URL` explícita prevalece; sem ela, usa `data\thermopower.db`
nesse diretório. Não procura nem importa automaticamente o banco de Documentos.
O modo client-preview não troca esse caminho. Ao iniciar, aplica migrations ao
banco selecionado; um banco existente nesse caminho é reutilizado.

## Compatibilidade e atualização Windows

1. Feche a instância normal e confirme que seu processo terminou.
2. Faça backup do diretório de dados efetivamente usado, com o aplicativo fechado,
   incluindo banco, configurações, relatórios e arquivos de acesso. Guarde o backup
   em local protegido. Não substitua nenhum banco por arquivos DEMO.
3. Preserve a pasta e o ZIP da candidata anterior. Extraia a r2 em outra pasta.
4. Inicie a r2 com as mesmas variáveis de ambiente e o mesmo diretório de dados.
5. A migration `0013_company_identity` adiciona somente uma tabela de identificação.
   Não transforma nem exclui medições, sessões ou relatórios. Compatível com SQLite
   e PostgreSQL. Sem marca configurada, mantém apresentação neutra.
   Em PostgreSQL, o controle `alembic_version.version_num` é ampliado para 128
   caracteres antes de executar a cadeia: o identificador histórico da migration
   0006 já excedia os 32 caracteres padrão. Não altera tabelas de aquisição.
6. Confira login, sessões e uma exportação antes de iniciar uma aquisição real.

## Rollback

Feche a r2, preserve uma cópia de seus dados e retome o executável anterior usando
o backup feito antes da atualização. Não sobreponha banco aberto. A candidata
anterior não conhece a revisão Alembic 0013; não a aponte diretamente para o banco
migrado. O backup restaura também o estado de compartilhamentos daquele momento:
reconcilie publicações feitas após o backup antes de usar controles administrativos.
Não execute downgrade destrutivo sobre dados reais como procedimento rotineiro.

## Integridade e limites

O traço cinza de indisponibilidade elétrica é exclusivo da apresentação: não gera
Reading, POST, amostra, média, pico ou energia. A curva medida é segmentada nos
eventos observados; reconexão depende de nova leitura com timestamp posterior.
Pausa e falha temporária são distintas. Temperatura indisponível permanece como
referência histórica, nunca como 0 °C. Os marcadores desta camada são observados na
tela aberta; não substituem os eventos persistidos pelo backend, nem reconstituem
eventos anteriores ao carregamento da página.

Protocolos, parsers, engine Celsius, recuperação e comandos físicos permanecem
preservados. Não houve correção de revogação motivada pela suspeita retirada.
O portal precisa de atualização somente para os snapshots com identidade; não foi
feito deploy, push, merge, tag ou release pública.

Consulte `CORPORATE_IDENTITY_071.md` e `DEMO_INSTANCE_071.md` para operação.
Resultados e limitações da validação estão no relatório local de entrega e em
`VALIDATION.json` do pacote. O pacote não contém bancos ou credenciais DEMO/clientes.
