// Package config loads the agent's self-contained configuration. Everything the
// agent needs at runtime lives in a single JSON file shipped beside the binary,
// so the agent never reaches the internet for configuration.
package config

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"time"
)

// Config is the on-disk agent configuration (config.json next to the binary).
type Config struct {
	ServerURL       string   `json:"server_url"`
	EnrollmentToken string   `json:"enrollment_token"`
	ScanPaths       []string `json:"scan_paths"`
	ScanIntervalMin int      `json:"scan_interval_minutes"`
	MaxFiles        int      `json:"max_files_per_scan"`
	MaxContentBytes int      `json:"max_content_bytes"`
	Workers         int      `json:"workers"`
}

// Defaults applied when fields are omitted.
const (
	defaultInterval    = 60
	defaultMaxFiles    = 50000
	defaultContentSize = 64 * 1024
)

// InstallDir returns the per-platform directory where the agent and its state
// live. CLASSIFYHUB_DIR overrides it (useful in containers and tests).
func InstallDir() string {
	if d := os.Getenv("CLASSIFYHUB_DIR"); d != "" {
		return d
	}
	if runtime.GOOS == "windows" {
		base := os.Getenv("ProgramData")
		if base == "" {
			base = os.Getenv("LOCALAPPDATA")
		}
		return filepath.Join(base, "ClassifyHub")
	}
	return "/Library/Application Support/ClassifyHub"
}

// Path returns the absolute path to config.json beside the running binary,
// falling back to the platform install directory.
func Path() string {
	if exe, err := os.Executable(); err == nil {
		p := filepath.Join(filepath.Dir(exe), "config.json")
		if _, err := os.Stat(p); err == nil {
			return p
		}
	}
	return filepath.Join(InstallDir(), "config.json")
}

// Load reads and validates the configuration, applying defaults.
func Load() (*Config, error) {
	raw, err := os.ReadFile(Path())
	if err != nil {
		return nil, err
	}
	var c Config
	if err := json.Unmarshal(raw, &c); err != nil {
		return nil, errors.New("config.json is not valid JSON: " + err.Error())
	}
	if c.ServerURL == "" || c.EnrollmentToken == "" {
		return nil, errors.New("config.json must set server_url and enrollment_token")
	}
	if c.ScanIntervalMin <= 0 {
		c.ScanIntervalMin = defaultInterval
	}
	if c.MaxFiles <= 0 {
		c.MaxFiles = defaultMaxFiles
	}
	if c.MaxContentBytes <= 0 {
		c.MaxContentBytes = defaultContentSize
	}
	if c.Workers <= 0 {
		c.Workers = runtime.NumCPU() * 4
	}
	if len(c.ScanPaths) == 0 {
		c.ScanPaths = defaultScanPaths()
	}
	c.ScanPaths = expandPaths(c.ScanPaths)
	return &c, nil
}

// expandPaths resolves ~ and environment variables in configured scan paths so
// hand-edited configs ("~/Documents", "%USERPROFILE%\\Docs") work as expected.
func expandPaths(paths []string) []string {
	home, _ := os.UserHomeDir()
	out := make([]string, 0, len(paths))
	for _, p := range paths {
		p = os.ExpandEnv(p)
		if p == "~" {
			p = home
		} else if strings.HasPrefix(p, "~/") || strings.HasPrefix(p, `~\`) {
			p = filepath.Join(home, p[2:])
		}
		out = append(out, p)
	}
	return out
}

// Interval returns the scan interval as a duration.
func (c *Config) Interval() time.Duration {
	return time.Duration(c.ScanIntervalMin) * time.Minute
}

func defaultScanPaths() []string {
	home, _ := os.UserHomeDir()
	if home == "" {
		return nil
	}
	return []string{
		filepath.Join(home, "Documents"),
		filepath.Join(home, "Desktop"),
		filepath.Join(home, "Downloads"),
	}
}
