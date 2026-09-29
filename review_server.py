#!/usr/bin/env python3
"""
Review server: serves the review pages of the dry runs, and applies the approved
changes straight from the browser, so there is no choices.json to download and
copy back to the server.

It listens on 127.0.0.1 only: put it behind your reverse proxy (HTTPS), e.g.
https://example.org/logos/ -> http://127.0.0.1:REVIEW_PORT/. Every request needs
the REVIEW_USER / REVIEW_PASSWORD login (HTTP Basic auth). The settings are read
from config.env, like the main script:

  REVIEW_PASSWORD  required: the server does not start without it
  REVIEW_USER      login name, default "plex"
  REVIEW_PORT      default 8787
  REVIEW_URL       public address of the server (used in the notifications)

Run it with: .venv/bin/python review_server.py (configure.py --review-server
installs it as a systemd user service).
"""
import base64
import hmac
import html
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import envfile

HERE = os.path.dirname(os.path.abspath(__file__))
envfile.load_into_environ(os.environ.get("PLEX_CONFIG", os.path.join(HERE, "config.env")))

LOGS_DIR = os.environ.get("PLEX_LOGS_DIR", os.path.join(HERE, "logs"))
PORT = int(os.environ.get("REVIEW_PORT", "8787"))
BIND = os.environ.get("REVIEW_BIND", "127.0.0.1")
USER = os.environ.get("REVIEW_USER", "plex") or "plex"
PASSWORD = os.environ.get("REVIEW_PASSWORD", "")
SCRIPT = os.path.join(HERE, "plex-smart-logo-updater.py")

# Dry-run folders only (never an application or undo folder)
RUN_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}h\d{2}m\d{2}_simulation(_\d+)?$")
ROUTE = re.compile(r"^/run/([^/]+)/(apply|status)?$")
STATE_FILE = "applied.json"        # in the dry run's folder, once an application was started
OUTPUT_FILE = "apply-output.txt"   # output of that application
MAX_BODY = 5 * 1024 * 1024
# Anti-CSRF token, embedded in the served pages and required to apply
TOKEN = secrets.token_urlsafe(24)
_LOCK = threading.Lock()
_SUMMARIES = {}  # review.html path -> (mtime, summary), so the index does not re-read big pages


def run_dir(name):
    """Folder of a dry run, or None when the name is not a dry run of the logs folder."""
    if not RUN_NAME.match(name):
        return None
    path = os.path.join(LOGS_DIR, name)
    return path if os.path.isfile(os.path.join(path, "review.html")) else None


def read_state(folder):
    try:
        with open(os.path.join(folder, STATE_FILE), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_state(folder, state):
    tmp = os.path.join(folder, STATE_FILE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, os.path.join(folder, STATE_FILE))


def tail(path, lines=40):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-lines:])
    except OSError:
        return ""


def is_full_run(folder):
    """A full dry run (all libraries), as opposed to a targeted one (Tautulli, --rating-key)."""
    try:
        with open(os.path.join(folder, "_summary.txt"), encoding="utf-8") as f:
            return "Selected    :" not in f.read()
    except OSError:
        return False


def outdated(folder):
    """
    True when a newer FULL dry run exists: its review page covers the same titles
    with fresher data, so this one must not be applied any more. Targeted runs
    (a new title added by Tautulli) stay valid until the next full run.
    """
    name = os.path.basename(folder)
    return any(n > name and RUN_NAME.match(n) and is_full_run(os.path.join(LOGS_DIR, n))
               for n in os.listdir(LOGS_DIR))


def status(folder):
    state = read_state(folder)
    if state is None:
        return {"state": "none", "outdated": outdated(folder)}
    output = tail(os.path.join(folder, OUTPUT_FILE))
    if state.get("exit") is None and not _alive(state.get("pid")):
        # The server restarted while the application was running, so its exit code was not
        # recorded: a run that went to the end prints its totals
        state.update(exit=0 if "TOTAL (" in output else -1, finished=state.get("started"))
        write_state(folder, state)
    return {"state": "running" if state.get("exit") is None else "done", "exit": state.get("exit"),
            "started": state.get("started"), "finished": state.get("finished"), "output": output}


