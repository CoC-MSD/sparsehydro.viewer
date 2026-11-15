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
SetupIconFile=app.ico
UninstallDisplayIcon={app}\sparsehydro-viewer.exe
ChangesAssociations=yes

[Files]
Source: "..\dist\sparsehydro-viewer\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "app.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\SparseHydro Viewer"; Filename: "{app}\sparsehydro-viewer.exe"; IconFilename: "{app}\app.ico"; AppUserModelID: "sparsehydro.viewer"
Name: "{group}\Third-party notices"; Filename: "{app}\_internal\THIRD_PARTY_NOTICES.md"
Name: "{autodesktop}\SparseHydro Viewer"; Filename: "{app}\sparsehydro-viewer.exe"; IconFilename: "{app}\app.ico"; AppUserModelID: "sparsehydro.viewer"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "associate"; Description: "Open SparseHydro project files (.shproj) with SparseHydro Viewer"

[Registry]
; per-user (HKA follows the install mode) file association for project files
Root: HKA; Subkey: "Software\Classes\.shproj"; ValueType: string; ValueName: ""; ValueData: "SparseHydroViewer.Project"; Flags: uninsdeletevalue; Tasks: associate
Root: HKA; Subkey: "Software\Classes\SparseHydroViewer.Project"; ValueType: string; ValueName: ""; ValueData: "SparseHydro project"; Flags: uninsdeletekey; Tasks: associate
Root: HKA; Subkey: "Software\Classes\SparseHydroViewer.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\app.ico,0"; Tasks: associate
Root: HKA; Subkey: "Software\Classes\SparseHydroViewer.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\sparsehydro-viewer.exe"" ""%1"""; Tasks: associate

[Run]
Filename: "{app}\sparsehydro-viewer.exe"; Description: "Launch SparseHydro Viewer"; Flags: nowait postinstall skipifsilent
