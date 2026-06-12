# ClassifyHub Agent SDK (Go)

An enterprise-grade endpoint scan agent compiled to a **single, statically
linked binary** with **zero runtime interpreter dependencies** (no Python, Node
or JVM). It installs itself as a native OS background service, scans local
information assets at high concurrency, and streams classified metadata to the
ClassifyHub cloud platform — buffering durably to disk when offline.

## Why Go

`CGO_ENABLED=0` yields a fully static binary that runs on a clean OS with nothing
preinstalled. Goroutines + channels give the scan engine extreme concurrency, and
one binary both *is* the service and can install/remove itself.

## Architecture

```
cmd/classifyhub-agent/main.go   CLI: install | uninstall | start | stop |
                                     restart | run | scan-once | version
internal/
  config/    self-contained config.json loader (no network for config)
  lifecycle/ native service manager (Windows SCM / macOS launchd) + scan loop
  scan/      concurrent walker + worker-pool scan engine (zero external binaries)
  state/     embedded, atomic, file-based store: credentials, dedup set,
             cached rules (for offline classification), durable outbox
  client/    stdlib HTTPS client (enroll / rules / report), bounded timeouts
build/
  build.sh                       static + stripped cross-compilation
  windows/classifyhub-agent.wxs  WiX v4 MSI definition
  macos/build_pkg.sh             signed .pkg builder + launchd daemon
```

### Module responsibilities

1. **Lifecycle Manager** (`internal/lifecycle`) — registers the agent with the
   Windows Service Control Manager / macOS launchd via `kardianos/service`
   (statically linked). `install` starts it at boot with auto-restart; `Stop`
   cancels a `context.Context` for a clean shutdown.
2. **Fast Scan Engine** (`internal/scan`) — a walker goroutine prunes noisy
   directories and feeds candidate paths into a buffered channel; a pool of
   `runtime.NumCPU()*4` workers reads and classifies files in parallel. Rules are
   pre-compiled once per pass. No external process is ever spawned.
3. **Local State Sync** (`internal/state`) — an atomic (temp-file + rename) JSON
   store. Scan results land in a durable **outbox**; delivery commits batches only
   after the server acknowledges them, so a disconnect or crash never loses data.
   A cached rule set lets the agent keep classifying while offline.

## Build

```bash
cd agent-go
./build/build.sh            # -> dist/ static, stripped binaries for win/mac
```

Exact flags used (also runnable directly):

```bash
# Windows x64
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 \
  go build -trimpath -buildvcs=false -ldflags "-s -w -X main.version=1.0.0" \
  -o dist/classifyhub-agent-windows-amd64.exe ./cmd/classifyhub-agent

# macOS Intel & Apple Silicon
CGO_ENABLED=0 GOOS=darwin GOARCH=amd64 \
  go build -trimpath -buildvcs=false -ldflags "-s -w -X main.version=1.0.0" \
  -o dist/classifyhub-agent-darwin-amd64 ./cmd/classifyhub-agent
CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 \
  go build -trimpath -buildvcs=false -ldflags "-s -w -X main.version=1.0.0" \
  -o dist/classifyhub-agent-darwin-arm64 ./cmd/classifyhub-agent
```

## Package into installers

- **Windows MSI**: `wix build build/windows/classifyhub-agent.wxs -d BinDir=../../dist -o ClassifyHubAgent.msi`
- **macOS PKG**: `./build/macos/build_pkg.sh`

Both must be **code-signed** (and the `.pkg` **notarized**) for friction-free,
non-flagged deployment — see `../agent/installers/SIGNING_AND_CERTIFICATION.md`.

## Run / operate

```bash
classifyhub-agent install     # install + start the system service
classifyhub-agent scan-once   # one diagnostic pass (foreground), then exit
classifyhub-agent stop        # stop the service
classifyhub-agent uninstall   # stop + remove the service
```

`config.json` (beside the binary) is the only required input:

```json
{
  "server_url": "https://classify1-chi.vercel.app",
  "enrollment_token": "enroll_xxx",
  "scan_paths": ["~/Documents", "~/Desktop", "~/Downloads"],
  "scan_interval_minutes": 60
}
```

Logs are written to `agent.log` in the install directory.

## A note on constraint #4 ("OS evasion")

This agent is built to run *cleanly* — registered as a well-formed system
service, no hidden processes, no anti-analysis tricks. The reliable way to avoid
quarantine/SmartScreen is **code signing + notarization**, not evasion. Software
engineered to dodge security tooling is what AV/EDR correctly flags as malware;
this agent deliberately does none of that.
