// Package lifecycle manages the agent as a native OS background service
// (Windows Service via the SCM, macOS launchd daemon) and runs the scan loop.
// One statically linked binary both *is* the service and can install/remove it.
package lifecycle

import (
	"context"
	"encoding/json"
	"io"
	"log"
	"os"
	"path/filepath"
	"runtime"
	"time"

	"github.com/kardianos/service"

	"github.com/classifyhub/agent/internal/client"
	"github.com/classifyhub/agent/internal/config"
	"github.com/classifyhub/agent/internal/scan"
	"github.com/classifyhub/agent/internal/state"
)

const reportBatch = 200

// serviceConfig describes how the OS registers and runs the daemon. The
// settings are chosen so the service starts cleanly at boot and is recognised as
// a well-formed system service (not flagged as anomalous).
func serviceConfig() *service.Config {
	return &service.Config{
		Name:        "ClassifyHubAgent",
		DisplayName: "ClassifyHub Asset Scan Agent",
		Description: "Classifies local information assets and reports metadata to ClassifyHub.",
		// Run at boot as a system service; restart automatically if it exits.
		Option: service.KeyValue{
			"OnFailure":              "restart",
			"OnFailureDelayDuration": "5s",
			"RunAtLoad":              true, // launchd
			"KeepAlive":              true, // launchd
		},
	}
}

// program implements service.Interface: Start returns promptly and runs the
// work in a goroutine; Stop signals a clean shutdown.
type program struct {
	cancel context.CancelFunc
	done   chan struct{}
}

func (p *program) Start(s service.Service) error {
	ctx, cancel := context.WithCancel(context.Background())
	p.cancel = cancel
	p.done = make(chan struct{})
	go func() {
		defer close(p.done)
		runLoop(ctx)
	}()
	return nil
}

func (p *program) Stop(s service.Service) error {
	if p.cancel != nil {
		p.cancel()
	}
	select {
	case <-p.done:
	case <-time.After(10 * time.Second):
	}
	return nil
}

// New constructs the OS service handle for the agent.
func New() (service.Service, error) {
	return service.New(&program{}, serviceConfig())
}

// Control runs an install/uninstall/start/stop/restart action and reports status.
func Control(action string) error {
	svc, err := New()
	if err != nil {
		return err
	}
	return service.Control(svc, action)
}

// RunService hands control to the OS service manager (this is the entry the SCM
// / launchd invoke). When not running under a service manager it runs inline.
func RunService() error {
	svc, err := New()
	if err != nil {
		return err
	}
	return svc.Run()
}

// ScanOnce performs a single enroll-scan-deliver pass in the foreground and
// returns. Used for diagnostics ("does it work on this machine?") and by the
// installer to seed the first inventory without waiting for the service tick.
func ScanOnce() error {
	if f, err := os.OpenFile(logPath(), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644); err == nil {
		log.SetOutput(io.MultiWriter(os.Stdout, f))
	}
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	st, err := state.Open(filepath.Join(config.InstallDir(), "state.json"))
	if err != nil {
		return err
	}
	cycle(context.Background(), cfg, st, client.New(cfg.ServerURL))
	return nil
}

// logPath returns the agent's log file inside the install directory.
func logPath() string {
	return filepath.Join(config.InstallDir(), "agent.log")
}

// runLoop is the heart of the daemon: enroll, then scan → buffer → deliver on a
// fixed interval, draining any backlog accumulated while offline.
func runLoop(ctx context.Context) {
	if f, err := os.OpenFile(logPath(), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644); err == nil {
		log.SetOutput(f)
	}
	log.SetFlags(log.LstdFlags | log.LUTC)

	cfg, err := config.Load()
	if err != nil {
		log.Printf("FATAL config: %v", err)
		return
	}
	st, err := state.Open(filepath.Join(config.InstallDir(), "state.json"))
	if err != nil {
		log.Printf("FATAL state: %v", err)
		return
	}
	api := client.New(cfg.ServerURL)

	ticker := time.NewTicker(cfg.Interval())
	defer ticker.Stop()
	cycle(ctx, cfg, st, api) // run immediately on start
	for {
		select {
		case <-ctx.Done():
			log.Printf("shutdown requested")
			return
		case <-ticker.C:
			cycle(ctx, cfg, st, api)
		}
	}
}

// cycle performs one enroll-scan-deliver pass. Failures are logged and retried
// next tick; buffered results survive across cycles and restarts.
func cycle(ctx context.Context, cfg *config.Config, st *state.Store, api *client.Client) {
	apiKey, _ := st.Credentials()
	if apiKey == "" {
		host, _ := os.Hostname()
		plat := "macos"
		if runtime.GOOS == "windows" {
			plat = "windows"
		}
		key, id, err := api.Enroll(cfg.EnrollmentToken, host, plat)
		if err != nil {
			log.Printf("enroll failed: %v", err)
			return
		}
		if err := st.SetCredentials(key, id); err != nil {
			log.Printf("persist credentials: %v", err)
		}
		apiKey = key
		log.Printf("enrolled as endpoint %d", id)
	}

	rules, err := api.Rules(apiKey)
	if err != nil {
		// Offline: fall back to the cached rule set so scanning + buffering
		// continue. Only give up if we've never successfully fetched rules.
		if raw := st.CachedRules(); len(raw) > 0 {
			_ = json.Unmarshal(raw, &rules)
			log.Printf("fetch rules failed (%v); using %d cached rules", err, len(rules))
		} else {
			log.Printf("fetch rules failed and no cache yet: %v", err)
			deliver(ctx, st, api, apiKey)
			return
		}
	} else if raw, mErr := json.Marshal(rules); mErr == nil {
		_ = st.CacheRules(raw) // refresh the offline cache on every successful fetch
	}

	t0 := time.Now()
	engine := scan.NewEngine(rules, cfg.MaxFiles, cfg.MaxContentBytes, cfg.Workers)
	assets := engine.Run(cfg.ScanPaths, st.Seen)
	if len(assets) > 0 {
		if err := st.Enqueue(assets); err != nil {
			log.Printf("enqueue: %v", err)
		}
	}
	log.Printf("scanned %d new files in %s (%d queued)", len(assets),
		time.Since(t0).Round(time.Millisecond), st.OutboxLen())

	deliver(ctx, st, api, apiKey)
}

// deliver drains the durable outbox to the platform in batches, committing only
// what the server acknowledges. Anything undelivered stays buffered for later.
func deliver(ctx context.Context, st *state.Store, api *client.Client, apiKey string) {
	for st.OutboxLen() > 0 {
		select {
		case <-ctx.Done():
			return
		default:
		}
		batch := st.Drain(reportBatch)
		if _, err := api.Report(apiKey, batch); err != nil {
			log.Printf("report failed (will retry, %d buffered): %v", st.OutboxLen(), err)
			return // keep the backlog; next cycle retries
		}
		if err := st.Commit(len(batch)); err != nil {
			log.Printf("commit: %v", err)
			return
		}
	}
}
