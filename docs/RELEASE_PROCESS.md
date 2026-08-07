# Processo de release Windows

`release-config.json` é a fonte de verdade da versão e das credenciais locais de homologação.
O build recusa versões divergentes e gera nomes de arquivo, `VERSION.txt`, notas e hashes a partir
desse manifesto; não edite esses valores diretamente nos scripts.

Execute `scripts\build-windows.ps1` em Windows x64 com Python, Node/npm e Inno Setup 6. O script restaura dependências, executa todos os gates, gera os dois executáveis, executa três smokes, cria instalador/ZIPs/PDFs e monta `release\ThermoPower-Monitor-0.5.0-beta` com SHA-256.

`-SkipInstaller` é permitido para CI portátil quando Inno Setup não estiver disponível. `-SkipDependencyInstall` reutiliza o ambiente local. Não use `npm audit fix --force`.

O workflow `windows-client-package.yml` roda em PRs de build, despacho manual e tags beta. Tags criam somente GitHub Release em estado draft; promoção estável é manual e depende da validação física.
