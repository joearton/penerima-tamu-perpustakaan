; Installer Windows (Inno Setup 6). Dibangun oleh packaging/windows/build.ps1.
#define AppName "Penerima Tamu Perpustakaan"
#define AppExe "PenerimaTamu.exe"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{EBA07CCE-B47F-49D0-BB4C-89BDED7E9DD4}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
; Tanpa hak admin secara default (terpasang untuk user saat ini); bisa dipilih untuk semua user
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=PenerimaTamuPerpustakaan-{#AppVersion}-setup
SetupIconFile=..\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[CustomMessages]
AutoStart=Jalankan otomatis saat Windows dinyalakan (disarankan untuk PC kios)
OtherOptions=Opsi lain:
DataFolder=Folder Data (database, backup, .env)

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "{cm:AutoStart}"; GroupDescription: "{cm:OtherOptions}"; Flags: unchecked

[Files]
Source: "..\..\dist\PenerimaTamu\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\.env.example"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
; Data per user; tidak dihapus saat uninstall agar database & backup aman
Name: "{localappdata}\PenerimaTamuPerpustakaan"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:DataFolder}"; Filename: "{localappdata}\PenerimaTamuPerpustakaan"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: autostart

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
