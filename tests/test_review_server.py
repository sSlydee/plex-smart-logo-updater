"""review_server.py: login, paths, anti-CSRF token and the apply flow (the application itself is faked)."""
import base64
import importlib
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from test_main import main  # noqa: F401  (fixture: the main script, isolated from the real config)

RUN = "2026-09-29_20h15m01_simulation"


@pytest.fixture
def server(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    (logs / RUN).mkdir(parents=True)
    data = {"format": "plex-smart-logo-updater/choices-v1", "simulation": RUN, "apply": False,
            "cards": [{"id": "7", "decidable": True}, {"id": "8", "decidable": False}]}
    (logs / RUN / "review.html").write_text(
        '<html><head></head><body><script type="application/json" id="data">'
        + json.dumps(data) + "</script></body></html>", encoding="utf-8")
    (logs / "2026-09-29_21h00m00_application").mkdir()
    monkeypatch.setenv("PLEX_CONFIG", str(tmp_path / "missing.env"))
    monkeypatch.setenv("PLEX_LOGS_DIR", str(logs))
    monkeypatch.setenv("REVIEW_PASSWORD", "secret")
    monkeypatch.setenv("REVIEW_USER", "plex")
    import review_server
    rs = importlib.reload(review_server)
    # The application is faked: a short Python command instead of the real script
    fake = tmp_path / "fake_apply.py"
    fake.write_text("import sys; print('Applying', sys.argv[1:]); print('TOTAL (0 min 01 s)')\n")
    monkeypatch.setattr(rs, "SCRIPT", str(fake))
    httpd = rs.ThreadingHTTPServer(("127.0.0.1", 0), rs.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield rs, f"http://127.0.0.1:{httpd.server_address[1]}", logs
    httpd.shutdown()


def request(url, auth=("plex", "secret"), data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=dict(headers or {}))
    if auth:
        req.add_header("Authorization", "Basic " + base64.b64encode(":".join(auth).encode()).decode())
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def raw(url, data=None, headers=None):
    """Request without following redirects: (status, headers, body)."""
    req = urllib.request.Request(url, data=data, headers=dict(headers or {}))
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=10) as r:
            return r.status, r.headers, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read().decode()


def sign_in(base, user="plex", password="secret", next_path=""):
    form = urllib.parse.urlencode({"user": user, "password": password, "next": next_path}).encode()
    return raw(base + "/login", data=form, headers={"Content-Type": "application/x-www-form-urlencoded"})


def test_signed_out_visitors_get_the_login_page(server):
    _, base, _ = server
    status, headers, _ = raw(base + f"/run/{RUN}/")
    assert status == 303 and headers["Location"] == f"../../login?next=run/{RUN}/"
    status, _, body = raw(base + "/login")
    assert status == 200 and 'type="password"' in body
    assert raw(base + f"/run/{RUN}/status")[0] == 401
    assert request(base + "/", auth=("plex", "wrong"))[0] in (303, 200)  # Basic auth: wrong -> login page


def test_sign_in_opens_a_session(server):
    _, base, _ = server
    status, headers, _ = sign_in(base, next_path=f"run/{RUN}/")
    assert status == 303 and headers["Location"] == f"./run/{RUN}/"
    cookie = headers["Set-Cookie"].split(";")[0]
    assert "HttpOnly" in headers["Set-Cookie"] and "SameSite=Lax" in headers["Set-Cookie"]
    status, _, body = raw(base + "/", headers={"Cookie": cookie})
    assert status == 200 and "1 to review" in body and "Sign out" in body
    # a forged or expired session does not work
    assert raw(base + "/", headers={"Cookie": "plexlogo_session=9999999999.forged"})[0] == 303
    assert raw(base + "/", headers={"Cookie": "plexlogo_session=1.x"})[0] == 303


def test_wrong_password_and_open_redirect(server, monkeypatch):
    rs, base, _ = server
    monkeypatch.setattr(rs.time, "sleep", lambda s: None)  # no 1 s penalty in tests
    status, _, body = sign_in(base, password="wrong")
    assert status == 401 and "Wrong login or password" in body
    status, headers, _ = sign_in(base, next_path="https://evil.example/")
    assert status == 303 and headers["Location"] == "./"


def test_too_many_failed_sign_ins(server, monkeypatch):
    rs, base, _ = server
    monkeypatch.setattr(rs.time, "sleep", lambda s: None)
    for _ in range(rs.MAX_FAILURES):
        sign_in(base, password="wrong")
    status, _, body = sign_in(base)  # even the right password is refused for a while
    assert status == 429 and "Too many" in body


def sign_out(base, rs, cookie, token=None):
    form = urllib.parse.urlencode({"token": rs.TOKEN if token is None else token}).encode()
    return raw(base + "/logout", data=form, headers={"Cookie": cookie})


def test_sign_out(server):
    rs, base, _ = server
    cookie = sign_in(base)[1]["Set-Cookie"].split(";")[0]
    status, headers, _ = sign_out(base, rs, cookie)
    assert status == 303 and "Max-Age=0" in headers["Set-Cookie"]


def test_sign_out_needs_a_post_with_the_token(server):
    rs, base, _ = server
    cookie = sign_in(base)[1]["Set-Cookie"].split(";")[0]
    raw(base + "/logout", headers={"Cookie": cookie})     # GET (e.g. an <img> on another site)
    sign_out(base, rs, cookie, token="forged")              # cross-site POST without the page token
    assert raw(base + "/", headers={"Cookie": cookie})[0] == 200


def test_changing_the_password_signs_everyone_out(server, monkeypatch):
    rs, base, _ = server
    cookie = sign_in(base)[1]["Set-Cookie"].split(";")[0]
    monkeypatch.setattr(rs, "SESSION_KEY", b"key derived from a new password")
    assert raw(base + "/", headers={"Cookie": cookie})[0] == 303


def test_only_dry_run_folders_are_served(server):
    _, base, _ = server
    assert request(base + f"/run/{RUN}/")[0] == 200
    for bad in ("2026-09-29_21h00m00_application", "..", "%2e%2e", "../config.env", "x"):
        assert request(base + f"/run/{bad}/")[0] == 404


def test_page_gets_the_token(server):
    rs, base, _ = server
    body = request(base + f"/run/{RUN}/")[1]
    assert f'"token": "{rs.TOKEN}"' in body


def apply(base, rs, token=None, simulation=RUN):
    body = json.dumps({"format": "plex-smart-logo-updater/choices-v1", "simulation": simulation,
                       "decisions": {"7": {"ok": True, "target": "x"}}}).encode()
    return request(base + f"/run/{RUN}/apply", data=body,
                   headers={"Content-Type": "application/json", "X-Review-Token": token or rs.TOKEN})


def test_apply_needs_the_token_and_matching_choices(server):
    rs, base, logs = server
    assert apply(base, rs, token="forged")[0] == 403
    assert apply(base, rs, simulation="2026-01-01_00h00m00_simulation")[0] == 400
    assert not (logs / RUN / "choices.json").exists()


def test_apply_runs_once_and_reports_its_output(server):
    rs, base, logs = server
    assert apply(base, rs)[0] == 200
    saved = json.loads((logs / RUN / "choices.json").read_text())
    assert saved["decisions"]["7"]["ok"] is True
    assert apply(base, rs)[0] == 409  # never applied twice
    for _ in range(100):
        status = json.loads(request(base + f"/run/{RUN}/status")[1])
        if status["state"] == "done":
            break
        threading.Event().wait(0.05)
    assert status["state"] == "done" and status["exit"] == 0
    assert "--choices" in status["output"] and "TOTAL" in status["output"]
    assert "Applied" in request(base + "/")[1]


def test_outdated_dry_run_cannot_be_applied(server):
    rs, base, logs = server
    newer = logs / "2026-09-30_06h00m01_simulation"
    newer.mkdir()
    (newer / "review.html").write_text("<html><head></head></html>")
    (newer / "run.json").write_text(json.dumps({"targeted": False, "complete": True, "libraries": ["Films"]}))
    assert json.loads(request(base + f"/run/{RUN}/status")[1])["outdated"] is True
    status, body = apply(base, rs)
    assert status == 409 and "newer dry run" in body


def test_targeted_newer_run_does_not_outdate(server):
    rs, base, logs = server
    newer = logs / "2026-09-30_06h00m01_simulation"
    newer.mkdir()
    (newer / "review.html").write_text("<html><head></head></html>")
    (newer / "_summary.txt").write_text("  Selected    : 1 title(s) from 1 ratingKey(s)\n")
    assert json.loads(request(base + f"/run/{RUN}/status")[1])["outdated"] is False


def test_command_line_application_marks_the_dry_run(main, tmp_path):
    folder = tmp_path / RUN
    folder.mkdir()
    main.mark_applied(str(folder / "choices.json"), str(tmp_path / "2026-09-29_21h00m00_application"))
    state = json.loads((folder / "applied.json").read_text())
    assert state["exit"] == 0 and state["application"] == "2026-09-29_21h00m00_application"
    other = tmp_path / "somewhere"
    other.mkdir()
    main.mark_applied(str(other / "choices.json"), str(tmp_path / "x_application"))
    assert not (other / "applied.json").exists()


def test_newer_run_with_the_same_changes_supersedes(server):
    rs, base, logs = server
    newer = logs / "2026-09-30_06h00m01_simulation"
    newer.mkdir()
    page = (logs / RUN / "review.html").read_text()
    (newer / "review.html").write_text(page)  # same change "7"
    (newer / "_summary.txt").write_text("  Selected    : 1 title(s) from 1 ratingKey(s)\n")
    assert json.loads(request(base + f"/run/{RUN}/status")[1])["outdated"] is True


def newer_run(logs, info=None, summary_text=None):
    newer = logs / "2026-09-30_06h00m01_simulation"
    newer.mkdir()
    if info is not None:
        (newer / "run.json").write_text(json.dumps(info))
    if summary_text is not None:
        (newer / "_summary.txt").write_text(summary_text)
    return newer


@pytest.mark.parametrize("info, summary_text, expected", [
    ({"targeted": False, "complete": False, "libraries": ["Films"]}, None, False),  # interrupted / still running
    ({"targeted": False, "complete": True, "libraries": ["Séries TV"]}, None, False),  # other libraries only
    (None, "OVERALL SUMMARY\n  [!] Cannot connect to the Plex server\n", False),   # legacy run that stopped
    (None, "OVERALL SUMMARY\n  TOTAL (4 min 38 s)\n", True),                          # legacy complete run
])
def test_only_a_complete_run_covering_the_libraries_outdates(server, info, summary_text, expected):
    rs, base, logs = server
    page = json.loads(re.search(r'id="data">(.*)</script>', (logs / RUN / "review.html").read_text()).group(1))
    for c in page["cards"]:
        c["library"] = "Films"
    (logs / RUN / "review.html").write_text('<html><head></head><body><script type="application/json" id="data">'
                                            + json.dumps(page) + "</script></body></html>")
    newer_run(logs, info, summary_text)
    assert json.loads(request(base + f"/run/{RUN}/status")[1])["outdated"] is expected


def test_forged_forwarded_for_does_not_bypass_the_limit(server, monkeypatch):
    rs, base, _ = server
    monkeypatch.setattr(rs.time, "sleep", lambda s: None)
    form = urllib.parse.urlencode({"user": "plex", "password": "wrong"}).encode()
    for i in range(rs.MAX_FAILURES):
        raw(base + "/login", data=form, headers={"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.9"})
    right = urllib.parse.urlencode({"user": "plex", "password": "secret"}).encode()
    assert raw(base + "/login", data=right, headers={"X-Forwarded-For": "1.2.3.4, 203.0.113.9"})[0] == 429


def test_basic_auth_guesses_count_as_failures(server):
    rs, base, _ = server
    for _ in range(rs.MAX_FAILURES):
        assert request(base + "/", auth=("plex", "guess"))[0] in (200, 303)
    status, _, _ = raw(base + "/", headers={"Authorization": "Basic " + base64.b64encode(b"plex:secret").decode()})
    assert status == 303  # locked out for a while, even with the right password


@pytest.mark.parametrize("length", ["-1", "abc"])
def test_invalid_content_length_is_refused(server, length):
    rs, base, _ = server
    import http.client
    host, port = base.split("//")[1].split(":")
    for path in ("/login", f"/run/{RUN}/apply"):
        conn = http.client.HTTPConnection(host, int(port), timeout=5)
        conn.putrequest("POST", path)
        conn.putheader("Content-Length", length)
        conn.putheader("Authorization", "Basic " + base64.b64encode(b"plex:secret").decode())
        conn.putheader("X-Review-Token", rs.TOKEN)
        conn.endheaders()
        assert conn.getresponse().status == 400
        conn.close()


def test_sign_out_revokes_the_session(server):
    rs, base, _ = server
    cookie = sign_in(base)[1]["Set-Cookie"].split(";")[0]
    assert raw(base + "/", headers={"Cookie": cookie})[0] == 200
    sign_out(base, rs, cookie)
    assert raw(base + "/", headers={"Cookie": cookie})[0] == 303


def test_application_that_cannot_start_reports_an_error(server, monkeypatch):
    rs, base, logs = server
    monkeypatch.setattr(rs.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(OSError("no python")))
    status, body = apply(base, rs)
    assert status == 409 and "cannot start" in body
    assert not (logs / RUN / "applied.json").exists()  # can be retried


def test_reused_pid_is_not_an_application(server):
    rs, _, _ = server
    assert rs._alive(os.getpid()) is False  # this test process: alive, but not the application


@pytest.mark.parametrize("cookie", ["plexlogo_session=\u00b2.x", "plexlogo_session=1.\u00e9"])
def test_odd_cookies_do_not_crash(server, cookie):
    _, base, _ = server
    import http.client
    host, port = base.split("//")[1].split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=5)
    conn.putrequest("GET", "/")
    conn.putheader("Cookie", cookie.encode("latin-1"))
    conn.endheaders()
    assert conn.getresponse().status == 303  # sign-in page, not a dropped connection