def _alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def start_apply(folder, choices):
    """Writes choices.json and starts the application in the background. Returns an error or None."""
    with _LOCK:
        if read_state(folder) is not None:
            return "this dry run was already applied (or is being applied)"
        if outdated(folder):
            return "a newer dry run exists: open it from the list and apply that one"
        path = os.path.join(folder, "choices.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(choices, f, ensure_ascii=False, indent=1)
        out = open(os.path.join(folder, OUTPUT_FILE), "w", encoding="utf-8")
        proc = subprocess.Popen([sys.executable, SCRIPT, "--apply", "--choices", path, "--notify", "--quiet"],
                                cwd=HERE, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True)
        out.close()
        state = {"started": time.strftime("%Y-%m-%d %H:%M"), "pid": proc.pid, "exit": None, "finished": None}
        write_state(folder, state)

    def wait():
        code = proc.wait()
        state.update(exit=code, finished=time.strftime("%Y-%m-%d %H:%M"))
        write_state(folder, state)

    threading.Thread(target=wait, daemon=True).start()
    return None


def summary(folder):
    """(changes to review, titles to handle by hand) from the data embedded in review.html."""
    page = os.path.join(folder, "review.html")
    mtime = os.path.getmtime(page)
    cached = _SUMMARIES.get(page)
    if cached and cached[0] == mtime:
        return cached[1]
    with open(page, encoding="utf-8") as f:
        text = f.read()
    match = re.search(r'<script type="application/json" id="data">(.*?)</script>', text, re.S)
    try:
        cards = json.loads(match.group(1).replace("<\\/", "</"))["cards"] if match else []
    except ValueError:
        cards = []
    result = (sum(1 for c in cards if c.get("decidable")), sum(1 for c in cards if not c.get("decidable")))
    _SUMMARIES[page] = (mtime, result)
    return result


def index_page():
    names = sorted((n for n in os.listdir(LOGS_DIR) if run_dir(n)), reverse=True)[:30]
    rows = []
    for name in names:
        folder = os.path.join(LOGS_DIR, name)
        todo, manual = summary(folder)
        st = status(folder)
        if st["state"] == "running":
            label = "applying…"
        elif st["state"] == "done":
            label = "applied" if st["exit"] == 0 else "application failed"
        elif st.get("outdated"):
            label = "outdated (a newer dry run exists)"
        elif todo:
            label = f"<b>{todo} change(s) to review</b>"
        else:
            label = "nothing to review"
        extra = f", {manual} to do by hand" if manual else ""
        rows.append(f'<li><a href="run/{html.escape(name)}/">{html.escape(name)}</a> — {label}{extra}</li>')
    body = "<ul>" + "".join(rows) + "</ul>" if rows else "<p>No dry run with a review page yet.</p>"
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Plex logo review</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;max-width:760px;margin:24px auto;padding:0 16px;color:#1d2330}}
a{{color:#2f5fd0}} li{{margin:6px 0}}</style></head>
<body><h1>Plex logo review</h1><p>Latest dry runs (newest first):</p>{body}</body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "plex-smart-logo-updater"

    def log_message(self, fmt, *args):
        sys.stderr.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {self.address_string()} {fmt % args}\n")

    def authorized(self):
        header = self.headers.get("Authorization", "")
        if header.startswith("Basic "):
            try:
                user, _, password = base64.b64decode(header[6:]).decode("utf-8").partition(":")
            except ValueError:
                return False
            ok_user = hmac.compare_digest(user.encode(), USER.encode())
            ok_password = hmac.compare_digest(password.encode(), PASSWORD.encode())
            return ok_user and ok_password
        return False

    def send(self, code, body, content_type="text/html; charset=utf-8", headers=()):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, code, obj):
        self.send(code, json.dumps(obj), "application/json")

    def check(self):
        if self.authorized():
            return True
        self.send(401, "Login required", "text/plain; charset=utf-8",
                  [("WWW-Authenticate", 'Basic realm="Plex logo review", charset="UTF-8"')])
        return False

    def do_GET(self):
        if not self.check():
            return
        path = self.path.split("?", 1)[0]
        if path in ("/", ""):
            return self.send(200, index_page())
        match = ROUTE.match(path)
        if not match and re.match(r"^/run/[^/]+$", path):
            return self.send(301, "", headers=[("Location", path.rsplit("/", 1)[1] + "/")])
        folder = run_dir(match.group(1)) if match else None
        if folder is None:
            return self.send(404, "Not found", "text/plain; charset=utf-8")
        if match.group(2) == "status":
            return self.send_json(200, status(folder))
        if match.group(2) is None:
            with open(os.path.join(folder, "review.html"), encoding="utf-8") as f:
                page = f.read()
            inject = f"<script>window.REVIEW_SERVER = {json.dumps({'token': TOKEN})};</script>\n"
            return self.send(200, page.replace("</head>", inject + "</head>", 1))
        self.send(405, "Method not allowed", "text/plain; charset=utf-8")

    def do_POST(self):
        if not self.check():
            return
        match = ROUTE.match(self.path.split("?", 1)[0])
        folder = run_dir(match.group(1)) if match and match.group(2) == "apply" else None
        if folder is None:
            return self.send_json(404, {"error": "not found"})
        if not hmac.compare_digest(self.headers.get("X-Review-Token", ""), TOKEN):
            return self.send_json(403, {"error": "the page is out of date: reload it, then apply again"})
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_BODY:
            return self.send_json(400, {"error": "empty or too large request"})
        try:
            choices = json.loads(self.rfile.read(length))
        except ValueError:
            return self.send_json(400, {"error": "invalid JSON"})
        if not isinstance(choices, dict) or not isinstance(choices.get("decisions"), dict) \
                or choices.get("simulation") != os.path.basename(folder):
            return self.send_json(400, {"error": "these choices do not belong to this dry run"})
        error = start_apply(folder, choices)
        if error:
            return self.send_json(409, {"error": error})
        self.send_json(200, {"state": "running"})


def main():
    if not PASSWORD:
        sys.exit("REVIEW_PASSWORD is not set (config.env): the review server does not start without a password.")
    try:
        server = ThreadingHTTPServer((BIND, PORT), Handler)
    except OSError as e:
        sys.exit(f"Cannot listen on {BIND}:{PORT} ({e}): change REVIEW_PORT (configure.py --review-server).")
    print(f"Review server on http://{BIND}:{PORT}/ (logs: {LOGS_DIR})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
