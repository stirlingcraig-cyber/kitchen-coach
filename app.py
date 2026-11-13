"""Kitchen Coach - local recipe engine and web server (Windows desktop build).

Serves the Kitchen Coach app from the web/ folder and reads uploaded recipes with
recipe_parser.py. It only ever listens on 127.0.0.1 - it is not reachable from other devices.

Run directly for development:   python app.py          (then open http://127.0.0.1:8765)
Normal use goes through launcher.py, which also opens the app window and shuts the server
down when the window is closed.
"""
from __future__ import annotations

import logging
import mimetypes
import sys
import threading
import time
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge

from recipe_parser import RecipeError, parse_recipe

VERSION = "1.0.0"
APP_ID = "kitchen-coach"
MAX_UPLOAD = 15 * 1024 * 1024  # 15 MB

# Windows takes MIME types from the registry, where .js is sometimes "text/plain" - which
# stops the browser running the app's JavaScript modules. Pin the types we serve.
for _ext, _mime in {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
                    ".svg": "image/svg+xml", ".webmanifest": "application/manifest+json",
                    ".json": "application/json", ".png": "image/png", ".pdf": "application/pdf",
                    ".html": "text/html"}.items():
    mimetypes.add_type(_mime, _ext)

log = logging.getLogger("kitchen_coach")


def resource_dir() -> Path:
    """The web/ folder, both when run from source and inside the PyInstaller build."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "web"


class Presence:
    """Tracks whether an app window is still open (heartbeats from the page)."""

    def __init__(self):
        self.started = time.time()
        self.last_seen: float | None = None
        self.bye_at: float | None = None
        self.lock = threading.Lock()

    def seen(self):
        with self.lock:
            self.last_seen = time.time()

    def bye(self):
        with self.lock:
            self.bye_at = time.time()

    def should_exit(self, now: float | None = None, idle_limit=180, startup_limit=120, bye_grace=20) -> bool:
        now = now or time.time()
        with self.lock:
            if self.last_seen is None:
                return now - self.started > startup_limit
            if self.bye_at and self.bye_at >= self.last_seen and now - self.bye_at > bye_grace:
                return True
            return now - self.last_seen > idle_limit


def create_app(web_dir: Path | None = None, local_only: bool = True) -> Flask:
    web = Path(web_dir or resource_dir())
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD
    app.presence = Presence()

    @app.before_request
    def only_local():
        # Blocks DNS-rebinding tricks: the page must be addressed as this computer.
        host = (request.host or "").rsplit(":", 1)[0].strip("[]")
        if local_only and host not in {"127.0.0.1", "localhost", "::1"}:
            abort(403)

    @app.after_request
    def headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers.setdefault("Cache-Control", "no-cache")
        return resp

    @app.get("/api/health")
    def health():
        app.presence.seen()
        return jsonify(app=APP_ID, version=VERSION)

    @app.post("/api/heartbeat")
    def heartbeat():
        app.presence.seen()
        return ("", 204)

    @app.post("/api/bye")
    def bye():
        app.presence.bye()
        return ("", 204)

    @app.post("/api/parse")
    def parse():
        uploaded = request.files.get("recipe")
        if not uploaded or not uploaded.filename:
            return jsonify(error="Choose a recipe file first."), 400
        data = uploaded.read()
        try:
            result = parse_recipe(Path(uploaded.filename).name, data)
        except RecipeError as exc:
            return jsonify(error=str(exc)), 422
        except Exception:  # never show a stack trace to the cook
            log.exception("Unexpected error reading %s", uploaded.filename)
            return jsonify(error="Sorry - that file couldn't be read. It may be damaged or in an unusual format."), 500
        return jsonify(result)

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_exc):
        return jsonify(error="That file is over 15 MB - please upload a smaller recipe file."), 413

    @app.errorhandler(404)
    def not_found(_exc):
        if request.path.startswith("/api/"):
            return jsonify(error="Not found"), 404
        return send_from_directory(web, "index.html")

    @app.get("/")
    def index():
        return send_from_directory(web, "index.html")

    @app.get("/<path:filename>")
    def static_files(filename):
        return send_from_directory(web, filename)  # safe_join inside blocks ../ escapes

    return app


app = create_app()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Local testing only. Do not expose this server publicly.
    app.run(host="127.0.0.1", port=8765, debug=False)
