# Candidata interna integrada 0.7.1

## Escopo e limites

A candidata reúne o checkpoint físico `7059784`, a experiência de resultados,
indicadores térmicos, períodos oficiais, seleção de canais, gráficos com lacunas,
portal externo e configuração administrativa já incorporados até `ba3f919`.
A revisão final organiza formulários, status e compartilhamentos em grids responsivos.
Também contém as dicas dos indicadores dentro dos cartões e adapta o login à largura
de tablet, eliminando os transbordamentos reproduzidos na auditoria visual.
Nenhuma política física, cálculo, protocolo, parser ou arquitetura de portal foi alterada.

Em 21/10/2026, o solicitante esclareceu que a suspeita de revogação resultou da
consulta a outro link ainda válido. Não há defeito de revogação confirmado.
As alterações corretivas exploradas durante a investigação foram canceladas;
o código de revogação/publicação e o viewer foram restaurados às versões originais.
Não é necessário atualizar o Render por causa desta suspeita.

O pacote é uma candidata interna de engenharia, não uma homologação física.
É necessário validar estabilidade contínua e recuperação em bancada AT4532/GPM.
Testes automatizados e sessões sintéticas não substituem essa validação.

## Atualização Windows

1. Finalize ou pause o ensaio conforme o procedimento operacional e feche o ThermoPower.
2. Faça backup da pasta de dados/configuração da instalação, com o aplicativo fechado.
   Preserve também o executável anterior para retorno controlado.
3. Confira o SHA-256 do ZIP com `Get-FileHash -Algorithm SHA256`.
4. Extraia o ZIP em uma pasta nova. Não extraia sobre uma candidata anterior.
5. Execute `ThermoPowerMonitor.exe` com o mesmo usuário Windows e a mesma configuração
   de diretório de dados. As migrations existentes serão aplicadas pelo aplicativo.
6. Confira versão, sessões históricas, configuração, relatórios e canais antes da bancada.
   Não conecte uma versão antiga a um banco migrado sem procedimento de restauração.

Nenhuma base real, credencial, log físico ou captura de cliente integra o ZIP.
O pacote não altera automaticamente o diretório de dados nem o cofre Windows.

## Conexão com o portal existente

Em **Configuração → Portal externo**, informe:

- URL HTTPS da API: `https://thermopower-results-free-api.onrender.com`.
- Identificador da instalação fornecido pelo administrador.
- Credencial exclusiva da instalação fornecida por canal seguro.

Salve e use **Testar conexão com o portal**. Salvar não equivale a validar a conexão.
A credencial permanece no Gerenciador de Credenciais do usuário Windows e não volta
ao formulário. Não use a URL do viewer no campo da API.

Em uma sessão finalizada, selecione os canais e o período oficial, abra
**Compartilhar resultado**, selecione **Portal externo** e publique. O link retornado
usa o viewer `https://thermopower-results-free-viewer.onrender.com`.

## Regressão de acesso

Use dados sintéticos e anote o identificador e o link exato de cada compartilhamento.
Teste senha correta/incorreta, expiração, downloads e alterações de permissões.
Revogue um único compartilhamento e teste **o mesmo link**, inclusive após atualizar
a página e em uma janela anônima. Um segundo link válido deve continuar funcionando.
Arquivos já baixados não podem ser recolhidos por revogação.

O servidor não foi modificado por esta entrega. O aceite remoto adicional e a bancada
física devem ser registrados separadamente dos gates locais.

Regressões locais: 430 testes backend, 78 frontend, 35 cenários backend do portal
(SQLite/PostgreSQL, incluindo dois links distintos) e quatro testes do viewer.
Migrations, geração de relatórios, lint, TypeScript, Ruff e Compose foram validados.
O smoke real de navegador do portal verificou senha, três formatos de download,
reinício independente, permissões e revogação com dados exclusivamente sintéticos.

## Evidências da execução

Os resultados, screenshots sintéticos, hashes de preservação, manifesto de fontes,
logs de build e smoke ficam em `build/integrated-071/`. O pacote final fica em
`engineering/ThermoPower-0.7.1-engineering-integrated.zip`, somente após gates locais
e smoke do executável congelado aprovados. O relatório de entrega registra o commit,
tamanho e SHA-256 efetivamente produzidos.
