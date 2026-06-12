# Code signing & certification — so the agent isn't treated as malware

The agent's own code is harmless, but operating systems judge *unsigned*
downloads harshly: macOS Gatekeeper says "cannot verify it is free of malware"
and Windows SmartScreen / Defender warn or block. The fix is **code signing**
plus, on macOS, **notarization**. Here is exactly what to obtain for each
platform and what each step buys you.

## Windows

| What to get | From | Cost (approx) | Removes |
|---|---|---|---|
| **OV code-signing certificate** (Authenticode) | DigiCert, Sectigo, GlobalSign | ~$200–400 / yr | The "unknown publisher" warning; shows your company name on the UAC prompt |
| **EV code-signing certificate** (Extended Validation) | Same CAs | ~$300–600 / yr | The same, **plus immediate SmartScreen reputation** (no "Windows protected your PC" wait) |

Notes:
- As of 2023 both OV and EV certs are issued on **hardware tokens / HSM**
  (FIPS 140-2). You sign with `signtool` pointing at the token, or use a cloud
  signing service (DigiCert KeyLocker, Azure Trusted Signing).
- **Azure Trusted Signing** (~$10/mo) is the cheapest modern path and gives
  Microsoft-backed reputation; recommended for a SaaS starting out.
- Sign **both** the `.exe` and `.msi`:
  `signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a file`
- Timestamping (`/tr`) is essential — it keeps signatures valid after the cert
  expires.

## macOS

| What to get | From | Cost | Removes |
|---|---|---|---|
| **Apple Developer Program** membership | Apple | $99 / yr | Prerequisite for everything below |
| **Developer ID Application** certificate | Apple (via Xcode/Developer portal) | included | Signs the agent binary/scripts |
| **Developer ID Installer** certificate | Apple | included | Signs the `.pkg` installer |
| **Notarization** (not a cert — an Apple service) | Apple `notarytool` | included | The Gatekeeper "cannot verify free of malware" block entirely |

Flow on a Mac:
1. `productsign --sign "Developer ID Installer: Your Co (TEAMID)" in.pkg out.pkg`
2. `xcrun notarytool submit out.pkg --apple-id … --team-id … --password … --wait`
3. `xcrun stapler staple out.pkg`  (so it verifies even offline)

After notarization + stapling, the `.pkg` installs with no warnings.

## "Python wrapping" caveat

The agent currently runs as a `.py` under the system Python. For a clean signed
distribution you'll want a **self-contained executable** so end users don't need
Python and so there's a single binary to sign:

- Build with **PyInstaller** (`pyinstaller --onefile agent.py`) on each OS.
- Then sign that binary (Windows: `signtool`; macOS: `codesign --options runtime`
  with a Developer ID Application cert, then notarize).
- The CI workflow `.github/workflows/build-agents.yml` is the place to add these
  steps; wire your certificates in as encrypted GitHub Actions secrets.

## Building trust beyond signing (reduces AV false-positives)

Signing stops the OS prompts; these reduce antivirus heuristic flags:

- **Submit your signed binaries** to Microsoft (Defender) and major AV vendors
  for allow-listing / reputation seeding.
- Keep the cert and publisher name **stable** — reputation accrues to the
  signing identity over time and downloads.
- Avoid behaviors that look malicious: no process injection, no hidden windows,
  no obfuscation. (The agent already avoids all of these.)

## Enterprise / compliance certifications (separate from code signing)

If a customer's procurement asks about *organizational* certification — that is
not about the binary but about your SaaS:

- **SOC 2 Type II** — the usual ask from US enterprises.
- **ISO/IEC 27001** — the global equivalent.
- These cover ClassifyHub the service, and are earned via an audit, not bought.

## Bottom line / recommended minimum

- **Windows:** Azure Trusted Signing (or an EV cert) — kills SmartScreen warnings.
- **macOS:** Apple Developer Program ($99/yr) → Developer ID + notarization.

Until those are in place, the agent still works; users just have to clear the
quarantine / "Run anyway" prompts documented in the package README.
