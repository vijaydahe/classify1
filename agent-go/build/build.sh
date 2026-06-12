#!/bin/bash
# Cross-compile the ClassifyHub agent into compact, fully static, stripped,
# single-file binaries for Windows and macOS.
#
#   CGO_ENABLED=0  -> no libc linkage; a self-contained static binary with zero
#                     runtime/interpreter dependencies.
#   -trimpath      -> remove local filesystem paths (reproducible, no info leak).
#   -ldflags "-s -w" -> strip the symbol table (-s) and DWARF debug info (-w),
#                     producing a smaller binary with fewer AV heuristic triggers.
#   -buildvcs=false -> don't embed VCS metadata.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="${VERSION:-1.0.0}"
OUT="dist"
mkdir -p "$OUT"
LDFLAGS="-s -w -X main.version=${VERSION}"
COMMON=(-trimpath -buildvcs=false -ldflags "$LDFLAGS")
PKG="./cmd/classifyhub-agent"

echo "Building v${VERSION} (CGO_ENABLED=0, static, stripped)…"

# Windows x64
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build "${COMMON[@]}" \
  -o "$OUT/classifyhub-agent-windows-amd64.exe" "$PKG"

# macOS Intel + Apple Silicon
CGO_ENABLED=0 GOOS=darwin GOARCH=amd64 go build "${COMMON[@]}" \
  -o "$OUT/classifyhub-agent-darwin-amd64" "$PKG"
CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 go build "${COMMON[@]}" \
  -o "$OUT/classifyhub-agent-darwin-arm64" "$PKG"

# Stitch a macOS universal binary when lipo is available (macOS build hosts).
if command -v lipo >/dev/null 2>&1; then
  lipo -create -output "$OUT/classifyhub-agent-darwin-universal" \
    "$OUT/classifyhub-agent-darwin-amd64" "$OUT/classifyhub-agent-darwin-arm64"
  echo "  + universal macOS binary"
fi

echo "Artifacts:"
ls -lh "$OUT"
