# Auditoria de segurança — ThermoPower Monitor 0.7.0

Data: **12/10/2026**, America/Sao_Paulo. Branch: `security/audit-070`.
Base: `862c8ce10ac02754c2e02dcc7eb48547fae8e060`.

## Resultado e limites

Confirmadas e corrigidas **uma vulnerabilidade crítica e quatro altas**, sob
as condições descritas abaixo. Permanecem riscos médios/baixos e alertas SCA,
inclusive críticos na cadeia de desenvolvimento. **Não há declaração de
conformidade, segurança irrestrita ou prontidão para exposição corporativa.**

Todos os testes da aplicação usaram dados sintéticos e SQLite isolado em
`build/security-audit-070/`. O servidor HTTP temporário vinculou-se somente
a `127.0.0.1` e foi encerrado ao terminar. Nenhuma infraestrutura da Britânia,
porta serial ou equipamento real foi acessado. Acesso externo limitado ao Git
remoto autorizado, ferramentas/dependências e bases públicas de vulnerabilidades.
Semgrep executou localmente com métricas desativadas, sem upload de código.

AT4532, GPM, protocolos, máquina de aquisição, common-start, pausa/continuação
e correção de persistência permanecem preservados. Nenhuma migration, nova
funcionalidade, versão da aplicação, executável ou ZIP de entrega foi gerado.
O ZIP baixado para instalar Gitleaks é somente ferramenta de auditoria;
exportações em memória da suíte são fixtures. Sem commit, push, tag ou release.
Esta auditoria não homologa aquisição física nem atualiza binários existentes.

## Preparação e preservação

Lidos `AGENTS.md`, `RELIABILITY_AUDIT_070_20261011.md`,
`PENDING_SAMPLE_PERSISTENCE_070.md` e documentação de implantação.
`git status --short --branch` mostrou `master...origin/master`, sem mudanças.
Histórico solicitado:

```text
862c8ce fix: improve sample persistence and session reliability
401e582 fix(at4532): acquire TCP-32 frames with validated Celsius triggers
ec4e445 feat(analysis): refine session periods, events and sharing workflows
e196671 feat: add product analysis, development demo and isolated AT4532 characterization
1a3170f  FEAT Correção
```

Executado `git fetch origin`; `git rev-list --left-right --count
master...origin/master` retornou `0 0`. Criada a branch com
`git switch -c security/audit-070`, a partir de `862c8ce`.
Não se descartou ou sobrescreveu trabalho local. Como o `conftest.py` usa URL
SQLite relativa, pytest executou em diretórios novos, preservando os bancos
de teste preexistentes da raiz/backend e os artefatos anteriores.

## Crítica — corrigida

### C01 — segredos padrão permitem assumir administração

**Condição:** iniciar backend com a chave JWT padrão antiga ou subir Compose
sem substituir seus defaults. Compose publicava `8080:80` e fornecia senha
administrativa, senha PostgreSQL e chave JWT conhecidas no código. Não se
afirma que uma instalação real tenha utilizado essa configuração.

**Evidência:** `config.py` continha chave constante e Compose usava
`${VAR:-valor-conhecido}`. Em banco sintético, JWT HS256 assinado com a chave
antiga e `sub="1"` obteve **200 em `/api/v1/users`**, sem login, demonstrando
administração indevida nessa configuração. A senha inicial conhecida também
permitia login sem falsificação de token.

**Correção:** rejeitar chave ausente, menor que 32 bytes ou igual aos três
placeholders conhecidos; exigir variáveis não vazias no Compose por
`${VAR:?...}`. Comprimento não comprova entropia: gerar segredo aleatório.

**Testes:** `test_known_or_short_jwt_keys_are_rejected`,
`test_missing_jwt_key_is_rejected`, `test_compose_requires_explicit_secrets`,
`test_default_signing_key_allows_admin_impersonation_before_fix` e
`test_known_key_forgery_is_rejected_with_private_key`. A demonstração injeta
deliberadamente a chave antiga em memória; o startup agora a rejeita.

**Impacto operacional:** desenvolvimento também exige chave privada explícita.
O launcher Windows já gera chave aleatória persistente. Não houve rotação de
segredo real. Rotacionar chave invalida JWTs e impede reconstruir links antigos;
planejar essa operação e proteger o backup do segredo.

## Altas — corrigidas

