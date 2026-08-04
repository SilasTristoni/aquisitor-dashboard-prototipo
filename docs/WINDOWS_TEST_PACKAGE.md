# Pacote de homologação Windows — 0.4.0-beta

## Objetivo e limites

Este pacote permite testar o ThermoPower Monitor em Windows 10/11 x64 sem instalar Python ou
Node.js no computador de destino. A comunicação com AT4532 e GPM-8213 está preparada, mas
permanece **pendente de validação física** porque os manuais e amostras reais não estão no
repositório. O simulador é o caminho de aceite funcional.

## Compilar

Pré-requisitos no computador de build:

- Windows x64;
- Python 3.11 ou superior e `.venv` criado;
- Node.js LTS/npm;
- Inno Setup 6 para gerar o instalador final.

Na raiz do repositório:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\build-windows.ps1
```

Para validar somente o pacote portátil, sem Inno Setup:

```powershell
.\scripts\build-windows.ps1 -SkipInstaller
```

Saídas esperadas:

- `dist\ThermoPowerMonitor\ThermoPowerMonitor.exe` e dependências portáteis;
- `dist\ThermoPower-Setup-0.4.0-beta.exe` quando o Inno Setup estiver disponível.

O script interrompe o build em falhas de lint, typecheck, testes, frontend ou PyInstaller.
Após gerar o pacote portátil, valide migrations, SPA, health e login executando
`scripts\smoke-windows-package.ps1`; o teste usa `build\smoke-runtime` e encerra o processo.

## Instalar e executar

1. Execute `ThermoPower-Setup-0.4.0-beta.exe` como o usuário que fará o teste.
2. Mantenha ou desmarque o atalho da área de trabalho.
3. Abra **ThermoPower Monitor**. O launcher aplica migrations, escolhe uma porta HTTP local
   livre e abre o navegador padrão.
4. Entre com as credenciais locais de homologação:
   - e-mail: `homologacao@demo.thermopower.com`
   - senha: `ThermoPower-HML@2026`
5. Abra o ícone de configurações para iniciar o assistente de primeiro uso.

Essas credenciais existem somente para o beta local. Para qualquer ambiente compartilhado,
defina `THERMOPOWER_DEMO_ADMIN_EMAIL`, `THERMOPOWER_DEMO_ADMIN_PASSWORD` e
`THERMOPOWER_JWT_SECRET` antes da primeira execução.

## Dados e logs

O instalador não remove dados operacionais ao desinstalar. Os arquivos ficam em:

```text
%LOCALAPPDATA%\ThermoPower Monitor\
  data\thermopower.db
  logs\thermopower.log
  reports\
  jwt-secret.key
```

Para reiniciar uma homologação do zero, feche o aplicativo, faça backup dessa pasta e renomeie
explicitamente apenas `%LOCALAPPDATA%\ThermoPower Monitor`. A operação apaga o histórico local
quando a pasta antiga for removida; por isso, não é automatizada pelo instalador.

## Roteiro mínimo de aceite

1. Login e abertura do assistente.
2. Conferência de banco, espaço e versão.
3. Descoberta das portas COM com equipamento desconectado e conectado.
4. Associação de uma porta e execução do diagnóstico em etapas.
5. Conexão do simulador, sessão com pelo menos dois minutos e finalização.
6. Relatório por sessão em CSV/XLSX/PDF.
7. Relatório por período incluindo a sessão: prévia, PNG, JPEG e PDF.
8. Reinício do aplicativo e conferência da persistência do histórico.

Para instrumentos reais, registre fabricante/modelo/firmware, VID/PID/serial, driver, porta,
baud rate, mensagens brutas autorizadas, frequência, canais e discrepâncias contra instrumento
de referência. Não marque a integração como homologada apenas porque a porta abriu.

## Solução de problemas

- **Navegador não abriu:** consulte `logs\thermopower.log` e abra a URL `127.0.0.1` indicada.
- **Porta ocupada:** feche softwares do fabricante/terminais seriais e atualize a descoberta.
- **Porta não aparece:** confira cabo e Gerenciador de Dispositivos; o driver pode estar ausente.
- **Banco não migra:** preserve o arquivo, envie o log ao suporte e não tente editar o SQLite.
- **Antivírus bloqueou:** forneça o hash e o pacote ao time de segurança; não desative proteção.
- **Instalador não foi gerado:** confirme Inno Setup 6; o pacote portátil ainda pode ser testado.
