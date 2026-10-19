# Portal no Render — preparação da integração 0.7.1

Preparado em 19/10/2026. **Sem deploy, contratação, push, merge, tag, release ou ZIP.**
Usar inicialmente somente dados sintéticos. Não publicar dados da Britânia.
Este guia substitui a configuração de chave global descrita na primeira implementação.

## Arquitetura

1. O aplicativo Windows mantém aquisição e banco local. Admin/operator publica somente
   uma sessão finalizada com período oficial salvo, canais e potência selecionados.
2. O backend reutiliza a coleta e os geradores de relatórios existentes. Monta snapshot v1
   com projeção pública, curvas reduzidas, estatísticas e apenas os documentos autorizados.
   Não envia SQLite, usuários, dispositivos, portas, payloads seriais ou API operacional.
3. Antes do HTTPS, salva o snapshot autorizado e UUID da solicitação em campos exclusivos
   de compartilhamento. Falha/perda de confirmação deixa um registro pendente revogável.
   Reenviar usa os mesmos bytes, token, validade, senha e filtros, mesmo que a sessão mude.
4. A API isolada do portal autentica a instalação, grava snapshot e documentos no PostgreSQL
   e retorna a origem pública, caminho e hash do identificador. O backend local acrescenta
   o token ao fragmento e devolve a URL HTTPS pronta para copiar.
5. O site estático público consulta somente a API do portal. CORS aceita sua origem exata,
   sem cookies. Depois de publicado, o resultado independe do computador do laboratório.

Entradas: `app.portal.application:create_app` e `frontend/portal.html`.
**Nunca hospedar `app.main:app`, o frontend operacional ou o SQLite local no Render.**
Não há túnel, abertura de porta do laboratório, Redis, worker ou sincronização automática.

## Serviços, custos e limites

Modelo: [deploy/results-portal/render.yaml](../deploy/results-portal/render.yaml).
Um Web Service Python `0.5c-512mb`, um Static Site e um PostgreSQL
`0.1c-256mb`, 1 GB inicial, mesma região da API. Região proposta: Virginia;
confirmar localização e requisitos de dados antes de criar recursos.
Sem autoscaling, previews ou outros recursos que exijam workspace Pro.
Auto-deploy está desligado; aplicar um Blueprint **ainda cria e cobra** os serviços.

