// Package state is an embedded, file-based store. It persists enrollment
// credentials, the set of already-reported assets (for fast incremental
// re-scans), and a durable outbox that buffers scan results when the agent is
// disconnected from the cloud platform. No external database is required.
package state

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
)

// Asset is one scanned item queued for delivery to the platform.
type Asset struct {
	Name           string   `json:"name"`
	AssetType      string   `json:"asset_type"`
	Label          string   `json:"label,omitempty"`
	MatchedRules   []string `json:"matched_rules"`
	ContentExcerpt string   `json:"content_excerpt"`
}

// persisted is the full on-disk shape of state.json.
type persisted struct {
	APIKey     string          `json:"api_key"`
	EndpointID int             `json:"endpoint_id"`
	Reported   map[string]bool `json:"reported"`
	Outbox     []Asset         `json:"outbox"`
	RulesRaw   json.RawMessage `json:"rules_cache,omitempty"`
}

// Store is a concurrency-safe wrapper around the persisted state file. Writes
// are atomic (temp file + rename) so a crash never corrupts the store.
type Store struct {
	path string
	mu   sync.Mutex
	data persisted
}

// Open loads (or initializes) the state store at the given path.
func Open(path string) (*Store, error) {
	s := &Store{path: path, data: persisted{Reported: map[string]bool{}}}
	raw, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return s, nil
		}
		return nil, err
	}
	_ = json.Unmarshal(raw, &s.data) // tolerate a partial file; we re-enroll if needed
	if s.data.Reported == nil {
		s.data.Reported = map[string]bool{}
	}
	return s, nil
}

func (s *Store) flushLocked() error {
	tmp := s.path + ".tmp"
	b, err := json.Marshal(s.data)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(s.path), 0o755); err != nil {
		return err
	}
	if err := os.WriteFile(tmp, b, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, s.path) // atomic on the same filesystem
}

// Credentials returns the stored enrollment key and endpoint id.
func (s *Store) Credentials() (apiKey string, endpointID int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.data.APIKey, s.data.EndpointID
}

// SetCredentials persists the enrollment result.
func (s *Store) SetCredentials(apiKey string, endpointID int) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.data.APIKey = apiKey
	s.data.EndpointID = endpointID
	return s.flushLocked()
}

// CacheRules stores the latest rule set (raw JSON) so the agent can keep
// classifying and buffering while disconnected from the platform.
func (s *Store) CacheRules(raw json.RawMessage) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.data.RulesRaw = raw
	return s.flushLocked()
}

// CachedRules returns the last cached rule set, or nil if none.
func (s *Store) CachedRules() json.RawMessage {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.data.RulesRaw
}

// Seen reports whether a file path has already been reported to the platform.
func (s *Store) Seen(name string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.data.Reported[name]
}

// Enqueue buffers assets in the durable outbox (call when a scan produces results).
func (s *Store) Enqueue(assets []Asset) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.data.Outbox = append(s.data.Outbox, assets...)
	return s.flushLocked()
}

// Drain returns up to n buffered assets without removing them (peek for sending).
func (s *Store) Drain(n int) []Asset {
	s.mu.Lock()
	defer s.mu.Unlock()
	if n > len(s.data.Outbox) {
		n = len(s.data.Outbox)
	}
	out := make([]Asset, n)
	copy(out, s.data.Outbox[:n])
	return out
}

// Commit removes the first n assets from the outbox and marks them reported.
// Call this only after the platform has acknowledged delivery.
func (s *Store) Commit(n int) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if n > len(s.data.Outbox) {
		n = len(s.data.Outbox)
	}
	for _, a := range s.data.Outbox[:n] {
		s.data.Reported[a.Name] = true
	}
	s.data.Outbox = append([]Asset(nil), s.data.Outbox[n:]...)
	return s.flushLocked()
}

// OutboxLen returns the number of buffered, undelivered assets.
func (s *Store) OutboxLen() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.data.Outbox)
}
