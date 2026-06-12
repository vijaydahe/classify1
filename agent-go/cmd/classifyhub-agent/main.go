// Command classifyhub-agent is the ClassifyHub endpoint scan agent: a single
// statically linked, dependency-free binary that installs itself as a native OS
// background service and streams classified asset metadata to the cloud
// platform.
//
//	classifyhub-agent install     install + start the system service
//	classifyhub-agent uninstall   stop + remove the system service
//	classifyhub-agent start|stop  control the running service
//	classifyhub-agent run         run in the foreground (service manager entry)
//	classifyhub-agent scan-once   one scan/report pass, then exit (diagnostics)
//	classifyhub-agent version     print version
package main

import (
	"fmt"
	"os"

	"github.com/classifyhub/agent/internal/lifecycle"
)

// version is injected at build time via -ldflags "-X main.version=...".
var version = "1.0.0"

func main() {
	cmd := "run"
	if len(os.Args) > 1 {
		cmd = os.Args[1]
	}

	switch cmd {
	case "install":
		must(lifecycle.Control("install"))
		_ = lifecycle.Control("start")
		fmt.Println("ClassifyHub agent installed and started as a system service.")
	case "uninstall":
		_ = lifecycle.Control("stop")
		must(lifecycle.Control("uninstall"))
		fmt.Println("ClassifyHub agent service removed.")
	case "start", "stop", "restart":
		must(lifecycle.Control(cmd))
		fmt.Printf("ClassifyHub agent %sed.\n", cmd)
	case "run":
		// Entry point the SCM / launchd invoke; blocks until the service stops.
		must(lifecycle.RunService())
	case "scan-once":
		must(lifecycle.ScanOnce())
	case "version", "--version", "-v":
		fmt.Printf("classifyhub-agent %s\n", version)
	default:
		fmt.Fprintf(os.Stderr, "unknown command %q\n\n", cmd)
		fmt.Fprintln(os.Stderr, "usage: classifyhub-agent {install|uninstall|start|stop|restart|run|scan-once|version}")
		os.Exit(2)
	}
}

func must(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}