Referência consultada em 19/10/2026: API a partir de US$ 7/mês e PostgreSQL a partir
de US$ 6/mês; site estático e workspace Hobby sem mensalidade básica. Estimar cerca de
US$ 13/mês de computação, mais armazenamento excedente, tráfego/builds excedentes,
tributos/câmbio e eventual domínio. Confirmar o orçamento exibido no Dashboard;
nenhum valor representa contratação. Fontes: [preços](https://render.com/pricing),
[guia de custos](https://render.com/articles/how-much-does-cloud-application-hosting-cost-for-small-businesses).

PostgreSQL Free expira em 30 dias; não atende retenção duradoura. Web Service Free
tem suspensão por inatividade e pode exceder o timeout de publicação no primeiro acesso.
Usar Free apenas para avaliação descartável sintética, sem prometer disponibilidade.
[Limitações oficiais](https://render.com/docs/free).

Snapshots e documentos ficam no banco, não no disco efêmero do Web Service.
Há limite de 25 MiB por snapshot, 4 KiB para comandos públicos/políticas e
15 s de leitura do corpo. O serviço inicia com um worker e concorrência 4;
dimensionamento, retenção e carga real ainda precisam de aceite.

## Variáveis e segredos

| Local | Variável | Conteúdo |
| --- | --- | --- |
| API | `THERMOPOWER_PORTAL_DATABASE_URL` | Connection string **interna** do PostgreSQL exclusivo |
| API | `THERMOPOWER_PORTAL_INTEGRITY_KEY` | Segredo aleatório independente com pelo menos 32 caracteres; Blueprint gera |
| API | `THERMOPOWER_PORTAL_INSTALLATIONS` | JSON de instalações, empresas, SHA-256 das credenciais e estado enabled |
| API | `THERMOPOWER_PORTAL_PUBLIC_ORIGIN` | Origem HTTPS exata do **site estático**, sem caminho ou barra final |
| API | `PYTHON_VERSION` | Versão fixada no Blueprint |
| API | `PORT` | Injetada pelo Render; não definir manualmente |
| Build estático | `VITE_PORTAL_API_ORIGIN` | Origem HTTPS exata da **API**, sem caminho ou barra final; não é segredo |
| Windows, alternativa por ambiente | `THERMOPOWER_RESULTS_PORTAL_URL` | Origem HTTPS da API |
| Windows, alternativa por ambiente | `THERMOPOWER_RESULTS_PORTAL_INSTALLATION_ID` | ID exclusivo da instalação |
| Windows, alternativa por ambiente | `THERMOPOWER_RESULTS_PORTAL_PUBLISH_KEY` | Credencial aleatória daquela instalação |

Não usar a antiga `THERMOPOWER_PORTAL_PUBLISH_KEY`: a chave global não autentica o portal
atual. JWT, senhas de usuários e credenciais do laboratório não pertencem ao portal.
As URLs `postgres://` e `postgresql://` do Render são normalizadas para psycopg 3.

Formato de registro (marcadores, não valores operacionais):

```json
{
  "installation-id": {
    "tenant_id": "company-id",
    "credential_sha256": "<SHA-256 hexadecimal de 64 caracteres>",
    "enabled": true
  }
}
```

Gerar uma credencial de 32 bytes aleatórios em um cofre aprovado, codificada em base64url
sem padding (43 caracteres). Guardar a credencial no cofre administrativo e no Windows;
somente seu SHA-256 vai ao registro do portal. Para calcular o registro sem incluir
o segredo na linha de comando/histórico, executar localmente:

```powershell
python scripts/portal-installation-record.py --tenant company-id --installation installation-id
```

O script solicita a credencial com entrada oculta e imprime apenas IDs/hash.
Adicionar uma entrada por instalação no JSON existente; não sobrescrever as outras.
A empresa é determinada pela configuração autenticada do servidor, nunca pelo payload.
Mesmo instalações da mesma empresa não podem administrar publicações umas das outras.

Rotação: manter os IDs, substituir o hash no Render e o segredo no cofre Windows;
os links continuam válidos. `enabled: false` bloqueia novas operações administrativas,
mas não revoga automaticamente links já distribuídos. Revogar os resultados pelo operador
antes de desativar a instalação quando esse for o objetivo. Não trocar a chave de integridade
sem migração/reassinatura planejada: fazê-lo torna snapshots existentes indisponíveis.

## Passo a passo — somente após aprovação de implantação e custo

1. Aprovar serviços, orçamento, região, retenção e responsável. Revisar o checkpoint local.
   Disponibilizar a branch no provedor Git somente quando o push também for autorizado.
2. No Render, manter workspace Hobby. Criar um Blueprint apontando para
   `deploy/results-portal/render.yaml`, na branch aprovada. Escolher nomes únicos antes
   de aplicar; nomes existentes podem atualizar serviços existentes.
3. Preencher os três valores `sync: false`: registro de instalações, origem pública do
   viewer e origem da API para o build estático. Usar os subdomínios reais atribuídos
   pelo Render, não presumir disponibilidade dos nomes sugeridos.
   Se as URLs ainda não forem conhecidas, criar os serviços manualmente com os comandos
   do YAML, obter suas URLs e configurar ambas as origens antes do build final do viewer.
   Valores provisórios não tornam o sistema pronto para uso.
4. Conferir os planos e cobrança apresentados antes de aplicar. A API usa o connection
   string interno referenciado pelo Blueprint; o PostgreSQL tem `ipAllowList: []`,
   desabilitando acesso externo ao banco. Não apontar para banco de aquisição.
5. Conferir o pre-deploy `cd backend && python -m alembic -c portal-alembic.ini upgrade head`.
   Em configuração manual, usar exatamente esse comando antes de iniciar a API.
   A migration do portal é independente da migration da instalação.
6. A API escuta `0.0.0.0:$PORT`, com logs de acesso desligados e sem confiar em headers
   de proxy arbitrários. Health check `GET /health` verifica banco e colunas migradas.
   O Render termina HTTPS; conferir certificado e ausência de redirecionamentos na URL
   exata da API. O cliente recusa redirects para não transferir sua credencial.
7. O site estático publica **somente `frontend/dist-portal`**, gerado por
   `npm ci && npm run build:portal`. Configurar rewrite de `/compartilhado` para
   `/portal.html` e os headers do Blueprint. Alterar `VITE_PORTAL_API_ORIGIN` exige
   novo build. HTTPS é fornecido pelo Render para ambos os serviços.
8. Verificar `THERMOPOWER_PORTAL_PUBLIC_ORIGIN` = origem do viewer. O teste CORS deve
   aceitar apenas essa origem; a publicação por máquina usa Authorization e não CORS.
9. Aplicar a migration local 0012 com backup prévio: `cd backend; python -m alembic upgrade head`
   no ambiente autorizado da instalação. Não aplicar essa migration ao banco do portal.
10. Configurar o Windows conforme a próxima seção; executar o aceite sintético abaixo.
    Só então decidir sobre uso externo com dados autorizados.

O YAML foi preparado para validação estrutural pelo
[schema oficial](https://render.com/schema/render.yaml.json).
Isso não substitui a validação do Dashboard, o build Linux e os testes de infraestrutura.
Referências: [Blueprint](https://render.com/docs/blueprint-spec),
[Web Services](https://render.com/docs/web-services),
[Static Sites](https://render.com/docs/static-sites).

## Preparação administrativa no Windows

1. Abrir o ThermoPower como o usuário Windows que normalmente executa o aplicativo;
   autenticar como administrador do ThermoPower.
2. Na sessão concluída, abrir Compartilhamentos → Configuração administrativa do portal.
3. Informar URL HTTPS da **API**, ID da instalação e credencial correspondente ao hash
   cadastrado no Render. Clicar em Salvar configuração.
4. URL, ID e credencial são gravados juntos no Gerenciador de Credenciais do Windows,
   entrada `ThermoPower/ResultsPortal/v1`, vinculada ao usuário Windows atual.
   Não são gravados em SQLite, arquivo de configuração, pacote ou localStorage.
   O campo de senha é limpo após a tentativa de gravação e a API nunca devolve o segredo.
5. Clicar em Testar conexão com o portal. É uma chamada autenticada à API, sem dados de ensaio.
6. Entrar como operador, salvar o período oficial, selecionar termopares e potência,
   abrir Compartilhar resultado, escolher Portal externo, senha opcional, validade
   e permissões. Clicar Publicar e gerar link e depois Copiar link.

Sem configuração, a interface explica a dependência e mantém relatórios/links locais.
A configuração por ambiente continua disponível para ambientes gerenciados; quando
`THERMOPOWER_RESULTS_PORTAL_URL` está definida, os três valores vêm exclusivamente
do ambiente e a edição pelo cofre é bloqueada. Não misturar identidades entre fontes.
Variáveis antigas incompletas devem ser removidas antes de usar a interface administrativa.
Em Linux não há fallback de segredo em arquivo: usar ambiente administrado.
Outro usuário/serviço Windows precisa da própria configuração; acesso ao cofre é uma
capacidade do usuário do SO, não isolamento contra malware executado sob essa mesma conta.

## Falhas, permissões e segurança operacional

- O UUID da solicitação local tem unicidade no banco; conteúdo diferente com mesmo UUID
  resulta em conflito. No portal, hash de token identifica snapshot imutável e o insert
  é atômico. Tentativas duplicadas não criam outro resultado nem mudam validade/senha.
- Publicação não confirmada não oferece link copiável. Usar Reenviar publicação;
  nunca reconstruir a partir de dados modificados. Após confirmação ou revogação,
  a cópia pendente local é descartada. Registros pendentes anteriores sem outbox
  precisam ser revogados antes de publicar novamente.
- Alterar permissões sincroniza uma política versionada e autenticada por HMAC.
  Pode desligar e reativar apenas opções autorizadas no snapshot original.
  Dados, senha e validade são imutáveis: revogar e publicar outro para alterá-los.
  Resposta perdida mantém alteração pendente visível; Reenviar alteração pendente
  envia a mesma revisão. Não indicar revogação concluída enquanto o portal não confirmar.
- Revogação cria tombstone mesmo antes do upload; envio atrasado não reativa o link.
  Novos acessos/downloads são bloqueados. Arquivos já baixados não são recolhidos.
- Tokens de acesso ficam no fragmento da URL e no corpo do POST; a API recebe somente
  hash na publicação. Credencial de máquina fica no header, sem query string.
  Não habilitar captura de bodies/headers ou analytics; revisar logs da infraestrutura.
- Senha opcional bcrypt, expiração e autorização por download reaproveitam a mesma
  política do ThermoPower local. HMAC verifica snapshot, identidade e política vigente.
- Limite persistente de 30 operações/minuto por endereço de socket e 600/minuto global,
  incluindo autenticação de máquina inválida; reiniciar workers não limpa contadores.
  No Render, com `--no-proxy-headers`, usuários podem compartilhar o limite do proxy.
  Esta escolha é conservadora: **não configurar confiança em `*`**. Validar NAT/carga
  e eventual lista de proxies confiáveis com evidência antes do uso operacional.
- Backups devem incluir banco e chave de integridade em cofre separado. Restauração
  de backup antigo exige reconciliar revogações/políticas antes de voltar ao público.
  Definir retenção e acompanhar espaço: não há exclusão automática de resultados expirados.
- A migration 0002 não atribui proprietário a snapshots antigos de testes. Registros
  sem identidade/política assinada falham fechados. Usar banco novo para a implantação;
  migração de um portal pré-existente exigiria inventário e associação explícita, nunca
  conceder tudo automaticamente à primeira instalação.

## Aceite externo pendente

Somente com dados sintéticos: publicar; abrir em duas redes e celular sem login;
desligar o laboratório; reiniciar a API; verificar gráficos/documentos; testar senha,
expiração, revogação e permissões diretamente na API; simular resposta perdida e reenvio;
tentar administrar o resultado com outra empresa/instalação; revisar logs; testar
restauração preservando revogações; medir carga, memória e comportamento dos limites.
Confirmar 404 para aquisição, usuários, suporte, docs e WebSocket operacionais.

PostgreSQL real, execução Linux/Render, DNS/TLS, acessos externos, carga e restauração
permanecem pendentes. Testes locais não são deploy nem homologação física do AT4532/GPM.
