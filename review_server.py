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

Signing in (login page) opens a session for 30 days (cookie). Changing the
password signs every session out. HTTP Basic auth also works, for scripts.
"""
import base64
import hashlib
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
from urllib.parse import parse_qs, quote

import envfile
import html_report

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

COOKIE = "plexlogo_session"
SESSION_DAYS = 30
# Sessions are signed with a key derived from the login: changing the password signs everyone out
SESSION_KEY = hashlib.sha256(f"plex-smart-logo-updater session\0{USER}\0{PASSWORD}".encode()).digest()
MAX_FAILURES = 10           # failed sign-ins per address...
FAILURE_WINDOW = 15 * 60    # ...within this window, then sign-in is refused for a while
_FAILURES = {}


def new_session():
    expiry = str(int(time.time()) + SESSION_DAYS * 86400)
    return expiry + "." + hmac.new(SESSION_KEY, expiry.encode(), hashlib.sha256).hexdigest()


def valid_session(value):
    expiry, _, sig = (value or "").partition(".")
    if not expiry.isdigit() or int(expiry) < time.time():
        return False
    return hmac.compare_digest(sig, hmac.new(SESSION_KEY, expiry.encode(), hashlib.sha256).hexdigest())


def too_many_failures(address):
    now = time.time()
    recent = [t for t in _FAILURES.get(address, []) if now - t < FAILURE_WINDOW]
    _FAILURES[address] = recent
    return len(recent) >= MAX_FAILURES


def relative_root(path):
    """Relative link to the server's root from a path: the server may live under a prefix (/logos/)."""
    return "../" * (path.count("/") - 1) or "./"


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
    True when a newer dry run supersedes this one: a FULL dry run (it covers every
    title with fresher data), or a targeted one proposing all the same changes.
    Other targeted runs (a new title added by Tautulli) stay valid until then.
    """
    name = os.path.basename(folder)
    mine = None
    for n in os.listdir(LOGS_DIR):
        other = os.path.join(LOGS_DIR, n)
        if n <= name or not RUN_NAME.match(n):
            continue
        if is_full_run(other):
            return True
        if os.path.isfile(os.path.join(other, "review.html")):
            if mine is None:
                mine = set(summary(folder)["ids"])
            if mine and mine <= set(summary(other)["ids"]):
                return True
    return False


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
    """
    What a dry run's review page holds: changes to review, titles to do by hand,
    their titles, libraries and a few "after" thumbnails (read from the data
    embedded in review.html, cached by modification time).
    """
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
    todo = [c for c in cards if c.get("decidable")]
    result = {
        "todo": len(todo),
        "ids": sorted(c.get("id") for c in todo),
        "manual": len(cards) - len(todo),
        "titles": [c.get("title", "") for c in todo] or [c.get("title", "") for c in cards],
        "libraries": sorted({c.get("library", "") for c in cards if c.get("library")}),
        "thumbs": [(c.get("after"), c.get("asset") == "poster") for c in todo if c.get("after")][:4],
    }
    _SUMMARIES[page] = (mtime, result)
    return result


DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def run_date(name):
    """"2026-09-29_21h02m52_simulation" -> "Tue 29 Sep · 21:02"."""
    try:
        t = time.strptime(name[:19], "%Y-%m-%d_%Hh%Mm%S")
    except ValueError:
        return name
    return f"{DAYS[t.tm_wday]} {t.tm_mday} {MONTHS[t.tm_mon - 1]} · {t.tm_hour:02d}:{t.tm_min:02d}"


INDEX_CSS = """
header { padding: 24px 16px 4px; max-width: 1200px; margin: 0 auto; }
main { max-width: 1200px; margin: 0 auto; padding: 8px 16px 32px; }
.sec { font-size: 13px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); margin: 22px 0 10px; }
.grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); }
a { color: inherit; text-decoration: none; }
.run { background: var(--panel); border: 1px solid var(--line); border-left: 4px solid var(--accent);
  border-radius: 12px; padding: 14px; display: flex; flex-direction: column; gap: 10px; transition: transform .1s; }
.run:hover { transform: translateY(-1px); border-color: var(--accent); }
.run-head { display: flex; justify-content: space-between; gap: 8px; align-items: flex-start; }
.run-date { font-weight: 700; font-size: 16px; }
.pill { font-size: 12px; font-weight: 700; padding: 3px 9px; border-radius: 999px; white-space: nowrap;
  background: var(--bg); color: var(--muted); }
