# ThermoPower 0.7.1 r4 — gráficos e atualização Windows

Base: branch `feat/product-experience-071`, r3 `2c0c076e910da0b2b6911a8eed78b616ac4502e1`.
O usuário indicou **o pacote Windows r3** como referência para a comparação visual.
Não foi identificado outro commit como visual aprovado pela Britânia.

## Correções e evidências

- Um separador de lacuna de um termopar podia interromper a linha de outro canal:
  a filtragem por fonte incluía linhas sem aquela propriedade. Cada curva agora
  usa apenas suas próprias coordenadas, preservando `null` explícito como lacuna.
  O teste renderiza SVG real do Recharts e verifica a continuidade, inclusive 0 W real.
- A referência tracejada de indisponibilidade podia ultrapassar o eixo horizontal:
  os extremos dos segmentos `ReferenceLine` não compunham o domínio dos dados.
  O gráfico ao vivo agora inclui explicitamente as coordenadas dessa camada no eixo.
  Essa camada não é uma medição, não cria leituras e não participa de indicadores,
  armazenamento, CSV, XLSX ou cálculos de energia.
- Eventos próximos são agrupados com espaço para os marcadores também no mobile.
  Detalhes permanecem no tooltip e nas listas; eventos observados ao vivo ficam em
  painel expansível. As duas legendas textuais por lacuna foram removidas de dentro
  das curvas; os intervalos completos ficam em painel próprio nas sessões e links.
- Tempo real, sessões, relatório por período e página compartilhada usam a mesma
  regra de seleção de série. Layout, identidade corporativa e controles r3 preservados.

As mudanças não demonstram a causa de toda fragmentação relatada em campo. Os testes
usam dados sintéticos; não foram consultados bancos ou ensaios reais da Britânia.

## Interpretação dos dados

Potência medida continua azul. Uma desconexão confirmada observada na tela pode
gerar referência cinza tracejada em 0 W, expressamente identificada como não medida.
Timeout isolado, atraso ou dado ausente não criam essa referência. O retorno exige
nova leitura real; temperaturas não são preenchidas com zero.

O histórico e os documentos não dispõem de intervalos de desconexão certificados
no contrato atual. Nesses casos preservam lacunas e não inventam horários de falha
ou zeros. Eventos vistos somente durante a abertura do Tempo real não são convertidos
em eventos persistidos. Assim, reabrir uma sessão não reconstitui essa observação.
As referências visuais não são exportadas como amostras. PDFs/imagens preservam o
renderizador existente, os segmentos reais e as tabelas de eventos; nenhuma alteração
de cálculo ou exportação foi feita nesta revisão.

## Investigação dos registros mencionados

- `ResolutionError ... 0013_company_identity`: executável antigo não conhece a
  revisão adicionada na r2. Não é evidência de perda de sessões. Não apagar nem
  editar `alembic_version`, não executar downgrade manual.
- Identificação GPM e exportação não concluída: o `errors.log` não foi fornecido
  com o pedido nem faz parte do pacote Windows preservado. Causas permanecem
  indeterminadas. Nenhum driver/protocolo ou exportador foi alterado por hipótese.
  As regressões automatizadas e o smoke de exportação constam no relatório de entrega.

## Atualização segura

1. Encerre o ThermoPower e confirme o encerramento de todas as instâncias, inclusive
   DEMO se apontar por engano para o mesmo banco. Nunca troque o banco por um DEMO.
2. Identifique o caminho efetivo: `THERMOPOWER_DATABASE_URL` prevalece; sem ela,
   `THERMOPOWER_APP_DATA_DIR/data/thermopower.db`, ou
   `%LOCALAPPDATA%/ThermoPower Monitor/data/thermopower.db`.
3. Com o aplicativo fechado, preserve cópia completa dos dados e configurações,
   relatórios e arquivos de acesso. Se houver WAL/SHM, preserve o conjunto completo;
   não copie apenas o arquivo principal de um banco aberto.
4. Preserve pastas e ZIPs r2/r3 e extraia a r4 em outra pasta. Use o mesmo usuário
   Windows e a configuração de dados desejada.
5. Antes de qualquer migration SQLite pendente, o launcher r4 verifica a revisão,
   integridade e espaço livre (duas vezes banco + WAL, mais 64 MiB). Faz backup
   consistente pela API SQLite, incluindo WAL confirmado, em `migration-backups`
   ao lado do banco. Verifica a cópia e grava manifesto com SHA-256 e revisões.
   Falha de backup, espaço ou revisão desconhecida impede a migration.
6. Nenhuma migration nova foi adicionada: a revisão continua `0013_company_identity`.
   Bancos r2/r3 nessa revisão não são migrados. O backup manual da etapa 3 continua
   necessário para retorno operacional, mesmo sem mudança de esquema.
7. Confira login, sessões e uma exportação antes de retomar ensaios reais.

PostgreSQL: o launcher não tenta fazer cópia de arquivos do servidor. Havendo migration
pendente, bloqueia a atualização automática e exige procedimento administrativo:
backup nativo consistente (`pg_dump`), verificação/restauração de teste, espaço livre
no destino e servidor, aplicação controlada das migrations, conferência de sessões
e exportações. Banco já atualizado segue aceito. A proteção desta revisão se aplica
ao launcher Windows; execução direta de Alembic continua sendo operação administrativa.

## Rollback sem perda de ensaios

R2, r3 e r4 compartilham a revisão 0013. Feche a r4, preserve cópia de seus dados e
retome r3/r2 com o mesmo banco somente após o backup. Não execute duas versões juntas.

Para 0.7.0 ou outra versão que não conhece 0013, restaure **um backup anterior e
compatível em pasta separada**, mantendo intacto o banco atualizado. Se houve novos
ensaios depois daquele backup, eles permanecem no banco atualizado e devem continuar
acessíveis pela r4/r3. Não substitua o banco atualizado pelo backup nem descarte dados
posteriores. Uma fusão de bancos não é automatizada. Reconcilie publicações posteriores
ao backup antes de retomar administração de links. Sem backup compatível, mantenha
a versão atual: não altere manualmente a revisão para forçar a versão antiga.

## Preservação e limites

Aquisição AT4532/GPM, parsers, recuperação serial, armazenamento de medições, cálculos,
permissões, credenciais, publicação e regras de compartilhamento permanecem preservados.
Operadores autorizados continuam publicando resultados; configuração administrativa
do portal continua restrita a administradores. DEMO permanece isolado.

O pacote Windows não contém credenciais predefinidas do Render. Configurações anteriores
podem ser reutilizadas quando presentes no cofre do mesmo usuário Windows.

Sem push, merge, deploy ou release pública. A homologação física continua pendente
de bancada. Logs originais e confirmação visual da usuária permanecem pendentes.
Evidências e resultados finais: `build/integrated-r4/DELIVERY.md`.
