"""Webhook parsing and sending (no network: requests are captured)."""
import notify


def test_parse_targets_guesses_types():
    targets = notify.parse_targets(
        "https://discord.com/api/webhooks/1/abc, https://api.day.app/KEY https://hook.example.org/x")
    assert targets == [
        ("discord", "https://discord.com/api/webhooks/1/abc"),
        ("bark", "https://api.day.app/KEY"),
        ("json", "https://hook.example.org/x"),
    ]


def test_parse_targets_prefixes():
    targets = notify.parse_targets("bark:https://bark.example.org/KEY json:json:https://a.example/x")
    assert targets == [("bark", "https://bark.example.org/KEY"), ("json", "https://a.example/x")]


def test_parse_targets_empty():
    assert notify.parse_targets("") == []
    assert notify.parse_targets(None) == []


class FakeResponse:
    def __init__(self, status=200):
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"{self.status} error for url: {self.url}")


class FakeSession:
    def __init__(self, status=200):
        self.calls = []
        self.status = status

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json))
        response = FakeResponse(self.status)
        response.url = url
        return response


def test_send_payloads():
    session = FakeSession()
    targets = [("discord", "https://d/x"), ("bark", "https://b/KEY/"), ("json", "https://j/x")]
    results = notify.send(session, targets, "Title", "Body", markdown_body="**Body**")
    assert results == [("discord", None), ("bark", None), ("json", None)]
    discord, bark, generic = session.calls
    assert discord == ("https://d/x", {"content": "**Title**\n**Body**", "allowed_mentions": {"parse": []}})
    assert bark[0] == "https://b/KEY" and bark[1]["title"] == "Title" and bark[1]["body"] == "Body"
    assert generic[1] == {"title": "Title", "message": "Body", "text": "Title\nBody"}


def test_send_never_leaks_webhook_address():
    session = FakeSession(status=500)
    secret = "https://discord.com/api/webhooks/123/secret-token"
    [(kind, error)] = notify.send(session, [("discord", secret)], "Title", "Body")
    assert kind == "discord" and error
    assert "secret-token" not in error


class GetSession:
    def __init__(self, status=200):
        self.urls = []
        self.status = status

    def get(self, url, timeout=None):
        self.urls.append(url)
        response = FakeResponse(self.status)
        response.url = url
        return response


def test_heartbeat_uptime_kuma_up_and_down():
    from urllib.parse import urlsplit, parse_qs
    session = GetSession()
    url = "https://kuma.example.org/api/push/AbC123?status=up&msg=OK&ping="
    assert notify.heartbeat(session, url, True, "ok", 2.5) is None
    assert notify.heartbeat(session, url, False, "Plex token rejected") is None
    up, down = (parse_qs(urlsplit(u).query) for u in session.urls)
    assert up["status"] == ["up"] and up["msg"] == ["ok"] and up["ping"] == ["2500"]
    assert down["status"] == ["down"] and down["msg"] == ["Plex token rejected"]
    assert all(urlsplit(u).path == "/api/push/AbC123" for u in session.urls)


def test_heartbeat_healthchecks_style():
    session = GetSession()
    notify.heartbeat(session, "https://hc-ping.com/uuid", True)
    notify.heartbeat(session, "https://hc-ping.com/uuid/", False)
    assert session.urls == ["https://hc-ping.com/uuid", "https://hc-ping.com/uuid/fail"]


def test_heartbeat_error_hides_the_url():
    error = notify.heartbeat(GetSession(status=500), "https://kuma.example.org/api/push/SECRET", True)
    assert error and "SECRET" not in error


class FailingSession:
    """Raises the error text requests gives for a connection error: only the URL path is quoted."""

    def _fail(self, url, **kw):
        from urllib.parse import urlsplit
        parts = urlsplit(url)
        path = parts.path + ("?" + parts.query if parts.query else "")
        raise ConnectionError(f"HTTPSConnectionPool(host='{parts.hostname}', port=443): "
                              f"Max retries exceeded with url: {path} (Caused by NameResolutionError)")

    post = get = _fail


def test_connection_errors_hide_the_secrets():
    """Regression: connection errors quote only the URL path, which holds the webhook token / Bark key / push token."""
    targets = [("discord", "https://discord.com/api/webhooks/123456789/SECRETWEBHOOKTOKEN"),
               ("bark", "https://api.day.app/SECRETBARKKEY")]
    for kind, error in notify.send(FailingSession(), targets, "T", "B"):
        assert error and "SECRETWEBHOOKTOKEN" not in error and "SECRETBARKKEY" not in error
    error = notify.heartbeat(FailingSession(), "https://kuma.example.org/api/push/SECRETPUSH1?status=up&msg=OK", False)
    assert error and "SECRETPUSH1" not in error


