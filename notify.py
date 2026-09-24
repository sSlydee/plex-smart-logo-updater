"""
Sends notifications to one or more webhooks.

NOTIFY_URLS holds one or more addresses, separated by commas or spaces. The
type is guessed from the address, or forced with a prefix:

  discord:https://discord.com/api/webhooks/...   Discord (text message)
  bark:https://api.day.app/<key>                 Bark (iPhone), official or self-hosted server
  json:https://example.org/hook                  generic webhook (POST JSON)

Without a prefix: discord.com/api/webhooks addresses are Discord, api.day.app
addresses are Bark, anything else is a generic webhook.
"""
import re

KINDS = ("discord", "bark", "json")


def parse_targets(value):
    """List of (type, url) from NOTIFY_URLS."""
    targets = []
    for raw in re.split(r"[\s,]+", value or ""):
        if not raw:
            continue
        kind, url = None, raw
        # "discord:", "bark:" or "json:" prefix (possibly repeated by mistake)
        while True:
            prefix, sep, rest = url.partition(":")
            if not (sep and prefix.lower() in KINDS):
                break
            kind, url = prefix.lower(), rest
        if kind is None:
            if re.search(r"discord(app)?\.com/api/webhooks/", url):
                kind = "discord"
            elif "api.day.app/" in url:
                kind = "bark"
            else:
                kind = "json"
        targets.append((kind, url))
    return targets


def _discord(session, url, title, body):
    text = f"**{title}**\n{body}"
    return session.post(url, json={"content": text[:1900]}, timeout=20)


def _bark(session, url, title, body):
    # Bark: POST JSON to https://<server>/<key>
    return session.post(url.rstrip("/"), json={"title": title, "body": body[:3000], "group": "Plex logos"},
                        timeout=20)


def _json(session, url, title, body):
    return session.post(url, json={"title": title, "message": body, "text": f"{title}\n{body}"}, timeout=20)


SENDERS = {"discord": _discord, "bark": _bark, "json": _json}


def send(session, targets, title, body, markdown_body=None):
    """
    Sends the notification to every target. markdown_body (optional) is used for
    Discord, which renders Markdown. Returns a list of (type, error or None).
    """
    results = []
    for kind, url in targets:
        text = markdown_body if (kind == "discord" and markdown_body) else body
        try:
            r = SENDERS[kind](session, url, title, text)
            r.raise_for_status()
            results.append((kind, None))
        except Exception as e:
            # A webhook address is a secret: never copy it into the logs
            results.append((kind, str(e).replace(url, f"<webhook {kind}>")))
    return results


def heartbeat(session, url, ok, message="", duration_seconds=None):
    """
    Tells a monitoring service that a run happened (HEALTHCHECK_URL).

    - Uptime Kuma push URL (…/api/push/<token>): status=up|down, msg and ping are set.
    - Any other URL (healthchecks.io style): GET url when ok, url + "/fail" otherwise.
    Returns None on success, or an error message (the URL is never included).
    """
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
    if "/api/push/" in url:
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query))
        query.update(status="up" if ok else "down", msg=message[:200])
        if duration_seconds is not None:
            query["ping"] = str(int(duration_seconds * 1000))
        target = urlunsplit(parts._replace(query=urlencode(query)))
    else:
        target = url if ok else url.rstrip("/") + "/fail"
    try:
        r = session.get(target, timeout=20)
        r.raise_for_status()
        return None
    except Exception as e:
        return str(e).replace(target, "<healthcheck URL>").replace(url, "<healthcheck URL>")
