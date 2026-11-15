; Inno Setup script for the Windows installer.
; Build after PyInstaller:  iscc /DAppVersion=1.2.3 packaging\installer.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6E0F2B54-6A5B-4C77-9D51-2C4B1C8F3A10}
AppName=SparseHydro Viewer
AppVersion={#AppVersion}
AppPublisher=sparsehydro contributors
AppPublisherURL=https://github.com/CoC-MSD/sparsehydro.viewer
DefaultDirName={autopf}\SparseHydro Viewer
DefaultGroupName=SparseHydro Viewer
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputBaseFilename=sparsehydro-viewer-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\dist\sparsehydro-viewer\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\SparseHydro Viewer"; Filename: "{app}\sparsehydro-viewer.exe"
Name: "{group}\Third-party notices"; Filename: "{app}\_internal\THIRD_PARTY_NOTICES.md"
Name: "{autodesktop}\SparseHydro Viewer"; Filename: "{app}\sparsehydro-viewer.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\sparsehydro-viewer.exe"; Description: "Launch SparseHydro Viewer"; Flags: nowait postinstall skipifsilent
