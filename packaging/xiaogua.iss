; Inno Setup script for 每日一瓜 · 小瓜桌宠.  Built by: python packaging/build.py --installer
; Per-user install (no admin prompt), Start menu entry, desktop icon.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{C9176435-E78F-4774-9E13-802AEF823F9F}
AppName=每日一瓜
AppVersion={#AppVersion}
AppVerName=每日一瓜 {#AppVersion}
AppPublisher=hamburger-lie
AppPublisherURL=https://github.com/hamburger-lie/xiaogua-desktop-pet
AppSupportURL=https://github.com/hamburger-lie/xiaogua-desktop-pet/issues
DefaultDirName={localappdata}\Programs\XiaoguaDesktopPet
DefaultGroupName=每日一瓜
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=XiaoguaDesktopPet-Setup-{#AppVersion}
SetupIconFile=build\xiaogua.ico
UninstallDisplayIcon={app}\MeiriYigua.exe
UninstallDisplayName=每日一瓜（小瓜桌宠）
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
; The official Simplified Chinese translation (jrsoftware/issrc Files/Languages), kept here:
; Inno Setup 6.7 does not bundle it yet.
Name: "chs"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "在桌面放一个小瓜图标"

[Files]
Source: "dist\MeiriYigua\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\每日一瓜"; Filename: "{app}\MeiriYigua.exe"
Name: "{group}\卸载每日一瓜"; Filename: "{uninstallexe}"
Name: "{userdesktop}\每日一瓜"; Filename: "{app}\MeiriYigua.exe"; Tasks: desktopicon

[Registry]
; The app adds this Run value itself when "开机自动启动" is ticked; remove it on uninstall.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "xiaogua-desktop-pet"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\MeiriYigua.exe"; Description: "现在就叫小瓜出来"; Flags: nowait postinstall skipifsilent
