; ClassifyHub endpoint agent — Inno Setup script (produces a Windows .exe installer)
;
; Build (on Windows, with Inno Setup 6 installed):
;   iscc /DAgentDir=..\..  classifyhub-agent.iss
; Sign the output for production:
;   signtool sign /fd SHA256 /a /tr http://timestamp.digicert.com /td SHA256 Output\ClassifyHubAgentSetup.exe
;
; Managed-removal note: PrivilegesRequired=admin means a standard user cannot
; install or uninstall the agent — removal requires a local administrator. For
; fleets, deploy and lifecycle-manage this via Intune / Group Policy (see
; agent/installers/MANAGED_DEPLOYMENT.md) rather than relying on per-machine controls.

#ifndef AgentDir
  #define AgentDir "..\.."
#endif
#define AppVersion "1.3.0"

[Setup]
AppId={{B6F4B7E2-7C2A-4F3D-9E1A-CLASSIFYHUB01}
AppName=ClassifyHub Agent
AppVersion={#AppVersion}
AppPublisher=ClassifyHub
DefaultDirName={autopf}\ClassifyHub
DefaultGroupName=ClassifyHub
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=ClassifyHub Agent
OutputBaseFilename=ClassifyHubAgentSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "{#AgentDir}\agent.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#AgentDir}\config.json"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist

[Run]
; Register a per-machine scheduled task that runs the agent at logon in daemon mode.
Filename: "schtasks"; \
  Parameters: "/Create /F /SC ONLOGON /RL HIGHEST /TN ""ClassifyHubAgent"" /TR ""python \""{app}\agent.py\"" --daemon"""; \
  Flags: runhidden

[UninstallRun]
Filename: "schtasks"; Parameters: "/Delete /F /TN ""ClassifyHubAgent"""; Flags: runhidden; RunOnceId: "DelTask"