| ID | Evidência/reprodução local | Correção e alcance |
|---|---|---|
| A01 — divulgação de senha inicial | `GET /api/v1/build-info` sem autenticação retornava e-mail/senha em `development`, `test`, `windows-beta` e `physical-alpha`. Quatro regressões falharam antes da correção. Se a senha ainda estiver vigente, o visitante autentica como admin. | `demo_credentials` preservado no contrato, sempre `null`. Login manual funciona. Testes de backend/frontend atualizados, sem alteração visual ou de aquisição. |
| A02 — resolução UNC/SSRF Windows | Com frontend presente, `/assets/%5C%5Caudit.invalid%5Cshare%5Cfile.js` e a rota SPA entregavam caminho não confiável ao resolvedor. Teste substituiu `os.path.realpath` e interrompeu **antes de qualquer acesso externo**. Não houve captura real de NTLM. | Middleware rejeita barra invertida, colon/drive, NUL e barras iniciais duplicadas antes de `StaticFiles`/`Path.resolve`, inclusive UNC com barras normais percent-encoded. HTTP 400. Mitigação da aplicação, não remoção do aviso da biblioteca. |
| A03 — Range quadrático | Parser instalado consumiu **0,017095 / 0,067777 / 0,256598 s** para **2.000 / 4.000 / 8.000 zeros** seguidos de `a-`. Ensaio pequeno, sem saturação; caminho público em SPA/assets. | Aceitar somente um range com até 19 dígitos por posição antes do parser. Múltiplos headers/intervalos e formatos inválidos recebem 416. Downloads completos e ranges `0-2`, `-4`, `10-` preservados. Multi-range deixa de ser aceito. |
| A04 — headers multipart ilimitados antes de autenticar | POST anônimo em `/api/v1/imports/gpm8213/preview` com header de parte de **65.536 bytes** chegava integralmente ao callback do parser, antes da autenticação. Reprodução limitada, sem arquivo real ou carga destrutiva. | Atualizado somente `python-multipart` **0.0.20 → 0.0.31**. Header agora rejeitado com 400 antes de chegar inteiro ao callback. Importadores, parsers físicos e protocolos intactos; `pip check` aprovado. |

