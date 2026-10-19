# Portal independente de resultados

Estado: implementação local; **nenhum domínio, serviço público ou dado da Britânia foi publicado**.
Base física: `7059784949250ccf5519bc70b7e25c7f8ea4f384`, preservada no worktree
`feat/product-experience-071`. Não usar `app.main:app` no servidor público.

## Separação

`app.portal.application:create_app` importa somente o portal e a política compartilhada
`share_policy.py`. Não inicializa aquisição, serial, simulador ou banco da instalação.
O frontend público tem entrada própria `portal.html`/`src/portal.tsx`, sem dashboard,
login operacional ou navegação de equipamentos. Sua API é sempre da mesma origem.

A aplicação local publica somente por ação explícita de admin/operator. Exige sessão
finalizada e período oficial. Canais, potência, senha, validade e permissões são escolhidos
antes da publicação. O servidor prepara o snapshot e os documentos permitidos usando os
mesmos cálculos dos relatórios. O portal não recebe banco completo, usuários, equipamentos,
portas, payloads seriais nem credenciais de login. Não há sincronização em segundo plano.

O snapshot v1 contém resultado, gráficos reduzidos, limites das lacunas antes da redução,
estatísticas calculadas nas amostras originais e somente downloads autorizados. Documentos
têm SHA-256; o portal autentica todo o conteúdo armazenado por HMAC-SHA256 com chave própria.
Snapshots são imutáveis. Alterar nome, canais ou período local depois da publicação não
altera um link publicado: revogue e publique outro. A revogação também cria um impedimento
para uploads atrasados, evitando reativação por uma corrida com a publicação.

O registro local é salvo antes do envio. Se a confirmação se perder, aparece como
**Publicação não confirmada**, sem link copiável; continua revogável. Não presuma falha
do upload pela ausência de resposta. Revogue antes de publicar outro. Falha de conexão na
revogação é informada e não exibida como sucesso. Contadores remotos ficam no portal.

## Configuração e comandos (não executam implantação externa automaticamente)

Definir no ambiente do **portal**, com banco e credenciais exclusivos:

| Variável | Uso |
| --- | --- |
| `THERMOPOWER_PORTAL_DATABASE_URL` | PostgreSQL com usuário dedicado; SQLite em volume local para testes/instância única |
| `THERMOPOWER_PORTAL_PUBLISH_KEY` | Credencial aleatória de publicação/revogação, pelo menos 32 caracteres |
| `THERMOPOWER_PORTAL_INTEGRITY_KEY` | Outra chave aleatória, independente, pelo menos 32 caracteres |

Gerar as chaves com `secrets.token_urlsafe(32)` em ambiente seguro. Nunca incluí-las no
frontend, arquivo versionado, linha de comando de serviço ou log. O portal não precisa
de `THERMOPOWER_JWT_SECRET` nem das senhas da instalação. Para múltiplos workers use as
mesmas chaves e o mesmo banco. Não apontar o portal para o SQLite de aquisição.

Em um ambiente Python dedicado, a partir da raiz do projeto:

```sh
python -m pip install -r deploy/results-portal/requirements.txt
cd backend
python -m alembic -c portal-alembic.ini upgrade head
python -m uvicorn app.portal.application:create_app --factory --host 127.0.0.1 --port 8001 --no-access-log --proxy-headers --forwarded-allow-ips 127.0.0.1 --limit-concurrency 16
```

No frontend, `npm ci`, `npm run typecheck` e
`npm run build:portal`. Copiar **somente** `dist-portal/`
para `/srv/thermopower-results`. Não publicar o frontend operacional nem seus assets.
O exemplo `deploy/results-portal/nginx.conf` termina TLS e encaminha somente as rotas
públicas/administrativas do portal ao processo independente em loopback. Substituir domínio
e certificados após aprovação. A configuração é um modelo: Nginx/TLS precisam de teste
na hospedagem escolhida. Não há redirecionamento HTTP com token; distribuir links HTTPS.

Configurar na **instalação local**, fora do pacote e do Git:

| Variável | Uso |
| --- | --- |
| `THERMOPOWER_RESULTS_PORTAL_URL` | Origem HTTPS, sem caminho, query, usuário ou fragmento |
| `THERMOPOWER_RESULTS_PORTAL_PUBLISH_KEY` | Mesma credencial de publicação do portal |

Aplicar a migration local `python -m alembic upgrade head` com backup prévio. A revisão
`0011_share_result_options` acrescenta apenas dois campos opcionais de compartilhamento;
não modifica amostras ou sessões. Links antigos continuam locais e válidos.

