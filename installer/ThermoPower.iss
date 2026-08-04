#ifndef AppVersion
  #define AppVersion "0.4.0-beta"
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

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked

[Files]
Source: "..\dist\ThermoPowerMonitor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ThermoPower Monitor"; Filename: "{app}\ThermoPowerMonitor.exe"
Name: "{autodesktop}\ThermoPower Monitor"; Filename: "{app}\ThermoPowerMonitor.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ThermoPowerMonitor.exe"; Description: "Abrir ThermoPower Monitor"; Flags: nowait postinstall skipifsilent
