# ThermoPower 0.7.1 r3 — ajuste pontual de interface

Base: `8206d746`, candidata integrada r2. A r2 anterior é preservada.

## Alterações

- Identidade corporativa: campos em duas colunas no desktop e uma no mobile;
  botão Salvar identificação com largura natural em linha própria; seção de
  logotipo separada, seletor de arquivo estilizado e foco acessível; prévia delimitada.
- Tempo real: seletores e ações agrupados, controles de 44 px e alinhamento pela
  base; grupo abaixo do título no notebook, empilhado no mobile.
- Portal externo: largura de formulário limitada, campos de 44 px e status agrupado;
  textos explicam a origem da configuração sem expor credenciais.

Arquivos de interface: `frontend/src/pages/CompanyIdentityPage.tsx`,
`frontend/src/pages/DashboardPage.tsx`, `frontend/src/components/PortalConfiguration.tsx`
e `frontend/src/styles.css`. O teste visual `scripts/review-integrated-ui.mjs`
aceita resoluções/fixture configuráveis e verifica dimensões, alinhamento e foco do upload.

Nenhuma alteração de backend, aquisição AT4532/GPM, parsers, protocolos, persistência,
cálculos, lógica de compartilhamento ou credenciais. Não há nova migration.

## Validação

83 testes frontend aprovados; lint, typecheck e build aprovados. Comparação visual
antes/depois: identidade, portal e três estados de tempo real em 1366×768,
1920×1080 e 390×844. Quinze cenários depois da alteração, sem overflow horizontal
ou erros de página. Botão Salvar abaixo de 240 px, controles de fonte com 44 px e
mesma base no desktop/notebook; upload acessível pelo teclado.

Evidências locais: `build/integrated-r3/`, com `comparison.html`, capturas em
`before/` e `after/`, resultados JSON e logs frontend. O relatório de entrega
complementa com o smoke Windows, tamanho, commit e SHA-256 do pacote final.

## Portal e credenciais Windows

**O pacote Windows não contém credenciais predefinidas do Render.** Instalação,
URL e credencial podem vir de configuração explícita do ambiente; sem essa
configuração, o aplicativo consulta o Gerenciador de Credenciais do Windows.
Configurações anteriores podem ser reutilizadas quando presentes no cofre do
**mesmo usuário Windows** que executa o ThermoPower. Extrair um novo ZIP não apaga
esse cofre. Em outro usuário ou computador, pode ser necessário configurar novamente.
Nenhuma credencial armazenada é exibida pela interface.

Não houve push, deploy ou release pública. Esta revisão de layout não exige nova
atualização do portal; a dependência de atualização para snapshots corporativos,
documentada na r2, permanece aplicável se aquela atualização ainda não foi feita.

## Instalação e retorno à r2

Feche o ThermoPower e preserve o backup do diretório de dados. Extraia a r3 em pasta
separada, mantendo a pasta/ZIP r2. Use o mesmo diretório de dados/configuração.
Como não há migration nova em relação à r2, pode voltar ao executável r2 após
fechar a r3. Para versões anteriores à r2, siga o procedimento de backup/rollback
em `INTEGRATED_R2_071.md`. A homologação física permanece pendente de bancada.
