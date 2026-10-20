# Configuração administrativa independente do portal

Entrega local de 20/10/2026 na branch `feat/product-experience-071`, a partir de
`83116a2f37b2e4dcb9e6a148569c0a022e8d38f6`. Não é release homologada.

## Fluxo

O administrador acessa **Configuração → Portal externo** no menu lateral, rota
`/portal-externo`, mesmo sem nenhuma sessão cadastrada ou finalizada.
A página reutiliza `PortalConfiguration.tsx` e abre seus controles administrativos.

São exibidos URL HTTPS da API, identificador da instalação e campo de senha vazio
para fornecer uma credencial. Credenciais armazenadas nunca são retornadas ao formulário;
o campo é limpo após tentativa de gravação, inclusive quando ela falha.
Para salvar alterações, a credencial deve ser informada novamente, conforme o contrato existente.
Configuração administrada por ambiente exibe URL/identificador, sem editar segredos.

Estados visíveis: **Não configurado**, **Configurado**, **Conexão validada** e **Erro**.
Salvar não significa validar a conexão. A confirmação é da tentativa realizada nesta
visita à página e é descartada ao editar ou testar novamente. Alterações pendentes
precisam ser salvas antes do teste, pois o endpoint testa a configuração persistida.
Falha no teste permite nova tentativa. O timeout existente de 35 segundos foi preservado;
um portal gratuito suspenso pode exigir aguardar sua retomada e tentar outra vez.

## Autorização e preservação

O menu aparece somente para administradores e a rota usa o mesmo guard administrativo
de Usuários. Operadores, visualizadores e usuários não autenticados não montam a página.
No servidor, os endpoints existentes continuam protegidos:

- `GET /api/v1/results-portal/configuration`: leitura segura para operação, sem credencial;
- `PUT /api/v1/results-portal/configuration`: gravação exclusiva de administrador;
- `POST /api/v1/results-portal/check`: teste exclusivo de administrador.

`SessionSharing` permanece nas sessões finalizadas e continua reutilizando o componente.
Publicação, filtros e regras de compartilhamento não mudaram. Não foram alterados drivers,
aquisição, recuperação serial, protocolos, modelos, migrations, persistência, cofre,
endpoints ou relatórios. As únicas alterações no backend são testes de autorização
e de configuração sem sessões, com transporte/cofre simulados e dados sintéticos.

## Versão exibida e futura candidata

Foi confirmado que `VERSION.txt` ainda contém
`0.7.0-engineering-AT4532-celsius-trigger`. O frontend incorpora esse valor no build
por `frontend/vite.config.ts` (`__APP_VERSION__`) e o mostra no login.
O backend lê a mesma fonte em `backend/app/core/version.py`, com precedência do arquivo
embutido em executável congelado, depois do diretório de execução e da raiz do projeto.
O valor alimenta `/build-info` (Ajuda → Sobre), diagnóstico e metadados operacionais.
`frontend/package.json` e o lockfile também ainda identificam a versão de engenharia 0.7.0.
Não é apenas um texto antigo isolado em um componente.

Correção a fazer na preparação futura da candidata 0.7.1:

1. Definir explicitamente a identificação de pré-release/candidata aprovada, sem rotular
   como versão fisicamente homologada; atualizar `VERSION.txt` e alinhar metadados npm.
2. Revisar `backend/app/core/physical_trace.py`: a presença de `engineering-AT4532` na
   versão habilita tracing físico por padrão. Uma troca de versão pode mudar esse
   padrão; preservar a política desejada por configuração explícita e teste próprio.
   Nenhuma alteração nesse mecanismo foi feita nesta tarefa.
3. Reconstruir frontend e backend da mesma candidata e conferir login, Sobre,
   diagnóstico, `/build-info`, manifesto e arquivo de versão embutido no pacote.
   Atualizar apenas `VERSION.txt` não muda assets ou executáveis já construídos.
4. Preservar artefatos anteriores e executar gates e validação física aplicáveis antes
   de qualquer declaração de homologação. Pacote Windows, release e push são etapas separadas.

`VERSION.txt` foi mantido nesta entrega; o build local continua exibindo o identificador
antigo de forma conhecida e documentada. Não foi gerado pacote Windows.

## Verificação

- Testes focados: 14 frontend e 17 backend aprovados.
- Backend completo: 430 testes aprovados em 376,79 s; 27 avisos de dependências/JUnit,
  sem falhas. Evidência local em `build/portal-admin-071/backend.xml`.
- Frontend completo: 78 testes em 21 arquivos; lint, typecheck e build aprovados.
- Smoke Edge desktop/mobile: página independente, salvar/testar e limpeza de credencial
  aprovados, sem erros JavaScript, overflow ou consulta de sessões; API simulada.
- Compose: configuração validada com valores sintéticos, sem iniciar containers.
- Testes novos cobrem navegação sem sessões, bloqueio de rota/menu, campos protegidos,
  salvar/testar, estados, erro/retry, ambiente e ausência de segredo em respostas.
- O teste de conexão foi exercitado com transporte simulado; não utiliza credenciais
  reais nem comprova disponibilidade de uma implantação Render específica.
- A suíte automatizada não constitui homologação física. Não houve push, merge,
  deploy, tag, release ou geração de pacote Windows nesta entrega.
