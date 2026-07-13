; Script do instalador do to.MD, gerado com Inno Setup.
; Empacota a pasta produzida pelo PyInstaller (dist\to.MD) num unico
; instalador .exe, com atalhos no Menu Iniciar / Area de Trabalho e
; desinstalador.

#define MyAppName "to.MD"
; A versão vem do CI via /DMyAppVersion=<versão de tomd/version.py>;
; o default abaixo vale só para builds locais na mão.
#ifndef MyAppVersion
  #define MyAppVersion "1.1"
#endif
#define MyAppExeName "to.MD.exe"
#define MyAppSourceDir "dist\to.MD"

[Setup]
AppId={{B6C1E9C4-9C4F-4B9B-8B7A-1D9F1E0A9C41}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppName}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=to.MD_Setup
SetupIconFile=app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; GroupDescription: "Atalhos adicionais:"

[Files]
Source: "{#MyAppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName} agora"; Flags: nowait postinstall skipifsilent