def test_failed_application_can_be_retried(server):
    rs, base, logs = server
    (logs / RUN / "applied.json").write_text(json.dumps({"started": "x", "pid": None, "exit": 1, "finished": "x"}))
    assert apply(base, rs)[0] == 200
    (logs / RUN / "applied.json").write_text(json.dumps({"started": "x", "pid": None, "exit": 0, "finished": "x"}))
    assert apply(base, rs)[0] == 409


def test_home_page_survives_a_pruned_folder(server, monkeypatch):
    rs, base, _ = server
    real = rs.summary
    monkeypatch.setattr(rs, "summary", lambda f: (_ for _ in ()).throw(FileNotFoundError(f)))
    assert request(base + "/")[0] == 200
    monkeypatch.setattr(rs, "summary", real)


def test_command_line_application_with_errors_can_be_retried(main, tmp_path):
    """Regression: an application with failed titles marked its dry run applied (exit 0): no retry from the page."""
    folder = tmp_path / RUN
    folder.mkdir()
    main.mark_applied(str(folder / "choices.json"), str(tmp_path / "x_application"), main.ERRORS)
    assert json.loads((folder / "applied.json").read_text())["exit"] == main.ERRORS


def test_next_cannot_inject_headers(server):
    """Regression: next= accepted CR/LF, which went into the Location header (response splitting)."""
    _, base, _ = server
    cookie = sign_in(base)[1]["Set-Cookie"].split(";")[0]
    status, headers, _ = raw(base + "/login?next=run/x%0d%0aSet-Cookie:%20injected=1%0d%0aX-Evil:%20yes/",
                             headers={"Cookie": cookie})
    assert status == 303 and headers["Location"] == "./" and "X-Evil" not in headers
    assert all("injected" not in v for v in headers.get_all("Set-Cookie") or [])
    status, headers, _ = raw(base + f"/login?next=run/{RUN}/", headers={"Cookie": cookie})
    assert headers["Location"] == f"./run/{RUN}/"


