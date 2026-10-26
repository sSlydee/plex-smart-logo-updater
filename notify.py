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
import time

import requests

KINDS = ("discord", "bark", "json")
DISCORD_LIMIT = 1900   # Discord refuses messages over 2000 characters
RETRIES = 2            # new attempts after a temporary refusal (rate limit, server error) or a connection error
RETRY_STATUSES = (429, 500, 502, 503, 504)
MAX_RETRY_WAIT = 30    # seconds, whatever the server asks


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


def escape_markdown(text):
    """Text shown as is on Discord: *, _, ~, `, | and \\ in titles are not formatting."""
    return re.sub(r"([\\*_~`|])", r"\\\1", text)


def shorten_discord(text, limit=DISCORD_LIMIT):
    """
    A message that fits in Discord. Its last two lines (the review link and the logs
    folder of a run) are kept: the lines before them are cut instead.
    """
    if len(text) <= limit:
        return text
    lines = text.split("\n")
    tail = "\n".join(lines[-2:]) if len(lines) > 2 else ""
    room = limit - len(tail) - 2
    if room < 100:  # the last lines alone are too long: plain cut
        return text[:limit - 1] + "…"
    return "\n".join(lines[:-2])[:room] + "…\n" + tail


def _discord(session, url, title, body, link=None):
    text = shorten_discord(f"**{title}**\n{body}")
    # allowed_mentions: a "@everyone" in a title never pings the server
    return session.post(url, json={"content": text, "allowed_mentions": {"parse": []}}, timeout=20)


def _bark(session, url, title, body, link=None):
    # Bark: POST JSON to https://<server>/<key>; "url" is opened when the notification is tapped
    payload = {"title": title, "body": body[:3000], "group": "Plex logos"}
    if link:
        payload["url"] = link
    return session.post(url.rstrip("/"), json=payload, timeout=20)


def _json(session, url, title, body, link=None):
    payload = {"title": title, "message": body, "text": f"{title}\n{body}"}
    if link:
        payload["url"] = link
    return session.post(url, json=payload, timeout=20)


SENDERS = {"discord": _discord, "bark": _bark, "json": _json}


def hide(text, *urls):
    """
    An error text without the secret parts of these URLs. Errors do not always quote the
    full URL: a connection error quotes only its path ("Max retries exceeded with url:
    /api/webhooks/<id>/<token>"), so the path and each long path segment (tokens, keys)
    are hidden too.
    """
    from urllib.parse import urlsplit
    text = str(text)
    for url in urls:
        parts = urlsplit(url)
        path_query = parts.path + ("?" + parts.query if parts.query else "")
        secrets = [url, path_query, parts.path] + [seg for seg in parts.path.split("/") if len(seg) >= 8]
        for secret in sorted({s for s in secrets if s and s != "/"}, key=len, reverse=True):
            text = text.replace(secret, "<hidden>")
    return text


def send(session, targets, title, body, markdown_body=None, link=None):
    """
    Sends the notification to every target. markdown_body (optional) is used for
    Discord, which renders Markdown. link (optional, http(s) only) is opened when a
    Bark notification is tapped, and sent as "url" to generic webhooks.
    Returns a list of (type, error or None).
    """
    if link and not link.startswith(("http://", "https://")):
        link = None  # a local file path cannot be opened from a phone
    results = []
    for kind, url in targets:
        text = markdown_body if (kind == "discord" and markdown_body) else body
        for attempt in range(RETRIES + 1):
            try:
                r = SENDERS[kind](session, url, title, text, link)
                r.raise_for_status()
                results.append((kind, None))
                break
            except Exception as e:
                wait = retry_wait(e)
                if wait is None or attempt == RETRIES:
                    # A webhook address is a secret: never copy it into the logs
                    results.append((kind, hide(e, url)))
                    break
                time.sleep(wait)
    return results


def retry_wait(error):
    """Seconds to wait before trying again, or None when trying again is pointless (e.g. a 404)."""
    # Not a read timeout: the message may have arrived, and would be sent twice
    if isinstance(error, requests.ConnectionError):  # includes ConnectTimeout
        return 5
    response = getattr(error, "response", None)
    if response is None or response.status_code not in RETRY_STATUSES:
        return None
    try:
        wait = float(response.headers.get("Retry-After", 5))
    except (TypeError, ValueError):
        wait = 5
    return min(max(wait, 1), MAX_RETRY_WAIT)


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
        return hide(e, target, url)
