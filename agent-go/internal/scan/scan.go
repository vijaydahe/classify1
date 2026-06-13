// Package scan is a high-performance, concurrent file/metadata scanner. It makes
// zero external binary calls — everything uses the Go standard library. A walker
// goroutine feeds a buffered channel that a pool of worker goroutines drains,
// reading and classifying files in parallel.
package scan

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"

	"github.com/classifyhub/agent/internal/client"
	"github.com/classifyhub/agent/internal/state"
)

// contentExts are read for content matching; other extensions classify by name.
var contentExts = set(".txt", ".md", ".csv", ".log", ".json", ".xml", ".yaml",
	".yml", ".ini", ".cfg", ".conf", ".env", ".py", ".js", ".ts", ".java", ".go",
	".rb", ".cs", ".cpp", ".sh", ".ps1", ".sql", ".html")

// candidateExts are considered at all (everything else is ignored).
var candidateExts = union(contentExts, set(".doc", ".docx", ".pdf", ".rtf",
	".xls", ".xlsx", ".ppt", ".pptx"))

// skipDirs are pruned during the walk to avoid noise and wasted I/O.
var skipDirs = set(".git", "node_modules", "__pycache__", ".venv", "venv",
	"site-packages", "Library", ".Trash", "AppData", ".cache", ".npm")

// compiledRule is a rule with its regex pre-compiled / keywords pre-split.
type compiledRule struct {
	name     string
	label    string
	level    int
	priority int
	re       *regexp.Regexp
	keywords []string
}

// Engine holds the immutable, pre-compiled rule set for a scan pass.
type Engine struct {
	rules           []compiledRule
	maxFiles        int
	maxContentBytes int
	workers         int
}

// NewEngine pre-compiles rules once so per-file matching is allocation-light.
func NewEngine(rules []client.Rule, maxFiles, maxContentBytes, workers int) *Engine {
	e := &Engine{maxFiles: maxFiles, maxContentBytes: maxContentBytes, workers: workers}
	for _, r := range rules {
		cr := compiledRule{name: r.Name, label: r.Label, level: r.Level, priority: r.Priority}
		if r.Type == "regex" {
			re, err := regexp.Compile(r.Pattern)
			if err != nil {
				continue // skip malformed rules rather than failing the scan
			}
			cr.re = re
		} else {
			for _, kw := range strings.Split(r.Pattern, ",") {
				if kw = strings.ToLower(strings.TrimSpace(kw)); kw != "" {
					cr.keywords = append(cr.keywords, kw)
				}
			}
		}
		e.rules = append(e.rules, cr)
	}
	return e
}

// Run scans all roots concurrently and returns assets not already reported.
func (e *Engine) Run(roots []string, seen func(string) bool) []state.Asset {
	paths := make(chan string, 1024)
	results := make(chan state.Asset, 1024)

	// Walker: prune noisy dirs, emit candidate files, respect the file cap.
	go func() {
		defer close(paths)
		emitted := 0
		for _, root := range roots {
			_ = filepath.WalkDir(root, func(p string, d os.DirEntry, err error) error {
				if err != nil {
					return nil // unreadable entry: skip, don't abort the walk
				}
				if d.IsDir() {
					if skipDirs[d.Name()] || strings.HasPrefix(d.Name(), ".") {
						return filepath.SkipDir
					}
					return nil
				}
				name := d.Name()
				if strings.HasPrefix(name, ".") || !candidateExts[strings.ToLower(filepath.Ext(name))] {
					return nil
				}
				if seen(p) {
					return nil
				}
				paths <- p
				emitted++
				if emitted >= e.maxFiles {
					return filepath.SkipAll
				}
				return nil
			})
		}
	}()

	// Worker pool: read + classify in parallel.
	var wg sync.WaitGroup
	for i := 0; i < e.workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for p := range paths {
				if a, ok := e.process(p); ok {
					results <- a
				}
			}
		}()
	}
	go func() { wg.Wait(); close(results) }()

	var assets []state.Asset
	for a := range results {
		assets = append(assets, a)
	}
	return assets
}

func (e *Engine) process(path string) (state.Asset, bool) {
	var content string
	if contentExts[strings.ToLower(filepath.Ext(path))] {
		f, err := os.Open(path)
		if err != nil {
			return state.Asset{}, false
		}
		buf := make([]byte, e.maxContentBytes)
		n, _ := f.Read(buf)
		f.Close()
		content = string(buf[:n])
	}
	label, matched := e.classify(filepath.Base(path), content)
	excerpt := content
	if len(excerpt) > 300 {
		excerpt = excerpt[:300]
	}
	return state.Asset{
		Name: path, AssetType: "file", Label: label,
		MatchedRules: matched, ContentExcerpt: excerpt,
	}, true
}

// classify returns the highest-sensitivity matching label and the rule names.
func (e *Engine) classify(name, content string) (string, []string) {
	text := name + "\n" + content
	lower := strings.ToLower(text)
	var matched []compiledRule
	for _, r := range e.rules {
		if r.re != nil {
			if r.re.MatchString(text) {
				matched = append(matched, r)
			}
			continue
		}
		for _, kw := range r.keywords {
			if strings.Contains(lower, kw) {
				matched = append(matched, r)
				break
			}
		}
	}
	if len(matched) == 0 {
		// Non-nil so JSON encodes [] not null (the server expects a list).
		return "", []string{}
	}
	best := matched[0]
	names := make([]string, 0, len(matched))
	for _, r := range matched {
		names = append(names, r.name)
		if r.level > best.level || (r.level == best.level && r.priority < best.priority) {
			best = r
		}
	}
	return best.label, names
}

func set(items ...string) map[string]bool {
	m := make(map[string]bool, len(items))
	for _, i := range items {
		m[i] = true
	}
	return m
}

func union(a, b map[string]bool) map[string]bool {
	m := make(map[string]bool, len(a)+len(b))
	for k := range a {
		m[k] = true
	}
	for k := range b {
		m[k] = true
	}
	return m
}
