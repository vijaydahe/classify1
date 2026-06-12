#!/bin/bash
# Build a signed, standardized macOS .pkg for the ClassifyHub Go agent.
# Run on macOS (Xcode CLT installed). The universal binary is built first by
# build/build.sh; this packages and (optionally) signs + notarizes it.
#
#   ./build_pkg.sh                                    # unsigned (testing)
#   APP_ID="Developer ID Application: Acme (TEAM)" \
#   INSTALLER_ID="Developer ID Installer: Acme (TEAM)" ./build_pkg.sh
#
# Notarize (removes Gatekeeper "cannot verify free of malware"):
#   xcrun notarytool submit ClassifyHubAgent.pkg --keychain-profile NOTARY --wait
#   xcrun stapler staple ClassifyHubAgent.pkg
set -euo pipefail

VERSION="1.0.0"
IDENTIFIER="app.classifyhub.agent"
DIST="$(cd "$(dirname "$0")/../../dist" && pwd)"
BUILD="$(mktemp -d)"
ROOT="$BUILD/root"
INSTALL_DIR="/Library/Application Support/ClassifyHub"
LAUNCH_DAEMON="/Library/LaunchDaemons/app.classifyhub.agent.plist"

mkdir -p "$ROOT$INSTALL_DIR" "$ROOT/Library/LaunchDaemons" "$BUILD/scripts"

# Prefer a universal binary if present, else arm64.
BIN="$DIST/classifyhub-agent-darwin-universal"
[[ -f "$BIN" ]] || BIN="$DIST/classifyhub-agent-darwin-arm64"
cp "$BIN" "$ROOT$INSTALL_DIR/classifyhub-agent"
chmod 755 "$ROOT$INSTALL_DIR/classifyhub-agent"
cp "$DIST/config.json" "$ROOT$INSTALL_DIR/config.json" 2>/dev/null || true

# Sign the binary with a Developer ID Application cert + hardened runtime.
if [[ -n "${APP_ID:-}" ]]; then
  codesign --force --options runtime --timestamp \
    --sign "$APP_ID" "$ROOT$INSTALL_DIR/classifyhub-agent"
fi

# launchd daemon: root-owned, runs at boot, restarts on exit.
cat > "$ROOT$LAUNCH_DAEMON" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>app.classifyhub.agent</string>
  <key>ProgramArguments</key>
  <array>
    <string>$INSTALL_DIR/classifyhub-agent</string>
    <string>run</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>StandardErrorPath</key><string>$INSTALL_DIR/agent.log</string>
</dict></plist>
PLIST

# postinstall loads the daemon immediately.
cat > "$BUILD/scripts/postinstall" <<POST
#!/bin/bash
launchctl load -w "$LAUNCH_DAEMON" 2>/dev/null || true
exit 0
POST
chmod +x "$BUILD/scripts/postinstall"

pkgbuild --root "$ROOT" --scripts "$BUILD/scripts" \
  --identifier "$IDENTIFIER" --version "$VERSION" \
  --install-location "/" "$BUILD/component.pkg"

if [[ -n "${INSTALLER_ID:-}" ]]; then
  productbuild --package "$BUILD/component.pkg" --sign "$INSTALLER_ID" ClassifyHubAgent.pkg
else
  cp "$BUILD/component.pkg" ClassifyHubAgent.pkg
fi

rm -rf "$BUILD"
echo "Built ClassifyHubAgent.pkg (v$VERSION)"
