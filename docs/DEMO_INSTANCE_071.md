# Ambiente DEMO isolado — 0.7.1 r2

Na raiz do checkout, use PowerShell e o ambiente Python do projeto:

```powershell
.\.venv\Scripts\python.exe scripts/demo-instance.py seed
.\.venv\Scripts\python.exe scripts/demo-instance.py test
.\.venv\Scripts\python.exe scripts/demo-instance.py start
```

O frontend deve estar compilado (`npm --prefix frontend run build`). A instância
reutiliza o launcher por configuração, sem modificar o executável em uso. Usa
`build\demo-r2\demo.db`, diretórios próprios de logs/relatórios, segredo próprio e
mutex `ThermoPowerIsolatedDemoR2`. O navegador abre na primeira porta livre entre
8765 e 8804; com a instância normal em 8765, normalmente será 8766.
Use `--no-browser` para não abrir o navegador. Credenciais sintéticas locais ficam
em `build\demo-r2\demo-instance.json`; não compartilhe esse arquivo.

As dez sessões **DEMO UX** começam entre 01 e 10/09/2026 e incluem aquecimento,
ciclagem, sensor aberto, lacuna, somente temperatura, somente potência, ensaio longo,
cancelamento e desconexão/reconexão. Os dados são inteiramente artificiais.
O teste gera nove documentos em `build\demo-r2\exports` e registra
`build\demo-r2\verification.json`. Nenhum dado real é copiado.
O seed é repetível; não duplica sessões. Não selecione portas/equipamentos reais.
Para novas aquisições de demonstração, selecione fontes com protocolo simulador.

Publicação externa fica desabilitada por configuração incompleta e sem acesso ao
cofre de credenciais normal. Para um teste manual autorizado, configure os três
valores abaixo com uma instalação exclusiva de demonstração. Obtenha a credencial
por entrada segura; não grave segredos no script ou histórico de comandos:

```powershell
$env:DEMO_PORTAL_URL = 'https://API-DE-DEMONSTRACAO'
$env:DEMO_PORTAL_INSTALLATION_ID = 'INSTALACAO-DE-DEMONSTRACAO'
$secret = Read-Host 'Credencial exclusiva do DEMO' -AsSecureString
$env:DEMO_PORTAL_PUBLISH_KEY = [System.Net.NetworkCredential]::new('', $secret).Password
.\.venv\Scripts\python.exe scripts/demo-instance.py start --portal-from-environment
Remove-Item Env:DEMO_PORTAL_PUBLISH_KEY
```

Esse comando apenas habilita a configuração: não publica automaticamente. Abra uma
sessão finalizada, selecione e salve o período oficial, escolha permissões e prazo,
e publique pela interface. Revogue o link depois do teste. Para marca corporativa,
o portal precisa estar atualizado para r2. Nenhum teste desta entrega publica no Render.

Feche somente a instância DEMO antes de remover:

```powershell
.\.venv\Scripts\python.exe scripts/demo-instance.py remove
```

A remoção exige o marcador do DEMO, valida o caminho fixo no workspace e rejeita
conteúdo com links/junctions. O banco em Documentos e o banco normal em AppData não
são alvos desse comando. Dados/credenciais DEMO não entram no pacote Windows.