.pill.todo { background: var(--accent); color: #fff; }
.pill.ok { background: var(--ok-bg); color: var(--ok); }
.pill.no { background: var(--no-bg); color: var(--no); }
.pill.warn { background: var(--warn-bg); color: var(--warn); }
.thumbs { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
.thumb { background: var(--logo-bg); border-radius: 8px; height: 64px; display: flex; align-items: center;
  justify-content: center; padding: 5px; }
.thumb.poster { height: 110px; }
.thumb img { max-width: 100%; max-height: 100%; object-fit: contain; }
.run-titles { margin: 0; padding: 0; list-style: none; font-size: 13px; color: var(--muted); }
.run-titles li { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.run-titles li::before { content: "• "; }
.run .btn { text-align: center; margin-top: auto; }
.empty { background: var(--panel); border: 1px solid var(--line); border-left: 4px solid var(--ok);
  border-radius: 12px; padding: 18px; color: var(--muted); }
.empty b { color: var(--ok); }
.rows { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }
.row { display: flex; gap: 10px; align-items: center; padding: 10px 14px; border-top: 1px solid var(--line); }
.row:first-child { border-top: 0; }
.row:hover { background: var(--bg); }
.row .when { font-weight: 600; min-width: 150px; }
.row .what { flex: 1; color: var(--muted); font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row .pills { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
.logout { float: right; font-size: 13px; color: var(--muted); margin-top: 6px; }
.logout:hover { color: var(--accent); }
@media (max-width: 560px) { .row { flex-wrap: wrap; } .row .when { min-width: 0; } .row .what { flex-basis: 100%; order: 3; } }
"""


def index_page():
    names = sorted((n for n in os.listdir(LOGS_DIR) if run_dir(n)), reverse=True)[:30]
    todo_cards, rows = [], []
    for name in names:
        folder = os.path.join(LOGS_DIR, name)
        info = summary(folder)
        st = status(folder)
        esc = html.escape
        kind = "Full scan" if is_full_run(folder) else "New title (Tautulli)"
        where = " · ".join(info["libraries"][:3]) + (" …" if len(info["libraries"]) > 3 else "")
        pills = []
        if st["state"] == "running":
            pills.append('<span class="pill warn">Applying…</span>')
        elif st["state"] == "done":
            pills.append('<span class="pill ok">Applied</span>' if st["exit"] == 0
                         else '<span class="pill no">Application failed</span>')
        elif st.get("outdated"):
            pills.append('<span class="pill">Outdated</span>')
        elif info["todo"]:
            pills.append(f'<span class="pill todo">{info["todo"]} to review</span>')
        else:
            pills.append('<span class="pill">Nothing to review</span>')
        if info["manual"]:
            pills.append(f'<span class="pill warn">{info["manual"]} by hand</span>')
        actionable = st["state"] == "none" and not st.get("outdated") and info["todo"]
        if actionable:
            thumbs = "".join(f'<div class="thumb{" poster" if poster else ""}"><img src="{esc(src)}" alt=""></div>'
                             for src, poster in info["thumbs"])
            titles = "".join(f"<li>{esc(t)}</li>" for t in info["titles"][:4])
            more = len(info["titles"]) - 4
            if more > 0:
                titles += f"<li>and {more} more</li>"
            todo_cards.append(
                f'<a class="run" href="run/{esc(name)}/"><div class="run-head"><div>'
                f'<div class="run-date">{esc(run_date(name))}</div><div class="lib">{esc(kind)}'
                f'{" · " + esc(where) if where else ""}</div></div><div>{"".join(pills)}</div></div>'
                + (f'<div class="thumbs">{thumbs}</div>' if thumbs else "")
                + f'<ul class="run-titles">{titles}</ul><span class="btn primary">Open the review →</span></a>')
        else:
            what = ", ".join(info["titles"][:3]) or where or kind
            rows.append(f'<a class="row" href="run/{esc(name)}/"><span class="when">{esc(run_date(name))}</span>'
                        f'<span class="what">{esc(kind)} — {esc(what)}</span><span class="pills">{"".join(pills)}</span></a>')
    to_review = ('<div class="grid">' + "".join(todo_cards) + "</div>") if todo_cards else \
        '<div class="empty"><b>✓ All caught up.</b> Nothing waits for your review.</div>'
    history = f'<h2 class="sec">History</h2><div class="rows">{"".join(rows)}</div>' if rows else ""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Plex logo review</title>
<style>{html_report.THEME_CSS}{INDEX_CSS}</style></head>
<body><header><a class="logout" href="logout">Sign out</a><h1>Plex logo review</h1>
<div class="sub">Latest dry runs · open one to approve its changes and apply them</div></header>
<main><h2 class="sec">To review</h2>{to_review}{history}</main></body></html>"""


LOGIN_CSS = """
body { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 16px; }
.login { width: 100%; max-width: 360px; background: var(--panel); border: 1px solid var(--line);
  border-top: 4px solid var(--accent); border-radius: 14px; padding: 24px; }
.login h1 { margin-bottom: 2px; }
.login .sub { margin-bottom: 18px; }
label { display: block; font-size: 13px; font-weight: 600; margin: 12px 0 5px; }
input[type=text], input[type=password] { width: 100%; background: var(--bg); color: var(--text);
  border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; font-size: 15px; }
input:focus { outline: 2px solid var(--accent); outline-offset: 1px; border-color: var(--accent); }
.login .btn { width: 100%; margin-top: 18px; padding: 11px; font-size: 15px; }
.error { background: var(--no-bg); color: var(--no); border-radius: 8px; padding: 9px 12px; font-size: 13px; }
.note { background: var(--ok-bg); color: var(--ok); border-radius: 8px; padding: 9px 12px; font-size: 13px; }
"""


def login_page(next_path="", message="", error=True):
    box = f'<div class="{"error" if error else "note"}">{html.escape(message)}</div>' if message else ""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in · Plex logo review</title>
<style>{html_report.THEME_CSS}{LOGIN_CSS}</style></head>
<body><form class="login" method="post" action="login">
<h1>Plex logo review</h1><div class="sub">Sign in to review and apply the changes</div>{box}
<input type="hidden" name="next" value="{html.escape(next_path)}">
<label for="user">Login</label><input type="text" id="user" name="user" autocomplete="username" autocapitalize="none" required>
<label for="password">Password</label>
<input type="password" id="password" name="password" autocomplete="current-password" required autofocus>
<button class="btn primary" type="submit">Sign in</button></form></body></html>"""


# Where to go after signing in: only the home page or a dry run's page (no open redirect)
NEXT_PATH = re.compile(r"^(run/[^/]+/)?$")


class Handler(BaseHTTPRequestHandler):
    server_version = "plex-smart-logo-updater"

    def log_message(self, fmt, *args):
        sys.stderr.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {self.address_string()} {fmt % args}\n")

    def cookie(self, name):
        for part in self.headers.get("Cookie", "").split(";"):
            key, _, value = part.strip().partition("=")
            if key == name:
                return value
        return None

    def client(self):
        # Behind the reverse proxy, the client's address is in X-Forwarded-For
        return (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()

    def credentials_ok(self, user, password):
        ok_user = hmac.compare_digest(user.encode(), USER.encode())
        ok_password = hmac.compare_digest(password.encode(), PASSWORD.encode())
        return ok_user and ok_password

    def authorized(self):
        if valid_session(self.cookie(COOKIE)):
            return True
        header = self.headers.get("Authorization", "")
        if header.startswith("Basic "):
            try:
                user, _, password = base64.b64decode(header[6:]).decode("utf-8").partition(":")
            except ValueError:
                return False
            return self.credentials_ok(user, password)
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

    def check(self, path):
        """True when signed in; otherwise sends the sign-in page (or a JSON error for the page's requests)."""
        if self.authorized():
            return True
        if path.endswith(("/status", "/apply")):
            self.send_json(401, {"error": "you were signed out: reload the page and sign in again"})
        else:
            target = relative_root(path) + "login?next=" + quote(path.lstrip("/"))
            self.send(303, "", headers=[("Location", target)])
        return False

    def session_cookie(self, value, max_age):
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto", "") == "https" else ""
        return ("Set-Cookie", f"{COOKIE}={value}; Max-Age={max_age}; HttpOnly; SameSite=Lax{secure}")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/login":
            query = parse_qs(self.path.partition("?")[2])
            next_path = query.get("next", [""])[0]
            if self.authorized():
                return self.send(303, "", headers=[("Location", "./" + (next_path if NEXT_PATH.match(next_path) else ""))])
            message = "You are signed out." if "out" in query else ""
            return self.send(200, login_page(next_path if NEXT_PATH.match(next_path) else "", message, error=False))
        if path == "/logout":
            return self.send(303, "", headers=[("Location", "login?out=1"), self.session_cookie("", 0)])
        if not self.check(path):
            return
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
            inject = (f"<script>window.REVIEW_SERVER = {json.dumps({'token': TOKEN})};</script>\n"
                      "<style>.back { display: inline-block; font-size: 13px; color: var(--accent);"
                      " text-decoration: none; margin-bottom: 8px; }</style>\n")
            page = page.replace("</head>", inject + "</head>", 1)
            page = page.replace("<header>", '<header>\n  <a class="back" href="../../">← All dry runs</a>', 1)
            return self.send(200, page)
        self.send(405, "Method not allowed", "text/plain; charset=utf-8")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/login":
            return self.sign_in()
        if not self.check(path):
            return
        match = ROUTE.match(path)
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


    def sign_in(self):
        length = int(self.headers.get("Content-Length") or 0)
        form = parse_qs(self.rfile.read(min(length, 10000)).decode("utf-8", "replace")) if length else {}
        next_path = form.get("next", [""])[0]
        next_path = next_path if NEXT_PATH.match(next_path) else ""
        address = self.client()
        if too_many_failures(address):
            return self.send(429, login_page(next_path, "Too many failed attempts: try again in 15 minutes."))
        if self.credentials_ok(form.get("user", [""])[0], form.get("password", [""])[0]):
            _FAILURES.pop(address, None)
            return self.send(303, "", headers=[("Location", "./" + next_path),
                                               self.session_cookie(new_session(), SESSION_DAYS * 86400)])
        _FAILURES.setdefault(address, []).append(time.time())
        time.sleep(1)  # slows down password guessing
        self.send(401, login_page(next_path, "Wrong login or password."))


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
