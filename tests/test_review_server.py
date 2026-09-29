"""review_server.py: login, paths, anti-CSRF token and the apply flow (the application itself is faked)."""
import base64
import importlib
import json
import os
import sys
import threading
import urllib.error
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


def test_login_is_required(server):
    _, base, _ = server
    assert request(base + "/", auth=None)[0] == 401
    assert request(base + "/", auth=("plex", "wrong"))[0] == 401
    status, body = request(base + "/")
    assert status == 200 and RUN in body and "1 change(s) to review" in body


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
    assert "applied" in request(base + "/")[1]


def test_outdated_dry_run_cannot_be_applied(server):
    rs, base, logs = server
    newer = logs / "2026-09-30_06h00m01_simulation"
    newer.mkdir()
    (newer / "review.html").write_text("<html><head></head></html>")
    (newer / "_summary.txt").write_text("OVERALL SUMMARY\n")  # full run: no "Selected" line
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
