// Package client talks to the ClassifyHub cloud platform over HTTPS using only
// the standard library. All calls have bounded timeouts so a slow or
// unreachable server can never hang the agent.
package client

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/classifyhub/agent/internal/state"
)

// Client is a thin, timeout-bounded HTTP client for the platform API.
type Client struct {
	baseURL string
	http    *http.Client
}

// New returns a client for the given server base URL.
func New(baseURL string) *Client {
	return &Client{
		baseURL: baseURL,
		http:    &http.Client{Timeout: 30 * time.Second},
	}
}

// Rule is a classification rule pulled from the platform.
type Rule struct {
	Name     string `json:"name"`
	Type     string `json:"type"`
	Pattern  string `json:"pattern"`
	Label    string `json:"label"`
	Level    int    `json:"level"`
	Priority int    `json:"priority"`
}

// HTTPError carries the server's status code so the caller can react to
// 401/402/403 (auth/plan) differently from transient network failures.
type HTTPError struct {
	Code int
	Body string
}

func (e *HTTPError) Error() string { return fmt.Sprintf("server %d: %s", e.Code, e.Body) }

func (c *Client) do(method, path, apiKey string, in, out any) error {
	var body io.Reader
	if in != nil {
		b, err := json.Marshal(in)
		if err != nil {
			return err
		}
		body = bytes.NewReader(b)
	}
	req, err := http.NewRequest(method, c.baseURL+path, body)
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	if apiKey != "" {
		req.Header.Set("X-Agent-Key", apiKey)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if resp.StatusCode >= 400 {
		return &HTTPError{Code: resp.StatusCode, Body: string(raw)}
	}
	if out != nil {
		return json.Unmarshal(raw, out)
	}
	return nil
}

// Enroll registers this endpoint and returns its API key and id.
func (c *Client) Enroll(token, hostname, platform string) (apiKey string, endpointID int, err error) {
	var resp struct {
		APIKey     string `json:"api_key"`
		EndpointID int    `json:"endpoint_id"`
	}
	err = c.do(http.MethodPost, "/api/agent/enroll", "", map[string]string{
		"enrollment_token": token, "hostname": hostname, "platform": platform,
	}, &resp)
	return resp.APIKey, resp.EndpointID, err
}

// StampConfig is the tenant's document-stamping policy, returned with the rules.
type StampConfig struct {
	Enabled      bool              `json:"enabled"`
	Placement    string            `json:"placement"`
	TextTemplate string            `json:"text_template"`
	ColorByLabel map[string]string `json:"color_by_label"`
}

// Rules fetches the tenant's enabled classification rules and stamp policy.
func (c *Client) Rules(apiKey string) ([]Rule, *StampConfig, error) {
	var resp struct {
		Rules []Rule      `json:"rules"`
		Stamp StampConfig `json:"stamp"`
	}
	err := c.do(http.MethodGet, "/api/agent/rules", apiKey, nil, &resp)
	return resp.Rules, &resp.Stamp, err
}

// Report delivers a batch of assets; returns how many the server accepted.
func (c *Client) Report(apiKey string, assets []state.Asset) (int, error) {
	var resp struct {
		Accepted int `json:"accepted"`
	}
	err := c.do(http.MethodPost, "/api/agent/report", apiKey,
		map[string]any{"assets": assets}, &resp)
	return resp.Accepted, err
}
