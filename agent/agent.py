#!/usr/bin/env python3
"""ClassifyHub endpoint agent.

Enrolls with the ClassifyHub server using the enrollment token in config.json,
pulls the tenant's classification rules, scans the configured paths, classifies
files locally, and reports the results back. Uses only the Python standard
library so it runs on a stock Python 3 install on macOS and Windows.

Usage:
    python3 agent.py            # enroll (first run), scan once, report
    python3 agent.py --daemon   # scan repeatedly at the configured interval
"""
# Keep PEP 604 type hints (dict | None) working on the Python 3.8/3.9 that ships
# with macOS — this defers annotation evaluation so they never run at import.
from __future__ import annotations

import argparse
import json
import platform
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"
STATE_PATH = Path(__file__).parent / "state.json"

TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".log", ".json", ".xml", ".yaml", ".yml",
                   ".ini", ".cfg", ".conf", ".env", ".py", ".js", ".ts", ".java",
                   ".go", ".rb", ".cs", ".cpp", ".sh", ".ps1", ".sql", ".html"}
MAX_CONTENT_BYTES = 64 * 1024
MAX_FILES_PER_SCAN = 2000


def api(server_url: str, path: str, payload: dict | None = None,
        api_key: str | None = None, method: str | None = None) -> dict:
    url = server_url.rstrip("/") + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"))
    req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("X-Agent-Key", api_key)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def enroll(config: dict) -> dict:
    state = {}
    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text())
    if state.get("api_key"):
        return state
    print("[agent] enrolling with server...")
    result = api(config["server_url"], "/api/agent/enroll", {
        "enrollment_token": config["enrollment_token"],
        "hostname": socket.gethostname(),
        "platform": "windows" if platform.system() == "Windows" else "macos",
    })
    state = {"api_key": result["api_key"], "endpoint_id": result["endpoint_id"]}
    STATE_PATH.write_text(json.dumps(state))
    print(f"[agent] enrolled as endpoint {result['endpoint_id']}")
    return state


def classify(rules: list[dict], name: str, content: str) -> tuple[str | None, list[str]]:
    text = f"{name}\n{content}"
    matched = []
    for rule in rules:
        try:
            if rule["type"] == "regex":
                if re.search(rule["pattern"], text):
                    matched.append(rule)
            else:
                lowered = text.lower()
                if any(kw.strip().lower() in lowered
                       for kw in rule["pattern"].split(",") if kw.strip()):
                    matched.append(rule)
        except re.error:
            continue
    if not matched:
        return None, []
    winner = max(matched, key=lambda r: (r["level"], -r["priority"]))
    return winner["label"], [r["name"] for r in matched]


def scan(config: dict, rules: list[dict]) -> list[dict]:
    assets, seen = [], 0
    for raw_path in config.get("scan_paths", []):
        root = Path(raw_path).expanduser()
        if not root.exists():
            continue
        for file in root.rglob("*"):
            if seen >= MAX_FILES_PER_SCAN:
                break
            if not file.is_file() or file.name.startswith("."):
                continue
            seen += 1
            content = ""
            if file.suffix.lower() in TEXT_EXTENSIONS:
                try:
                    content = file.read_bytes()[:MAX_CONTENT_BYTES].decode("utf-8", errors="replace")
                except OSError:
                    pass
            label, matched = classify(rules, file.name, content)
            assets.append({
                "name": str(file),
                "asset_type": "file",
                "label": label,
                "matched_rules": matched,
                "content_excerpt": content[:300],
            })
    return assets


def run_once(config: dict) -> None:
    state = enroll(config)
    rules = api(config["server_url"], "/api/agent/rules",
                api_key=state["api_key"])["rules"]
    print(f"[agent] fetched {len(rules)} classification rules")
    assets = scan(config, rules)
    print(f"[agent] scanned {len(assets)} files")
    if assets:
        result = api(config["server_url"], "/api/agent/report",
                     {"assets": assets}, api_key=state["api_key"])
        print(f"[agent] server accepted {result['accepted']} assets")


def main() -> int:
    parser = argparse.ArgumentParser(description="ClassifyHub endpoint agent")
    parser.add_argument("--daemon", action="store_true",
                        help="keep running, scanning at the configured interval")
    args = parser.parse_args()

    if not CONFIG_PATH.exists():
        print("config.json not found next to agent.py", file=sys.stderr)
        return 1
    config = json.loads(CONFIG_PATH.read_text())

    while True:
        try:
            run_once(config)
        except urllib.error.HTTPError as e:
            print(f"[agent] server error {e.code}: {e.read().decode()}", file=sys.stderr)
        except urllib.error.URLError as e:
            print(f"[agent] cannot reach server: {e.reason}", file=sys.stderr)
        if not args.daemon:
            return 0
        interval = config.get("scan_interval_minutes", 60)
        print(f"[agent] sleeping {interval} minutes")
        time.sleep(interval * 60)


if __name__ == "__main__":
    raise SystemExit(main())
