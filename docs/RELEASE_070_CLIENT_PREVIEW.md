# ThermoPower 0.7.0-client-preview

Candidata integrada para avaliação. Base: `e196671e41babd45981a8c0bd0fdf958cae7ab3f`,
branch master. Esta entrega não representa homologação física do AT4532.

## Análise e experiência

- Sessão organizada em identificação, período/indicadores e análise detalhada.
- Seleção por dois pontos ou alças no gráfico, região sombreada, duração,
  indicação de alterações pendentes, aplicar e cancelar próximos do trecho.
- Período oficial com resumo compacto, reutilização, alteração e remoção por
  admin/operator. Formulário de salvamento exibido somente quando solicitado.
- Eventos com tipo, horário, descrição e autor. Marcadores curtos agrupam eventos
  próximos; detalhes completos disponíveis no hover e na lista abaixo do gráfico.
- Compartilhamento em formulário expansível, permissões compactas, link copiável,
  status, prazo, acessos e revogação. Senhas e autorizações continuam no backend.
- Página pública com identidade ThermoPower, identificação do ensaio, período,
  KPIs, legenda das séries, canais, eventos e barra de downloads autorizados.
- Viewer com navegação dedicada a Sessões, Relatórios e Comparar sessões.
- Tabelas com rolagem interna, cabeçalho fixo, valores numéricos alinhados,
  controles com foco visível, suporte a tema claro/escuro e tamanhos de notebook/tablet.
- Cadência reduzida válida permanece nos detalhes; falhas reais continuam destacadas.

Os indicadores e exports continuam usando os serviços existentes e somente o período
aplicado. A seleção não altera amostras, não interpola nem preenche lacunas.

## Compatibilidade e persistência

Migrations `0009_session_analysis` e `0010_session_shares` preservadas. Nenhuma
migration nova. Sessões sem período oficial/eventos e links anteriores permanecem
compatíveis. A remoção do período oficial limpa somente seus cinco metadados.

A auditoria encontrou perda do offset de Brasília em metadados persistidos pelo
SQLite. Novos períodos oficiais e eventos agora são normalizados para UTC antes de
persistir, também em PostgreSQL. Registros anteriores não são reescritos automaticamente;
um período salvo anteriormente com horário incorreto deve ser conferido e salvo
novamente pelo responsável. Timestamps das medições permanecem intocados.

Compartilhamento usa o endereço pelo qual a instalação foi acessada. Localhost é
acessível apenas no próprio computador; acesso em rede depende da infraestrutura.
Limite de requisições públicas continua em memória por processo.

## Correções físicas herdadas

O core físico é herdado integralmente da base: framing TCP-32, retenção de parciais,
fila/recovered frames, deduplicação, polling, reconnect, recuperação independente
das fontes, associação segura, GPM-8213 e `prepare_common_start`. Nenhum comando,
parser, threshold ou estado físico foi alterado nesta rodada.

As ferramentas de caracterização permanecem no repositório de engenharia. Não estão
no executável cliente nem em seus menus; o launcher do produto não oferece entrada
para caracterização. O pacote não contém seed, banco demo, senhas demo, capturas
físicas ou scripts experimentais. O primeiro acesso gera credenciais localmente.

## Pendências e critérios de bancada

O GPM possui validação física anterior; esta rodada não executou hardware.
O AT4532 permanece pendente: a captura de 01/10 mostrou ausência de RX passivo,
um TCP-32 após Celsius e silêncio após FETCH apesar de intervalo pós-RX de 9,343 s.
Isso não estabelece Celsius como comando de aquisição. Repetição controlada de
Celsius pertence à investigação de engenharia separada.

Antes de homologar: resolver a pendência de aquisição contínua AT com evidência
real; então validar leitura/completo, 5 min AT, dez inícios combinados, 10 min com
contadores de ambas as fontes progredindo e soak físico de 30–60 min. Conferir
timestamp, frescor, lacunas reais, ausência de duplicação e recuperação preservando
sessão e histórico. Uma falha mantém o AT sem homologação.

## Instalação e identificação

Extrair o ZIP completo para uma pasta nova, preservando a instalação anterior.
Executar `ThermoPowerMonitor.exe`. Dados da instalação ficam no diretório local
do aplicativo, fora do pacote; manter backup antes de atualizar uma instalação.

`build-info.json` registra versão, commit-base, data UTC e `source_dirty`.
`SOURCE-SHA256.json` identifica os arquivos usados na candidata; `SHA256SUMS.txt`
permite verificar os arquivos extraídos. A candidata incorpora alterações locais
revisadas sobre a base; não houve push, tag ou GitHub Release nesta rodada.