Para ensaio local isolado, somente com dados sintéticos, pode-se usar origem
`http://127.0.0.1:8001` e `THERMOPOWER_RESULTS_PORTAL_LOCAL_TEST=1`. Essa exceção aceita
apenas loopback e não deve ser habilitada na implantação. Não é um link externo utilizável.

## Controles e limites

- Token de 256 bits derivado por HMAC e nonce aleatório existente; só seu SHA-256 chega
  ao portal. Token no fragmento do link, enviado no corpo dos POSTs. Senha bcrypt custo 12.
- Expiração, revogação e permissão são checadas em cada acesso/download usando a mesma
  função de autorização da instalação. Credenciais públicas não autorizam publicação.
- Limite persistente e atômico: 30 requisições/minuto por IP e 600/minuto global, janelas
  fixas de um minuto. Buckets antigos são eliminados; reiniciar o serviço não zera o limite.
  Validações inválidas são limitadas também pelo tamanho/concurrency/proxy. Um NAT pode
  compartilhar cota; verificar carga esperada antes da exposição pública.
- O aplicativo usa o IP do socket. O exemplo confia somente no proxy em loopback; ele
  **sobrescreve** X-Forwarded-For. Nunca confiar em `*` nem aceitar cabeçalhos de cliente
  diretamente. Para proxy em outra máquina, configurar IP explícito e firewall privado.
- Corpo público até 4 KiB, publicação até 25 MiB, leitura de corpo até 15 s. Upload local
  tem timeout de 30 s; interface pública 30 s; publicação na interface 60 s. Não há redirects
  automáticos no transporte da credencial. Documentos são gerados localmente, não sob acesso
  anônimo. Provisionar memória para uploads/arquivos simultâneos e limites de concorrência.
- Respostas, inclusive erros, usam `no-store`/`no-referrer`. Sem analytics, cache/CDN de
  resultados, logs de acesso ou captura de bodies/headers. Erros de validação não ecoam entradas.
  O exemplo Nginx também desliga logs que poderiam conter query strings. Monitorar por métricas
  de status, volume e disponibilidade, sem registrar URLs completas, senhas ou tokens.
- O servidor nunca busca uma URL fornecida pelo visitante. Só a origem de portal definida
  no ambiente da instalação pode receber publicação/revogação.

## Operação, backup e decisões pendentes

Definir responsável pela hospedagem, domínio, certificado, banco, retenção, custo e resposta
a incidentes antes de implantar. Alternativas: servidor administrado pela empresa com
PostgreSQL dedicado; ou serviço de aplicação gerenciado com PostgreSQL gerenciado. A primeira
opção exige operação de SO/TLS/backups; a segunda exige aprovação de fornecedor, região e
contrato. Nenhuma foi contratada, configurada ou exposta nesta etapa.

Banco contém resultados privados, hashes de senhas e documentos. Usar acesso mínimo,
criptografia de volume/backup e retenção aprovada. Backups precisam incluir as chaves de
integridade em cofre separado e preservar revogações recentes: restaurar backup antigo pode
restaurar estado antigo de links. Não servir tráfego até reconciliar revogações após restauração.
Trocar a chave de integridade requer migração/reassinatura controlada; não apagar a chave antiga
antes da verificação. Credencial de publicação é de confiança administrativa e deve ficar
apenas nas instalações autorizadas. Esta versão atende uma organização por implantação.

Revogação impede novos acessos; não recolhe documentos já baixados ou respostas já autorizadas.
Senha opcional/link repassado transfere acesso ao resultado autorizado. Nada aqui representa
homologação física ou acesso público já validado. PostgreSQL real, Nginx/TLS real, restauração
em produção e teste de carga da hospedagem escolhida continuam gates da implantação externa.

## Aceite externo posterior

1. Publicar somente resultado sintético e conferir HTTPS/certificado/headers em celular e desktop.
2. Fechar ThermoPower; verificar que gráficos, picos e downloads continuam disponíveis.
3. Testar senha errada, limite de tentativas, expiração e isolamento entre dois resultados.
4. Negar downloads desmarcados diretamente no backend, não apenas na interface.
5. Revogar e testar acesso/download novamente; simular perda de confirmação e upload atrasado.
6. Confirmar que `/api/v1/devices`, `/sessions`, `/support`, WebSocket e docs não são servidos.
7. Revisar logs e backups para ausência de credenciais e dados fora do snapshot autorizado.