class StatusError(Exception):
    def __init__(self, status, headers=None):
        super().__init__(f"{status} error")
        self.response = type("R", (), {"status_code": status, "headers": headers or {}})()


class FlakySession:
    """Fails with the given errors first, then works."""

    def __init__(self, *errors):
        self.errors, self.calls = list(errors), 0

    def post(self, url, json=None, timeout=None):
        self.calls += 1
        error = self.errors.pop(0) if self.errors else None

        class Response:
            def raise_for_status(self):
                if error:
                    raise error
        return Response()


def test_a_temporary_refusal_is_tried_again(monkeypatch):
    """Regression: a Discord rate limit (429) lost the notification until the next run, a week later."""
    waits = []
    monkeypatch.setattr(notify.time, "sleep", waits.append)
    session = FlakySession(StatusError(429, {"Retry-After": "2.5"}), StatusError(503))
    assert notify.send(session, [("discord", "https://d/x")], "Title", "Body") == [("discord", None)]
    assert session.calls == 3 and waits == [2.5, 5]


def test_a_lasting_or_final_refusal_is_not_tried_again(monkeypatch):
    monkeypatch.setattr(notify.time, "sleep", lambda s: None)
    session = FlakySession(StatusError(404))
    [(kind, error)] = notify.send(session, [("bark", "https://b/KEY")], "Title", "Body")
    assert error and session.calls == 1
    session = FlakySession(*[StatusError(500)] * 5)
    [(kind, error)] = notify.send(session, [("bark", "https://b/KEY")], "Title", "Body")
    assert error and session.calls == notify.RETRIES + 1


def test_a_long_discord_message_keeps_its_last_lines():
    """The review link and the logs folder are the last two lines: they survive the cut."""
    body = "\n".join(f"• title {i}" * 10 for i in range(100)) + "\nReview page: https://x/run/a_b/\n`Logs: a_b`"
    text = notify.shorten_discord(body)
    assert len(text) <= notify.DISCORD_LIMIT
    assert text.endswith("Review page: https://x/run/a_b/\n`Logs: a_b`")


def test_escape_markdown():
    assert notify.escape_markdown("Thunderbolts* _x_ ~y~ `z` a|b \\") == "Thunderbolts\\* \\_x\\_ \\~y\\~ \\`z\\` a\\|b \\\\"


def test_bark_opens_the_link_when_tapped():
    session = FakeSession()
    targets = [("discord", "https://d/x"), ("bark", "https://b/KEY"), ("json", "https://j/x")]
    notify.send(session, targets, "Title", "Body", link="https://example.org/logos/run/a/")
    discord, bark, generic = session.calls
    assert bark[1]["url"] == generic[1]["url"] == "https://example.org/logos/run/a/"
    assert "url" not in discord[1]


def test_a_local_review_page_is_not_sent_as_a_link():
    session = FakeSession()
    notify.send(session, [("bark", "https://b/KEY")], "Title", "Body", link="/home/me/logs/run/review.html")
    assert "url" not in session.calls[0][1]


def test_timeouts_and_connection_errors_are_not_tried_again(monkeypatch):
    """Regression: a read timeout or a dropped connection was tried again though the message may have
    arrived (sent twice), and failed connections were retried on top of the HTTP session's own retries."""
    import requests
    monkeypatch.setattr(notify.time, "sleep", lambda s: None)
    for error in (requests.ReadTimeout("read timed out"), requests.ConnectTimeout("connect timed out"),
                  requests.ConnectionError("connection reset")):
        session = FlakySession(error)
        [(kind, message)] = notify.send(session, [("discord", "https://d/x")], "Title", "Body")
        assert message and session.calls == 1


def test_an_absurd_retry_after_does_not_crash(monkeypatch):
    waits = []
    monkeypatch.setattr(notify.time, "sleep", waits.append)
    for value in ("nan", "inf", "soon"):
        session = FlakySession(StatusError(429, {"Retry-After": value}))
        assert notify.send(session, [("discord", "https://d/x")], "Title", "Body") == [("discord", None)]
    assert waits == [5, 5, 5]


def test_a_long_two_line_alert_is_cut_not_emptied():
    """Regression: a failure alert (title + one long error line) became just "…" on Discord."""
    text = notify.shorten_discord("**Plex logos: run failed**\n" + "Cannot connect: " + "x" * 3000)
    assert text.startswith("**Plex logos: run failed**\nCannot connect: ") and len(text) <= notify.DISCORD_LIMIT
