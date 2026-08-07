#ifndef AppVersion
  #error AppVersion must be provided by scripts\build-windows.ps1
#endif

[Setup]
AppId={{A6EE8BBE-18D8-4FD5-B6C2-B6EF52B46C85}
AppName=ThermoPower Monitor
AppVersion={#AppVersion}
AppPublisher=ThermoPower
DefaultDirName={localappdata}\Programs\ThermoPower Monitor
DefaultGroupName=ThermoPower Monitor
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=ThermoPower-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\ThermoPowerMonitor.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
CloseApplicationsFilter=ThermoPowerMonitor.exe,ThermoPowerVirtualLab.exe

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked
Name: "virtuallab"; Description: "Instalar Laboratório Virtual (recomendado para homologação)"; GroupDescription: "Componentes opcionais:"; Flags: checkedonce

[Files]
Source: "..\dist\ThermoPowerMonitor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\ThermoPowerVirtualLab\*"; DestDir: "{app}\VirtualLab"; Flags: ignoreversion recursesubdirs createallsubdirs; Tasks: virtuallab

[Icons]
Name: "{group}\ThermoPower Monitor"; Filename: "{app}\ThermoPowerMonitor.exe"
Name: "{autodesktop}\ThermoPower Monitor"; Filename: "{app}\ThermoPowerMonitor.exe"; Tasks: desktopicon
Name: "{group}\ThermoPower Virtual Lab"; Filename: "{app}\VirtualLab\ThermoPowerVirtualLab.exe"; Tasks: virtuallab
Name: "{autodesktop}\ThermoPower Virtual Lab"; Filename: "{app}\VirtualLab\ThermoPowerVirtualLab.exe"; Tasks: "desktopicon and virtuallab"

[Run]
Filename: "{app}\ThermoPowerMonitor.exe"; Description: "Abrir ThermoPower Monitor"; Flags: nowait postinstall skipifsilent

[Code]
function ThermoPowerIsRunning(): Boolean;
var
  ResultCode: Integer;
  PowerShellPath: String;
  Parameters: String;
begin
  if CheckForMutexes('ThermoPowerMonitorRunning,ThermoPowerVirtualLabRunning') then
  begin
    Result := True;
    exit;
  end;

  PowerShellPath := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
  Parameters := '-NoProfile -NonInteractive -Command "$p = Get-Process -Name ''ThermoPowerMonitor'',''ThermoPowerVirtualLab'' -ErrorAction SilentlyContinue; if ($p) { exit 42 }"';
  Result := Exec(PowerShellPath, Parameters, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 42);
end;

function ConfirmApplicationsClosed(): Boolean;
begin
  Result := not ThermoPowerIsRunning();
  if not Result then
    MsgBox(
      'O ThermoPower Monitor ou o Laboratório Virtual está aberto.' + #13#10 + #13#10 +
      'Feche a aplicação e tente novamente. Isso evita arquivos bloqueados durante a instalação ou atualização.',
      mbError,
      MB_OK
    );
end;

function InitializeSetup(): Boolean;
begin
  Result := ConfirmApplicationsClosed();
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  if CurPageID = wpReady then
    Result := ConfirmApplicationsClosed()
  else
    Result := True;
end;