def test_session_cookie_is_secure_when_the_public_address_is_https(server, monkeypatch):
    """Regression: Secure was only set from X-Forwarded-Proto, which the documented proxy block did not send."""
    rs, base, _ = server
    monkeypatch.setattr(rs, "REVIEW_URL", "https://example.org/logos/")
    assert "Secure" in sign_in(base)[1]["Set-Cookie"]


def test_failure_tracking_is_bounded(server, monkeypatch):
    rs, _, _ = server
    monkeypatch.setattr(rs, "MAX_TRACKED", 50)
    for i in range(500):
        rs.record_failure(f"10.0.{i // 256}.{i % 256}")
    assert len(rs._FAILURES) <= 50


def test_command_line_retry_replaces_a_failed_state(main, tmp_path):
    """Regression: after a failed application from the page, a successful command-line retry left it 'failed'."""
    folder = tmp_path / RUN
    folder.mkdir()
    (folder / "applied.json").write_text(json.dumps({"exit": 2, "pid": None}))
    main.mark_applied(str(folder / "choices.json"), str(tmp_path / "x_application"), main.OK)
    assert json.loads((folder / "applied.json").read_text())["exit"] == 0
    (folder / "applied.json").write_text(json.dumps({"exit": None, "pid": 123}))  # being applied: kept
    main.mark_applied(str(folder / "choices.json"), str(tmp_path / "x_application"), main.OK)
    assert json.loads((folder / "applied.json").read_text())["exit"] is None
