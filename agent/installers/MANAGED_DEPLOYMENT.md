# Managed deployment & uninstall protection

The ClassifyHub endpoint agent is meant to be deployed and lifecycle-managed
centrally, the same way every enterprise DLP/endpoint agent is. This is how you
achieve "users cannot remove it" **correctly** — through device management,
not through anti-tamper tricks.

## Why not "truly impossible to uninstall"?

Software engineered to resist removal by the machine's own administrator is
indistinguishable from malware persistence, and Windows Defender / macOS
Gatekeeper / third-party EDR will quarantine it. It also creates real liability
(a device you cannot clean) and breaks the moment the OS updates. The supported,
durable approach below makes the agent **un-removable by standard users** and
**centrally controlled by IT**, which is what compliance frameworks actually
require.

## Windows

The provided installers set `PrivilegesRequired=admin` (EXE) and
`Scope=perMachine` + `ARPNOREMOVE=1` (MSI), so:

- A standard (non-admin) user cannot install or uninstall the agent.
- The MSI hides the "Uninstall" button in Add/Remove Programs.

For a fleet, deploy the MSI through one of:

- **Microsoft Intune**: upload the `.msi` (or wrap the `.exe` as a Win32 app),
  assign it as *Required* to a device group. Mark it "uninstall not allowed".
  Intune re-installs it if removed.
- **Group Policy**: publish the MSI to the *Computer Configuration → Software
  Installation* node; set it to *not* allow user removal.

To stop even local admins from casually removing it, restrict the scheduled
task and install directory ACLs to SYSTEM/Administrators and audit changes via
GPO — but the OS administrator can always remove software, by design.

## macOS

The `.pkg` installs a root-owned LaunchDaemon under `/Library`, which a standard
user cannot unload or delete. For a fleet, deploy through an **MDM** (Jamf,
Intune, Kandji, Mosyle):

- Push the signed, notarized `.pkg` as a managed package.
- Wrap removal protection with a **configuration profile** and, on supervised
  devices, restrict the agent files/daemon so only the MDM can manage them.
- The MDM redeploys the agent if it is removed.

## Code signing (required for distribution)

- **Windows**: Authenticode-sign the `.exe`/`.msi` with `signtool` using an OV/EV
  certificate, or SmartScreen will warn users.
- **macOS**: sign with a *Developer ID Installer* certificate (`productsign`) and
  **notarize** with `notarytool`, or Gatekeeper blocks the package.

CI builds both installers automatically — see
`.github/workflows/build-agents.yml`. Provide signing secrets in the repo to
have CI sign them too.