Fontes primárias:
[UNC/Windows](https://github.com/Kludex/starlette/security/advisories/GHSA-wqp7-x3pw-xc5r),
[Range](https://github.com/Kludex/starlette/security/advisories/GHSA-7f5h-v6xp-fcq8),
[headers multipart](https://github.com/Kludex/python-multipart/security/advisories/GHSA-pp6c-gr5w-3c5g),
[preamble/epilogue multipart](https://github.com/Kludex/python-multipart/security/advisories/GHSA-mj87-hwqh-73pj).

## Médias — registradas, não corrigidas

| ID | Evidência/condição | Recomendação |
|---|---|---|
| M01 — autorização WebSocket incompleta | Usuário sintético inativo recebe 401 em `/auth/me`, mas `connection.ready` em `/ws`. JWT assinado para ID inexistente também entra; Origin externo aceito. Loop não revalida usuário/expiração/perfil depois de entrar. Não há entrada sem JWT válido demonstrada. | Consultar usuário ativo, definir revalidação/revogação e política de Origin/mensagens por perfil. Origin não substitui autenticação. |
| M02 — contorno de restrição de leitura viewer por Host | Viewer recebe 403 em `/simulator/scenarios`; com `Host: testserver/allowed?x=` recebe 200. Autorização usa `request.url.path`, router usa ASGI. Nenhum discovery/comando físico foi chamado. Endpoints com `require_roles` adicional permanecem protegidos. | Usar caminho ASGI para autorização e validar Host no perímetro; atualizar framework. Exige viewer autenticado e proxy que aceite/encaminhe Host malformado. [Aviso moderado do fornecedor](https://github.com/Kludex/starlette/security/advisories/GHSA-86qp-5c8j-p5mr). |
| M03 — truncamento bcrypt | Hash de `'a'*72+'first'` valida `'a'*72+'second'`. Contratos de usuário/login aceitam até 128 caracteres sem limite em bytes. Compartilhamentos já limitam 72 bytes. | Validar limite em bytes na criação e definir compatibilidade de contas existentes, sem trocar hashes silenciosamente. |
| M04 — limites de recursos incompletos | Login limita IP+e-mail, mas mapa cresce ao variar e-mails. Compartilhamento possui mapa limitado; ambos são por processo. Sem limite global de WS/exportação. Upload limita 25 MiB após parsing; XLSX limita linhas, não bytes descompactados. | Limites de corpo/conexão no proxy e antes do parser; orçamento de trabalho de relatórios/importações. ZIP bomb e exaustão por concorrência **não executados/comprovados**. |
| M05 — HTTP/navegador | Python local não fornece CSP/HSTS/X-Frame-Options/nosniff em `/health`. Nginx adiciona nosniff/SAMEORIGIN/Referrer-Policy, mas não TLS. JWT em localStorage e query do WS. | TLS corporativo, CSP compatível, proteção de framing/cache e logs sem tokens. Risco por XSS é condicional: não foi demonstrado XSS no produto. |
| M06 — dados/backups/distribuição | SQLite, chave JWT e primeiro acesso são arquivos locais sem criptografia própria; ACL depende do diretório/perfil. Docker backend não define USER não privilegiado. Binário existente client-preview está `NotSigned`. | ACL/criptografia/backup protegido, execução sem privilégios, assinatura e distribuição controlada. Definir retenção/RPO/RTO e testar restauração. Nenhum diretório de dados de instalação real foi inspecionado. |

Esses achados não foram elevados artificialmente a alta severidade para ampliar
as mudanças autorizadas. M04/M05/M06 incluem riscos de implantação, com os
limites de evidência explícitos.

## Baixas / endurecimento

- **B01 — claims JWT:** token assinado sem `exp` obtém 200; `sub` não numérico
  assinado gera 500. Emissão normal inclui `sub/iat/exp`. Não se demonstrou
  falsificação sem chave privada. Exigir claims e tratar conversão inválida.
- **B02 — logout/duração:** remoção de localStorage não revoga token copiado;
  duração padrão 480 minutos. Rever política corporativa em mudança dedicada.
- **B03 — exposição/coleções:** health/build-info/OpenAPI públicos; algumas
  coleções (`users/devices/reports`) sem paginação. Isso não permite listar
  usuários sem autenticação. Rever exposição e limites.
- **B04 — logs:** arquivos JSON/suporte aplicam `sanitize`, mas eventos de
  login no banco contêm e-mail. Redação por padrões não garante remoção de
  qualquer segredo livre. Proxy requer configuração própria. Não se exportou
  ou leu log operacional real.

## SAST, segredos e falsos positivos

Ferramentas Python instaladas isoladamente em `build/security-audit-070/tools/`.

| Ferramenta/escopo | Resultado | Triagem |
|---|---|---|
| Bandit 1.9.4, `backend/app`, antes/depois | 2 LOW, zero erros | B311 no simulador gera sinais, não segredos. B105 em `adapters/specific.py` é literal `"None"` de metadado, não senha. **Falsos positivos contextuais**, sem editar drivers. |
| Semgrep 1.180.0, `p/security-audit` + `p/secrets`, backend/frontend/scripts/Compose | Primeira análise: 139 regras, 109 alvos; 3 achados e zero erros, mantidos na reanálise | URL em `monitor-serial-stability.py` vem de CLI local, não de endpoint público. Dois ElementTree em scripts de empacotamento leem XML local de evidência. Não provam SSRF/XXE da API. Usar somente evidência confiável; scripts não foram executados/alterados. |
| Gitleaks 8.30.1, histórico e arquivos atuais | 44 commits, cerca de 2,50 MB, zero achados; snapshot de 244 arquivos atuais, zero achados | Não comprova ausência de segredos. C01/A01 foram descobertos manualmente; valores de demo/default não necessariamente correspondem às regras. Resultados com `--redact`; arquivos ignorados de instalações/build não foram varridos. |

Semgrep registra exclusões por padrões `.semgrepignore` e escopo Git; não cobre
binários ou toda a cadeia de dependências. Legacy foi incluído na varredura de
segredos do histórico, sem alterações.

## SCA — dependências e aplicabilidade

`pip-audit 2.10.1` consultou requirements resolvidos e ambiente instalado.
Ambos apresentaram **82 registros em cinco pacotes, 47 IDs PYSEC distintos**.
Há duplicação na fonte; não são 82 falhas independentes da aplicação.
Depois da atualização multipart: **70 registros, 41 IDs distintos em quatro
pacotes**. JSONs integrais preservados na evidência local.

| Pacote antes | IDs distintos | Aplicabilidade/decisão |
|---|---:|---|
| PyJWT 2.10.1 | 16 | Maioria exige PyJWK/PyJWKClient, mistura HMAC/assimétrico, chaves externas ou revogação por hash. Produto usa string local e um algoritmo HS256 por padrão. Alerta disputado sobre tamanho de chave tratado por C01; política não usa extensões `crit`. Nenhum bypass adicional sem chave privada comprovado. Recomendar atualização dedicada. |
| python-multipart 0.0.20 | 6 | A04 e preamble/epilogue atingem parser pré-autenticação. Atualizado para 0.0.31; seis IDs deixam de aparecer. Path traversal por `UPLOAD_KEEP_FILENAME`/`UPLOAD_DIR` e `parse_form()` não correspondem ao uso pela aplicação. |
| Pillow 11.3.0 | 18 | Avisos dependem de decodificação de imagens específicas do atacante. API não recebe imagens; XLSX usa `read_only=True, data_only=True`; gráficos internos. Exploração pelos endpoints não demonstrada. Atualizar em manutenção testada de relatórios; não declarar biblioteca isenta. |
| pytest 8.4.1 | 1 | Test runner, também listado em requirements de produção. Não é endpoint. Separar dependências de teste em mudança futura; somente repositórios confiáveis. |
| Starlette 0.47.3 | 6 | UNC/Range mitigados na entrada HTTP; Host permanece M02. `HTTPEndpoint` com métodos implícitos não é usado. Limites de corpo urlencoded/request-target malformado ainda exigem tratamento no framework/perímetro. FastAPI 0.116.1 exige Starlette `<0.48.0`; correção integral requer atualização conjunta. |

Não foi aplicada atualização geral de FastAPI/Starlette/PyJWT/Pillow sem
exploração comprovada no contexto ou sem avaliar compatibilidade ampliada.
As mitigações HTTP **não removem** alertas SCA de Starlette.

`npm audit --json`: **19 pacotes afetados — 2 critical, 13 high, 4 moderate**.
Contagens incluem propagação para dependentes. Package/lock não foram alterados;
não se repetiu consulta idêntica.

| Grupo npm | Classificação/contexto | Decisão |
|---|---|---|
| `tinypool`, `vitest` | Critical: gadget de prototype pollution para RCE em workers; depende de primitive/configuração controlada anterior, não demonstrada no produto. Ferramentas de desenvolvimento, não serviços no bundle React. | **Pendência crítica da cadeia de desenvolvimento**, não RCE remota comprovada do dashboard. Sem testes/configurações não confiáveis ou segredos de implantação no runner. Audit sugere mudança maior para Vitest 5.0.4; planejar atualização isolada. |
| `@vitest/mocker` | Moderate, leitura de arquivos no servidor de mock quando habilitado. | Não expor servidor de testes; atualizar separadamente. |
| `brace-expansion`, `braces`, `micromatch`, `fast-glob`, cadeia `typescript-eslint` | High, DoS por padrões recursivos/expansão. | Lint/build recebem fontes locais; não encontrado endpoint que alimente esses padrões. Não reproduzida exploração da aplicação. |
| `js-yaml`, `nanoid`, `source-map-js` | High, entradas YAML/gerador/mapa específicas. | Uso transitivo de ferramentas, sem caminho de entrada da API identificado. Pendência de manutenção, não falso positivo universal. |
| `@remix-run/router`, `react-router`, `react-router-dom` | Moderate, redirects/SSR. | SPA sem hidratação SSR identificada e sem destino arbitrário do usuário encontrado. Atualização 6.30.6 indicada pelo scanner, recomendada. |

Fontes primárias dos críticos npm:
[worker options](https://github.com/tinylibs/tinypool/security/advisories/GHSA-5gmw-xhrv-c9v3),
[run options](https://github.com/tinylibs/tinypool/security/advisories/GHSA-85c8-ppgw-ccpr).
PoC de RCE não executado: pré-condição de prototype pollution não demonstrada.

## Cobertura funcional

- **Admin/operator/viewer:** enumeração das rotas operacionais no teste viewer;
  403 para operator/viewer em `/users` mesmo com claim assinado `role=admin`.
  HTTP usa papel/atividade do banco. Perfis globais do laboratório; não se
  promete isolamento por tenant/proprietário. Exceções M01/M02 explicitadas.
- **Compartilhamento:** testes de senha, hash/nonce, expiração, revogação,
  permissões por PDF/XLSX/CSV, ocultação de outro ensaio/metadados, rejeição de
  parâmetros extras, share-token inválido como JWT, rate limit e headers
  `no-store/no-referrer`. Token no fragmento, enviado no corpo para acesso.
  Operadores administram links das sessões do laboratório por desenho atual.
- **Entradas/exportações:** rejeição de vazio/extensão errada; ORM parametrizado;
  entrada semelhante a SQL não autentica. XLSX sem fórmulas em textos não
  confiáveis pela correção anterior e teste existente; Paragraph de PDF escapa
  texto. Upload não é gravado pelo nome original. Sem ZIP bomb de grande volume.
- **Banco/log/backup:** suíte inclui backup/restauração SQLite sintético,
  integridade, migrations, rollback e persistência. Sem ensaio PostgreSQL real,
  restauração corporativa ou permissões entre contas Windows. Sem schema change.
- **Windows:** revisão launcher/PyInstaller/instalador; bind loopback, senha/chave
  aleatórias persistentes e `PrivilegesRequired=lowest`. Authenticode do binário
  `release/ThermoPower-0.7.0-client-preview/ThermoPowerMonitor.exe`: `NotSigned`.
  Não executado/recompilado, **não contém estas correções**.

## Testes executados e indisponíveis

Evidências locais ignoradas pelo Git em `build/security-audit-070/`.

| Verificação | Resultado/evidência |
|---|---|
| Reprodução pré-correção | 17 falhas por vulnerabilidade e 8 aprovações em `repro-expanded-before.xml`; falha multipart em `multipart-before.xml`. A primeira tentativa também esperava `.csv` onde a API exige `.txt`: erro de teste corrigido, não vulnerabilidade. |
| Segurança/perfis/shares/preview | **37 aprovados**, `focused-final.xml`. Execução anterior sofreu interferência entre dois processos no mesmo banco sintético (`no such table`); descartada e repetida sequencialmente. Nenhum banco operacional envolvido. |
| Gate de fixtures físicas/persistência | **19 aprovados**, `physical-persistence-gate.xml`. Não equivale a bancada. |
| HTTP em subprocesso loopback | Aprovado, `http-local-results.json`: anônimo 401; login/me 200; senha oculta; range simples 206, múltiplo 416; caminho Windows 400; CORS externo 400. Processo encerrado. |
| Riscos restantes | `observations.json`: M01/M02/M03, B01, headers, oito logins 401 seguidos de 429. Sem carga destrutiva. |
| Frontend completo | Lint, typecheck, **55 testes** e build Vite aprovados. `frontend-results.json` e logs separados. Build web de validação, sem pacote Windows. |
| Backend completo | **328 aprovados**, 25 avisos, 280,36 s, `backend-full.xml`; execução única em banco sintético. Após reforço final da variante UNC com barras normais, **28 testes focados aprovados**, 22,92 s, `security-final.xml`, incluindo um caso adicional. Não se afirma nova execução completa depois desse reforço. |
| SAST/SCA | Bandit, Semgrep, pip-audit e npm audit executados. Código não zero por achados não significa ferramenta indisponível. |
| OWASP ZAP Baseline | **Indisponível**: ZAP e Docker não encontrados. Sondagens HTTP locais não equivalem a ZAP. |
| `docker compose config --quiet` | **Não executável**, Docker ausente. Teste textual dos segredos não substitui interpolação/validação Compose oficial. |
| PostgreSQL/TLS/proxy/ACL/carga/hardware | **Não executados** neste ambiente/escopo. Não inferir aprovação por SQLite/mocks/fixtures. |

Comandos principais (raiz, PowerShell):

```powershell
build/security-audit-070/tools/Scripts/python.exe -m bandit -r backend/app -f json -o build/security-audit-070/bandit-after.json
build/security-audit-070/tools/Scripts/semgrep.exe scan --config p/security-audit --config p/secrets --metrics=off --disable-version-check --json --output build/security-audit-070/semgrep-after.json backend/app frontend/src scripts docker-compose.yml
build/security-audit-070/tools/Scripts/python.exe -m pip_audit -r backend/requirements.txt -f json -o build/security-audit-070/pip-audit-after.json --progress-spinner off
build/security-audit-070/tools/Scripts/python.exe -m pip_audit --path .venv/Lib/site-packages -f json -o build/security-audit-070/pip-audit-installed.json --progress-spinner off
build/security-audit-070/gitleaks/gitleaks.exe git . --redact --report-format json --report-path build/security-audit-070/gitleaks-history.json --no-banner
# Em frontend/: npm.cmd audit --json; npm.cmd run lint; npm.cmd run typecheck;
# npm.cmd test -- --run; npm.cmd run build
# Em build/security-audit-070/work/, PYTHONPATH apontando para backend:
# ../../../.venv/Scripts/python.exe -m pytest ../../../backend/tests --junitxml=../backend-full.xml
```

## Riscos de implantação corporativa

Antes de acesso de rede, resolver/aceitar formalmente pendências, remover
credenciais padrão de instalações existentes, configurar segredos aleatórios,
TLS/proxy/firewall e limites de corpo/conexões. Não expor dev server, Vitest
ou ferramentas de engenharia. Logs do proxy não devem guardar JWTs/queries.

Planejar atualização conjunta FastAPI/Starlette e ferramentas de build/teste,
revalidando imports/exports/WS. Ausência de caminho identificado não garante
inexistência em outra configuração. Tratar os críticos da cadeia de build
separadamente do bundle servido. Validar Compose/PostgreSQL, ACLs, restauração
de backup, assinatura e política de compartilhamento/sessões em ambientes
apropriados. Preservar chave persistente em backup protegido. Nenhum desses
itens autoriza testes na infraestrutura da Britânia.

## Arquivos alterados

- `backend/app/core/config.py`: chave JWT.
- `backend/app/api/routes.py`: build-info sem credenciais.
- `backend/app/core/http_security.py` (novo): limites de path/range.
- `backend/app/main.py`: middleware; lifecycle/persistência preservados.
- `backend/requirements.txt`: multipart.
- `docker-compose.yml`: segredos obrigatórios.
- `backend/tests/test_security_audit.py` (novo): reproduções/regressões.
- `backend/tests/test_physical_engineering.py`: somente teste de build-info.
- `frontend/src/test/LoginPage.test.tsx`: contrato sem senha exposta.
- `docs/SECURITY_AUDIT_070.md`: relatório.

## Fechamento

Ruff nos arquivos de segurança e `git diff --check`: aprovados. Formatação dos
dois novos arquivos Python verificada. Os avisos da suíte incluem depreciações
de dependências gráficas e marcadores/propriedades de testes existentes; nenhuma
falha ou `xfail` na execução completa. `pip check`: sem dependências quebradas.

`protected-files.json` compara objetos Git com HEAD e armazena SHA-256 de 28
arquivos protegidos: adaptadores, importadores, domínio, aquisição, persistência,
sincronização/relógio, versões, dependências frontend e legacy. Todos iguais.
`scope-ast.json` compara funções: em 90 funções de `api/routes.py`, somente
`build_info` mudou; todas as sete funções de `main.py`, incluindo seed e
lifespan, permanecem iguais. O middleware é registrado fora dessas funções.

`evidence-manifest.json` contém SHA-256 dos resultados locais. O executável
anterior teve hash registrado, sem execução ou modificação. A análise estática
não substitui validação física nem assinatura de distribuição.

Estado final: HEAD permanece `862c8ce`, branch `security/audit-070`, **sete
arquivos rastreados modificados e três novos**, sem staging/commit:

```text
## security/audit-070
 M backend/app/api/routes.py
 M backend/app/core/config.py
 M backend/app/main.py
 M backend/requirements.txt
 M backend/tests/test_physical_engineering.py
 M docker-compose.yml
 M frontend/src/test/LoginPage.test.tsx
?? backend/app/core/http_security.py
?? backend/tests/test_security_audit.py
?? docs/SECURITY_AUDIT_070.md
```

## Inventário SCA Python da execução inicial

Lista deduplicada por ID PYSEC; versões corrigidas são informações do scanner,
não garantia de compatibilidade com esta aplicação. A triagem por pacote acima
define o contexto. Os seis IDs de multipart foram removidos na reanálise; os
demais permanecem no SCA, inclusive os mitigados na entrada HTTP.
| Pacote | ID do scanner | Referências / versões corrigidas informadas |
|---|---|---|
| pyjwt | PYSEC-2026-120 | CVE-2026-32597, [GHSA-752w-5fwx-jx9f](https://github.com/advisories/GHSA-752w-5fwx-jx9f); 2.12.0 |
| pyjwt | PYSEC-2025-183 | CVE-2025-45768;  |
| pyjwt | PYSEC-2026-179 | [GHSA-xgmm-8j9v-c9wx](https://github.com/advisories/GHSA-xgmm-8j9v-c9wx), CVE-2026-48526; 2.13.0 |
| pyjwt | PYSEC-2026-175 | [GHSA-993g-76c3-p5m4](https://github.com/advisories/GHSA-993g-76c3-p5m4), CVE-2026-48522; 2.13.0 |
| pyjwt | PYSEC-2026-177 | CVE-2026-48524, [GHSA-fhv5-28vv-h8m8](https://github.com/advisories/GHSA-fhv5-28vv-h8m8); 2.13.0 |
| pyjwt | PYSEC-2026-178 | [GHSA-w7vc-732c-9m39](https://github.com/advisories/GHSA-w7vc-732c-9m39), CVE-2026-48525; 2.13.0 |
| pyjwt | PYSEC-2026-176 | [GHSA-jq35-7prp-9v3f](https://github.com/advisories/GHSA-jq35-7prp-9v3f), CVE-2026-48523; 2.13.0 |
| pyjwt | PYSEC-2026-4145 | [GHSA-ffc3-869f-jxw9](https://github.com/advisories/GHSA-ffc3-869f-jxw9), CVE-2026-102268; 2.14.0 |
| pyjwt | PYSEC-2026-4149 | CVE-2026-102271, [GHSA-p4g4-x82p-q773](https://github.com/advisories/GHSA-p4g4-x82p-q773); 2.14.0 |
| pyjwt | PYSEC-2026-4152 | CVE-2026-102274, [GHSA-w6j9-cwv2-h6wq](https://github.com/advisories/GHSA-w6j9-cwv2-h6wq); 2.14.0 |
| pyjwt | PYSEC-2026-4144 | [GHSA-9v7f-9g4p-ffgj](https://github.com/advisories/GHSA-9v7f-9g4p-ffgj), CVE-2026-102267; 2.14.0 |
| pyjwt | PYSEC-2026-4148 | [GHSA-jwrc-g2q2-pq5p](https://github.com/advisories/GHSA-jwrc-g2q2-pq5p), CVE-2026-102270; 2.14.0 |
| pyjwt | PYSEC-2026-4140 | CVE-2026-101917, [GHSA-2gx3-rcp4-g85q](https://github.com/advisories/GHSA-2gx3-rcp4-g85q); 2.14.0 |
| pyjwt | PYSEC-2026-4141 | CVE-2026-101918, [GHSA-42vr-xj54-vc7v](https://github.com/advisories/GHSA-42vr-xj54-vc7v); 2.15.0 |
| pyjwt | PYSEC-2026-4147 | CVE-2026-102269, [GHSA-hxm8-2xgr-2p9m](https://github.com/advisories/GHSA-hxm8-2xgr-2p9m); 2.14.0 |
| pyjwt | PYSEC-2026-4183 | CVE-2026-102275, [GHSA-x33g-cr3x-6449](https://github.com/advisories/GHSA-x33g-cr3x-6449); 2.15.0 |
| python-multipart | PYSEC-2026-1852 | [GHSA-wp53-j4wj-2cfg](https://github.com/advisories/GHSA-wp53-j4wj-2cfg), CVE-2026-24486; 0.0.22 |
| python-multipart | PYSEC-2026-3038 | [GHSA-mj87-hwqh-73pj](https://github.com/advisories/GHSA-mj87-hwqh-73pj), CVE-2026-40347; 0.0.26 |
| python-multipart | PYSEC-2026-3039 | CVE-2026-42561, [GHSA-pp6c-gr5w-3c5g](https://github.com/advisories/GHSA-pp6c-gr5w-3c5g); 0.0.27 |
| python-multipart | PYSEC-2026-3040 | CVE-2026-53540, [GHSA-v9pg-7xvm-68hf](https://github.com/advisories/GHSA-v9pg-7xvm-68hf); 0.0.31 |
| python-multipart | PYSEC-2026-3036 | [GHSA-5rvq-cxj2-64vf](https://github.com/advisories/GHSA-5rvq-cxj2-64vf), CVE-2026-53539; 0.0.30 |
| python-multipart | PYSEC-2026-3037 | CVE-2026-53538, [GHSA-6jv3-5f52-599m](https://github.com/advisories/GHSA-6jv3-5f52-599m); 0.0.30 |
| pillow | PYSEC-2026-2249 | [GHSA-cfh3-3jmp-rvhc](https://github.com/advisories/GHSA-cfh3-3jmp-rvhc), CVE-2026-25990; 12.1.1 |
| pillow | PYSEC-2026-2250 | [GHSA-whj4-6x5x-4v2j](https://github.com/advisories/GHSA-whj4-6x5x-4v2j), CVE-2026-40192; 12.2.0 |
| pillow | PYSEC-2026-165 | [GHSA-wjx4-4jcj-g98j](https://github.com/advisories/GHSA-wjx4-4jcj-g98j), CVE-2026-42308; 12.2.0 |
| pillow | PYSEC-2026-2251 | [GHSA-5xmw-vc9v-4wf2](https://github.com/advisories/GHSA-5xmw-vc9v-4wf2), CVE-2026-42309; 12.2.0 |
| pillow | PYSEC-2026-2874 | CVE-2026-42310, [GHSA-r73j-pqj5-w3x7](https://github.com/advisories/GHSA-r73j-pqj5-w3x7); 12.2.0 |
| pillow | PYSEC-2026-2252 | [GHSA-pwv6-vv43-88gr](https://github.com/advisories/GHSA-pwv6-vv43-88gr), CVE-2026-42311; 12.2.0 |
| pillow | PYSEC-2026-2253 | [GHSA-8v84-f9pq-wr9x](https://github.com/advisories/GHSA-8v84-f9pq-wr9x), CVE-2026-54059; 12.3.0 |
| pillow | PYSEC-2026-2255 | CVE-2026-55379, [GHSA-45hq-cxwh-f6vc](https://github.com/advisories/GHSA-45hq-cxwh-f6vc); 12.3.0 |
| pillow | PYSEC-2026-2257 | [GHSA-4x4j-2g7c-83w6](https://github.com/advisories/GHSA-4x4j-2g7c-83w6), CVE-2026-55798; 12.3.0 |
| pillow | PYSEC-2026-2256 | [GHSA-phj9-mv4w-65pm](https://github.com/advisories/GHSA-phj9-mv4w-65pm), CVE-2026-55380; 12.3.0 |
| pillow | PYSEC-2026-2254 | [GHSA-5x94-69rx-g8h2](https://github.com/advisories/GHSA-5x94-69rx-g8h2), CVE-2026-54060; 12.3.0 |
| pillow | PYSEC-2026-3453 | [GHSA-9hw9-ch79-4vh6](https://github.com/advisories/GHSA-9hw9-ch79-4vh6), CVE-2026-59205; 12.3.0 |
| pillow | PYSEC-2026-3451 | CVE-2026-59199, [GHSA-6r8x-57c9-28j4](https://github.com/advisories/GHSA-6r8x-57c9-28j4); 12.3.0 |
| pillow | PYSEC-2026-3493 | [GHSA-62p4-gmf7-7g93](https://github.com/advisories/GHSA-62p4-gmf7-7g93), CVE-2026-54058; 12.3.0 |
| pillow | PYSEC-2026-3454 | [GHSA-xj96-63gp-2gmr](https://github.com/advisories/GHSA-xj96-63gp-2gmr), CVE-2026-59197; 12.3.0 |
| pillow | PYSEC-2026-3494 | CVE-2026-59198, [GHSA-fj7v-r99m-22gq](https://github.com/advisories/GHSA-fj7v-r99m-22gq); 12.3.0 |
| pillow | PYSEC-2026-3495 | [GHSA-jjj6-mw9f-p565](https://github.com/advisories/GHSA-jjj6-mw9f-p565), CVE-2026-59200; 12.3.0 |
| pillow | PYSEC-2026-3496 | CVE-2026-59204, [GHSA-vjc4-5qp5-m44j](https://github.com/advisories/GHSA-vjc4-5qp5-m44j); 12.3.0 |
| pytest | PYSEC-2026-1845 | CVE-2025-71176, [GHSA-6w46-j5rx-g56g](https://github.com/advisories/GHSA-6w46-j5rx-g56g); 9.0.3 |
| starlette | PYSEC-2026-1942 | CVE-2025-62727, [GHSA-7f5h-v6xp-fcq8](https://github.com/advisories/GHSA-7f5h-v6xp-fcq8); 0.49.1 |
| starlette | PYSEC-2026-161 | [GHSA-86qp-5c8j-p5mr](https://github.com/advisories/GHSA-86qp-5c8j-p5mr), CVE-2026-48710; 1.0.1 |
| starlette | PYSEC-2026-2281 | CVE-2026-48818, [GHSA-wqp7-x3pw-xc5r](https://github.com/advisories/GHSA-wqp7-x3pw-xc5r); 1.1.0 |
| starlette | PYSEC-2026-2280 | [GHSA-x746-7m8f-x49c](https://github.com/advisories/GHSA-x746-7m8f-x49c), CVE-2026-48817; 1.1.0 |
| starlette | PYSEC-2026-249 | CVE-2026-54283, [GHSA-82w8-qh3p-5jfq](https://github.com/advisories/GHSA-82w8-qh3p-5jfq); 1.3.1 |
| starlette | PYSEC-2026-248 | CVE-2026-54282, [GHSA-jp82-jpqv-5vv3](https://github.com/advisories/GHSA-jp82-jpqv-5vv3); 1.3.0 |

