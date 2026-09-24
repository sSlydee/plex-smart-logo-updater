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
    assert discord == ("https://d/x", {"content": "**Title**\n**Body**"})
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
