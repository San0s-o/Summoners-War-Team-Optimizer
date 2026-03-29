; Inno Setup script for SW Team Optimizer
; AppVersion and AppId are passed in via ISCC /DAppVersion=... /DAppId=...

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef AppId
  #define AppId "Summoners-War-Team-Optimizer"
#endif

#define AppName     "SW Team Optimizer"
#define AppExe      AppId + ".exe"
#define AppPublisher "San0s"

[Setup]
AppId={{8B5E2F31-C7A4-4D9E-B523-1047A6C89D20}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppVerName={#AppName} {#AppVersion}

; Kein UAC – Installation ins Benutzerverzeichnis
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}

OutputDir=dist
OutputBaseFilename={#AppId}-Setup-{#AppVersion}
SetupIconFile=app\assets\app_icon.ico

Compression=lzma2/ultra64
SolidCompression=yes

; Nur 64-Bit Windows
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; Wizard-Aussehen
WizardStyle=modern
ShowLanguageDialog=yes

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\{#AppId}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}";        Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
