#!/bin/bash
# ClassifyHub endpoint agent installer for macOS.
# Installs the agent under ~/Library/Application Support and registers a
# LaunchAgent so it runs at login and scans on the configured interval.
set -euo pipefail

INSTALL_DIR="$HOME/Library/Application Support/ClassifyHub"
PLIST="$HOME/Library/LaunchAgents/com.classifyhub.agent.plist"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required. Install it from https://www.python.org or via Xcode CLT." >&2
  exit 1
fi

mkdir -p "$INSTALL_DIR" "$HOME/Library/LaunchAgents"
cp "$SRC_DIR/agent.py" "$SRC_DIR/config.json" "$INSTALL_DIR/"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.classifyhub.agent</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(command -v python3)</string>
    <string>$INSTALL_DIR/agent.py</string>
    <string>--daemon</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$INSTALL_DIR/agent.log</string>
  <key>StandardErrorPath</key><string>$INSTALL_DIR/agent.log</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "ClassifyHub agent installed. Logs: $INSTALL_DIR/agent.log"
echo "Run once now with: python3 \"$INSTALL_DIR/agent.py\""
