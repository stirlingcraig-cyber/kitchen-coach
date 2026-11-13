"""Kitchen Coach launcher for Windows.

* starts the local recipe engine (app.py) on http://127.0.0.1:8765
* opens Kitchen Coach in its own app-style window (Microsoft Edge or Chrome "app mode",
  falling back to your default browser)
* if Kitchen Coach is already running, just opens another window
* shuts the engine down automatically a short while after the window is closed

Usage:  KitchenCoach.exe            (or: pythonw launcher.py)
        KitchenCoach.exe --browser  (open in a normal browser tab instead of an app window)
        KitchenCoach.exe --no-window --port 8765   (server only, for testing)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

APP_ID = "kitchen-coach"
DEFAULT_PORT = 8765


def data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    path = Path(base) / "KitchenCoach"
    path.mkdir(parents=True, exist_ok=True)
    return path


def setup_logging() -> None:
    log_file = data_dir() / "kitchen_coach.log"
    try:
        if log_file.exists() and log_file.stat().st_size > 1_000_000:
            log_file.replace(log_file.with_suffix(".old.log"))
    except OSError:
        pass
    # A windowed .exe has no console: send any stray output to the log instead of crashing.
    if sys.stdout is None or sys.stderr is None:
        stream = open(log_file, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream
    logging.basicConfig(filename=log_file, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def running_instance(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.5) as resp:
            return json.load(resp).get("app") == APP_ID
    except Exception:
        return False


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def find_app_browser() -> str | None:
    candidates = []
    for env in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        root = os.environ.get(env)
        if root:
            candidates += [Path(root) / "Microsoft/Edge/Application/msedge.exe",
                           Path(root) / "Google/Chrome/Application/chrome.exe"]
    for c in candidates:
        if c.is_file():
            return str(c)
    for name in ("msedge", "microsoft-edge", "google-chrome", "chrome", "chromium"):
        found = shutil.which(name)
        if found:
            return found
    return None


def open_window(url: str, plain_browser: bool = False) -> None:
    exe = None if plain_browser else find_app_browser()
    if exe:
        profile = data_dir() / "window-profile"  # keeps saved recipes in one place
        args = [exe, f"--app={url}", f"--user-data-dir={profile}", "--window-size=1180,880",
                "--no-first-run", "--no-default-browser-check", "--autoplay-policy=no-user-gesture-required"]
        try:
            subprocess.Popen(args, close_fds=True)
            logging.info("Opened app window with %s", exe)
            return
        except OSError:
            logging.exception("Could not start %s", exe)
    webbrowser.open(url)
    logging.info("Opened in default browser")


def watchdog(presence) -> None:
    while True:
        time.sleep(5)
        if presence.should_exit():
            logging.info("No app window open - shutting down")
            os._exit(0)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Kitchen Coach")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--browser", action="store_true", help="use a normal browser tab")
    parser.add_argument("--no-window", action="store_true", help="start the engine only")
    parser.add_argument("--keep-running", action="store_true", help="don't stop when the window closes")
    args = parser.parse_args(argv)

    setup_logging()
    port = args.port
    url = f"http://127.0.0.1:{port}/"

    if running_instance(port):
        logging.info("Already running - opening another window")
        if not args.no_window:
            open_window(url, args.browser)
        return 0

    if not port_free(port):
        # Something else owns the usual port. Saved recipes live with the port, so warn in the log.
        for candidate in range(port + 1, port + 20):
            if port_free(candidate):
                logging.warning("Port %s busy; using %s (recipes saved on %s won't show)", port, candidate, port)
                port, url = candidate, f"http://127.0.0.1:{candidate}/"
                break
        else:
            logging.error("No free port found")
            return 1

    from app import create_app  # imported late so a second launch opens instantly

    flask_app = create_app()
    if not args.keep_running and not args.no_window:
        threading.Thread(target=watchdog, args=(flask_app.presence,), daemon=True).start()
    if not args.no_window:
        threading.Timer(0.8, open_window, args=(url, args.browser)).start()

    logging.info("Kitchen Coach engine on %s", url)
    try:
        from waitress import serve
        serve(flask_app, host="127.0.0.1", port=port, threads=6, _quiet=True)
    except ImportError:
        flask_app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
