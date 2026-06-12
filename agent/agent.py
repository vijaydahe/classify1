#!/usr/bin/env python3
"""ClassifyHub endpoint agent.

Enrolls with the ClassifyHub server, pulls the tenant's classification rules,
scans the configured paths in parallel, classifies files locally, and reports
results back. Standard library only — runs on the stock Python 3 on macOS and
Windows.

    python3 agent.py            # enroll (first run), scan once, report
    python3 agent.py --daemon   # keep running, scan on the configured interval

Everything is logged to agent.log next to this file, so failures are visible
even when launched in the background by a scheduled task / LaunchAgent.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import os
import platform
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from logging.handlers import RotatingFileHandler
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
STATE_PATH = BASE_DIR / "state.json"
LOG_PATH = BASE_DIR / "agent.log"

TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".log", ".json", ".xml", ".yaml", ".yml",
                   ".ini", ".cfg", ".conf", ".env", ".py", ".js", ".ts", ".java",
                   ".go", ".rb", ".cs", ".cpp", ".sh", ".ps1", ".sql", ".html",
                   ".doc", ".docx", ".pdf", ".rtf", ".xls", ".xlsx", ".ppt", ".pptx"}
# Only these are content-scanned; everything else is classified by file name.
CONTENT_EXTENSIONS = {".txt", ".md", ".csv", ".log", ".json", ".xml", ".yaml", ".yml",
                      ".ini", ".cfg", ".conf", ".env", ".py", ".js", ".ts", ".java",
                      ".go", ".rb", ".cs", ".cpp", ".sh", ".ps1", ".sql", ".html"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "Library",
             ".Trash", "AppData", ".cache", "site-packages", ".npm"}
MAX_CONTENT_BYTES = 64 * 1024
MAX_FILES_PER_SCAN = 5000
REPORT_BATCH = 200
SCAN_WORKERS = min(16, (os.cpu_count() or 4) * 4)

log = logging.getLogger("classifyhub")


def setup_logging() -> None:
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh = RotatingFileHandler(LOG_PATH, maxBytes=512_000, backupCount=2)
    fh.setFormatter(fmt)
    log.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)


def api(server_url: str, path: str, payload: dict | None = None,
        api_key: str | None = None, timeout: int = 30) -> dict:
    url = server_url.rstrip("/") + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("X-Agent-Key", api_key)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except (ValueError, OSError):
            pass
    return {}


def save_state(state: dict) -> None:
    try:
        STATE_PATH.write_text(json.dumps(state))
    except OSError as e:
        log.warning("could not save state: %s", e)


def enroll(config: dict, state: dict) -> dict:
    if state.get("api_key"):
        return state
    log.info("enrolling with server %s", config["server_url"])
    result = api(config["server_url"], "/api/agent/enroll", {
        "enrollment_token": config["enrollment_token"],
        "hostname": socket.gethostname(),
        "platform": "windows" if platform.system() == "Windows" else "macos",
    })
    state["api_key"] = result["api_key"]
    state["endpoint_id"] = result["endpoint_id"]
    save_state(state)
    log.info("enrolled as endpoint %s", result["endpoint_id"])
    return state


def compile_rules(rules: list[dict]) -> list[dict]:
    """Pre-compile regex patterns and pre-split keywords once, for fast matching."""
    compiled = []
    for r in rules:
        item = dict(r)
        if r["type"] == "regex":
            try:
                item["_re"] = re.compile(r["pattern"])
            except re.error:
                continue
        else:
            item["_kw"] = [k.strip().lower() for k in r["pattern"].split(",") if k.strip()]
        compiled.append(item)
    return compiled


def classify(rules: list[dict], name: str, content: str):
    text = name + "\n" + content
    lowered = text.lower()
    matched = []
    for rule in rules:
        if "_re" in rule:
            if rule["_re"].search(text):
                matched.append(rule)
        elif any(kw in lowered for kw in rule["_kw"]):
            matched.append(rule)
    if not matched:
        return None, []
    winner = max(matched, key=lambda r: (r["level"], -r["priority"]))
    return winner["label"], [r["name"] for r in matched]


def iter_files(scan_paths: list[str]):
    """Yield candidate files, pruning noisy directories. Bounded by MAX_FILES_PER_SCAN."""
    yielded = 0
    for raw in scan_paths:
        root = Path(raw).expanduser()
        if not root.exists():
            log.info("scan path does not exist, skipping: %s", root)
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for fn in filenames:
                if fn.startswith("."):
                    continue
                if Path(fn).suffix.lower() not in TEXT_EXTENSIONS:
                    continue
                yield Path(dirpath) / fn
                yielded += 1
                if yielded >= MAX_FILES_PER_SCAN:
                    return


def process_file(path: Path, rules: list[dict]):
    """Read (if textual) + classify a single file. Runs in a thread pool."""
    content = ""
    if path.suffix.lower() in CONTENT_EXTENSIONS:
        try:
            with open(path, "rb") as f:
                content = f.read(MAX_CONTENT_BYTES).decode("utf-8", errors="replace")
        except OSError:
            return None
    label, matched = classify(rules, path.name, content)
    return {
        "name": str(path),
        "asset_type": "file",
        "label": label,
        "matched_rules": matched,
        "content_excerpt": content[:300],
    }


def scan(config: dict, rules: list[dict], already: set) -> list[dict]:
    """Parallel scan. Skips files already reported (incremental re-scans are fast)."""
    files = [p for p in iter_files(config.get("scan_paths", [])) if str(p) not in already]
    if not files:
        return []
    assets = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=SCAN_WORKERS) as pool:
        for result in pool.map(lambda p: process_file(p, rules), files):
            if result is not None:
                assets.append(result)
    return assets


def run_once(config: dict, state: dict) -> None:
    enroll(config, state)
    key = state["api_key"]
    t0 = time.perf_counter()
    raw_rules = api(config["server_url"], "/api/agent/rules", api_key=key)["rules"]
    rules = compile_rules(raw_rules)
    log.info("fetched %d classification rules", len(rules))

    already = set(state.get("reported", []))
    assets = scan(config, rules, already)
    log.info("scanned %d new files in %.1fs", len(assets), time.perf_counter() - t0)

    accepted = 0
    for i in range(0, len(assets), REPORT_BATCH):
        batch = assets[i:i + REPORT_BATCH]
        result = api(config["server_url"], "/api/agent/report",
                     {"assets": batch}, api_key=key)
        accepted += result.get("accepted", 0)
        for a in batch:
            already.add(a["name"])
    if assets:
        # Keep the reported set bounded; most recent names matter for dedup.
        state["reported"] = list(already)[-MAX_FILES_PER_SCAN * 2:]
        save_state(state)
        log.info("server accepted %d new assets", accepted)
    else:
        log.info("nothing new to report")


def main() -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="ClassifyHub endpoint agent")
    parser.add_argument("--daemon", action="store_true",
                        help="keep running, scanning at the configured interval")
    args = parser.parse_args()

    if not CONFIG_PATH.exists():
        log.error("config.json not found next to agent.py (%s)", CONFIG_PATH)
        return 1
    try:
        config = json.loads(CONFIG_PATH.read_text())
    except ValueError as e:
        log.error("config.json is not valid JSON: %s", e)
        return 1
    if not config.get("server_url") or not config.get("enrollment_token"):
        log.error("config.json must contain server_url and enrollment_token")
        return 1

    state = load_state()
    backoff = 30
    while True:
        try:
            run_once(config, state)
            backoff = 30  # reset after a clean run
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode()[:300]
            except Exception:
                pass
            log.error("server error %s: %s", e.code, body)
            # 402 (quota/plan) and 401 (bad key) won't fix themselves by retrying fast.
            if e.code in (401, 402, 403) and not args.daemon:
                return 2
        except urllib.error.URLError as e:
            log.error("cannot reach server: %s", e.reason)
        except Exception as e:  # never let the daemon die silently
            log.exception("unexpected error: %s", e)

        if not args.daemon:
            return 0
        interval = max(int(config.get("scan_interval_minutes", 60)), 1)
        log.info("sleeping %d minutes", interval)
        time.sleep(interval * 60)


if __name__ == "__main__":
    raise SystemExit(main())
