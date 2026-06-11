#!/bin/bash
# Build a macOS installer package (.pkg) for the ClassifyHub agent.
# Run on macOS with the Xcode command line tools installed.
#
#   ./build_pkg.sh                      # unsigned (testing)
#   DEV_ID="Developer ID Installer: Acme (TEAMID)" ./build_pkg.sh   # signed
#
# Signing + notarization are required for distribution outside your own fleet:
#   productsign --sign "$DEV_ID" ClassifyHubAgent.pkg ClassifyHubAgent-signed.pkg
#   xcrun notarytool submit ClassifyHubAgent-signed.pkg --keychain-profile NOTARY --wait
#
# Managed-removal note: a .pkg has no built-in uninstaller, so a standard user
# cannot remove it through the UI. Deploy and lifecycle-manage via an MDM
# (Jamf, Intune, Kandji) — see agent/installers/MANAGED_DEPLOYMENT.md.
set -euo pipefail

VERSION="1.3.0"
IDENTIFIER="app.classifyhub.agent"
SRC_DIR="$(cd "$(dirname "$0")/../.." && pwd)"   # the agent/ directory
BUILD="$(mktemp -d)"
PKGROOT="$BUILD/root"
INSTALL_DIR="/Library/Application Support/ClassifyHub"

mkdir -p "$PKGROOT$INSTALL_DIR" "$PKGROOT/Library/LaunchDaemons" "$BUILD/scripts"
cp "$SRC_DIR/agent.py" "$PKGROOT$INSTALL_DIR/"
cp "$SRC_DIR/config.json" "$PKGROOT$INSTALL_DIR/" 2>/dev/null || true

# LaunchDaemon runs the agent for all users at boot (root-owned, admin to remove).
cat > "$PKGROOT/Library/LaunchDaemons/app.classifyhub.agent.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>app.classifyhub.agent</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>$INSTALL_DIR/agent.py</string>
    <string>--daemon</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardErrorPath</key><string>$INSTALL_DIR/agent.log</string>
</dict>
</plist>
PLIST

# postinstall loads the daemon immediately.
cat > "$BUILD/scripts/postinstall" <<'POST'
#!/bin/bash
launchctl load -w /Library/LaunchDaemons/app.classifyhub.agent.plist 2>/dev/null || true
exit 0
POST
chmod +x "$BUILD/scripts/postinstall"

pkgbuild \
  --root "$PKGROOT" \
  --scripts "$BUILD/scripts" \
  --identifier "$IDENTIFIER" \
  --version "$VERSION" \
  --install-location "/" \
  "ClassifyHubAgent.pkg"

if [[ -n "${DEV_ID:-}" ]]; then
  productsign --sign "$DEV_ID" ClassifyHubAgent.pkg ClassifyHubAgent-signed.pkg
  echo "Signed: ClassifyHubAgent-signed.pkg"
fi

rm -rf "$BUILD"
echo "Built ClassifyHubAgent.pkg (v$VERSION)"
