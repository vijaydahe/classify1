#!/usr/bin/env python3
"""ClassifyHub agent — graphical installer (wizard) for Windows and macOS.

Double-clickable, standard-library only (Tkinter ships with Python). It copies
the agent into the per-user install location, registers it to run at every
login, and runs an initial scan — showing progress in a window instead of a
console that flashes and closes.

  Windows:  installs to %LOCALAPPDATA%\\ClassifyHub, registers a Scheduled Task
  macOS:    installs to ~/Library/Application Support/ClassifyHub, loads a LaunchAgent
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import ttk

IS_WIN = platform.system() == "Windows"
SRC_DIR = Path(__file__).resolve().parent
INSTALL_DIR = (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ClassifyHub" if IS_WIN
               else Path.home() / "Library" / "Application Support" / "ClassifyHub")
TASK_NAME = "ClassifyHubAgent"
PLIST = Path.home() / "Library" / "LaunchAgents" / "app.classifyhub.agent.plist"


def python_exe() -> str:
    return sys.executable or ("python" if IS_WIN else "python3")


def read_config() -> dict:
    try:
        return json.loads((SRC_DIR / "config.json").read_text())
    except Exception:
        return {}


class Installer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ClassifyHub Agent — Setup")
        self.geometry("520x420")
        self.resizable(False, False)
        cfg = read_config()

        tk.Label(self, text="ClassifyHub Agent", font=("Helvetica", 20, "bold")).pack(pady=(22, 2))
        tk.Label(self, text="Automatic data-classification endpoint agent",
                 fg="#555").pack()

        info = tk.Frame(self); info.pack(pady=18, padx=24, fill="x")
        rows = [("Server", cfg.get("server_url", "—")),
                ("Platform", "Windows" if IS_WIN else "macOS"),
                ("Install to", str(INSTALL_DIR)),
                ("Runs at", "every login (background)")]
        for i, (k, v) in enumerate(rows):
            tk.Label(info, text=k + ":", anchor="w", width=10, fg="#555").grid(row=i, column=0, sticky="w")
            tk.Label(info, text=v, anchor="w", wraplength=360, justify="left").grid(row=i, column=1, sticky="w")

        self.btn = tk.Button(self, text="Install", font=("Helvetica", 13, "bold"),
                             bg="#4f46e5", fg="white", activebackground="#4338ca",
                             relief="flat", padx=24, pady=8, command=self.start)
        self.btn.pack(pady=6)

        self.bar = ttk.Progressbar(self, mode="determinate", length=460, maximum=100)
        self.bar.pack(pady=(6, 4))
        self.log = tk.Text(self, height=7, width=62, bg="#0f172a", fg="#e2e8f0",
                           font=("Menlo", 10), relief="flat")
        self.log.pack(padx=24, pady=8)

    def say(self, msg: str, pct: int | None = None):
        self.log.insert("end", msg + "\n"); self.log.see("end")
        if pct is not None:
            self.bar["value"] = pct
        self.update_idletasks()

    def start(self):
        self.btn.config(state="disabled")
        threading.Thread(target=self.install, daemon=True).start()

    def install(self):
        try:
            self.say("Copying agent files…", 15)
            INSTALL_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SRC_DIR / "agent.py", INSTALL_DIR / "agent.py")
            if (SRC_DIR / "config.json").exists():
                shutil.copy2(SRC_DIR / "config.json", INSTALL_DIR / "config.json")
            if (SRC_DIR / "stamp.py").exists():
                shutil.copy2(SRC_DIR / "stamp.py", INSTALL_DIR / "stamp.py")

            agent = INSTALL_DIR / "agent.py"
            self.say("Registering to run at every login…", 45)
            if IS_WIN:
                subprocess.run(["schtasks", "/Create", "/F", "/SC", "ONLOGON", "/RL", "HIGHEST",
                                "/TN", TASK_NAME,
                                "/TR", f'"{python_exe()}" "{agent}" --daemon'],
                               check=True, capture_output=True, text=True)
            else:
                PLIST.parent.mkdir(parents=True, exist_ok=True)
                PLIST.write_text(self._plist(agent))
                subprocess.run(["launchctl", "unload", str(PLIST)], capture_output=True)
                subprocess.run(["launchctl", "load", str(PLIST)], capture_output=True)

            self.say("Running first scan… (this can take a minute)", 70)
            r = subprocess.run([python_exe(), str(agent)], capture_output=True, text=True, timeout=600)
            for line in (r.stdout or "").splitlines()[-4:]:
                self.say("  " + line)
            if r.returncode != 0 and r.stderr:
                self.say("  " + r.stderr.strip().splitlines()[-1])

            self.say("\n✅ Installed. The agent runs automatically at every login.", 100)
            self.say("You can close this window.")
        except subprocess.CalledProcessError as e:
            self.say("\n❌ Install step failed:")
            self.say((e.stderr or str(e)).strip()[:400])
            self.btn.config(state="normal", text="Retry")
        except Exception as e:  # keep the window open so the error is readable
            self.say(f"\n❌ {type(e).__name__}: {e}")
            self.btn.config(state="normal", text="Retry")

    def _plist(self, agent: Path) -> str:
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>app.classifyhub.agent</string>
  <key>ProgramArguments</key>
  <array><string>{python_exe()}</string><string>{agent}</string><string>--daemon</string></array>
  <key>RunAtLoad</key><true/>
  <key>StandardErrorPath</key><string>{INSTALL_DIR / "agent.log"}</string>
</dict></plist>
"""


if __name__ == "__main__":
    Installer().mainloop()
