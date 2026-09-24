"""
Setup wizard for plex-smart-logo-updater.py.

Asks a few questions, tests the Plex connection and the notifications, then
writes config.env (readable by you only). It can also install the automatic
run in cron. Run it again to change the configuration: current values are
offered as defaults (press Enter to keep them).

Usage:
  .venv/bin/python configure.py                   full setup
  .venv/bin/python configure.py --token           change the token only
  .venv/bin/python configure.py --token <token>   same, without prompting (the token is tested)
  .venv/bin/python configure.py --server | --libraries | --language | --notifications | --cron
                                                  redo a single step
"""
import argparse
import getpass
import os
import re
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import envfile  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("PLEX_CONFIG", os.path.join(HERE, "config.env"))
CRON_TAG = "# plex-smart-logo-updater (managed by configure.py)"
CRON_MARK = "# plex-smart-logo-updater"

TOKEN_HELP = "https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/"
LANGUAGE_CHOICES = [
    ("auto", "auto: each library's own language, then English (recommended)"),
    ("fr-FR,en-US", "French, otherwise English, for every library"),
    ("en-US", "English only, for every library"),
]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

def title(text):
    print()
    print(f"── {text} " + "─" * max(0, 60 - len(text)))


def ask(question, default=""):
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{question}{suffix}: ").strip()
    except EOFError:
        print()
        sys.exit("Setup interrupted.")
    return answer or default


def ask_secret(question, default=""):
    shown = f"{default[:4]}…" if default else ""
    suffix = f" [{shown}, Enter to keep]" if default else ""
    if sys.stdin.isatty():
        answer = getpass.getpass(f"{question}{suffix}: ").strip()
    else:
        answer = ask(question)
    return answer or default


def ask_yes(question, default=True):
    hint = "Y/n" if default else "y/N"
    answer = ask(f"{question} ({hint})").lower()
    if not answer:
        return default
    return answer.startswith(("y", "o"))  # "o" for "oui"


def ask_choice(question, options, default=1):
    """options: list of labels. Returns the chosen index (0-based)."""
    for i, label in enumerate(options, 1):
        print(f"  {i}. {label}")
    while True:
        answer = ask(question, str(default))
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return int(answer) - 1
        print("  Invalid answer, type one of the numbers above.")


# ---------------------------------------------------------------------------
# config.env
# ---------------------------------------------------------------------------

KNOWN_KEYS = ("PLEX_URL", "PLEX_TOKEN", "PLEX_LIBRARIES", "PLEX_LANGUAGES", "NOTIFY_URLS", "HEALTHCHECK_URL")


def read_config(path):
    return envfile.parse(path)


def write_config(path, values):
    """Writes config.env: the wizard's keys first, then every other key already in the file."""
    ordered = {k: values.get(k, "") for k in KNOWN_KEYS}
    ordered.update((k, v) for k, v in values.items() if k not in KNOWN_KEYS)
    envfile.write(path, ordered,
                  header=["plex-smart-logo-updater configuration, written by configure.py.",
                          "Do not publish: this file contains your Plex token and webhooks."],
                  comments={"NOTIFY_URLS": "Webhooks for --notify (Discord, Bark or json:<url>), comma-separated",
                            "HEALTHCHECK_URL": "Uptime Kuma push URL (or healthchecks.io URL), pinged after every run"})


def parse_hour(text):
    """Hour 0-23 from "6", "06", "6h", "06:00"…; None if it cannot be read."""
    m = re.match(r"^\s*(\d{1,2})\s*(?:h|:\d{2})?\s*$", text or "", re.IGNORECASE)
    if m and 0 <= int(m.group(1)) <= 23:
        return int(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def connect(url, token):
    """Returns (Plex server, None) or (None, error message)."""
    from plexapi.server import PlexServer
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    session = requests.Session()
    session.verify = False
    try:
        return PlexServer(url, token, session=session, timeout=15), None
    except Exception as e:
        from plexapi.exceptions import Unauthorized
        status = getattr(getattr(e, "response", None), "status_code", None)
        if isinstance(e, Unauthorized) or status == 401:
            return None, "token rejected by the server (401)"
        return None, str(e)


def step_token(values, token=None):
    """Changes the token only, keeping the server address."""
    title("Plex token")
    if not values.get("PLEX_URL"):
        sys.exit("No server address configured: run configure.py without options first.")
    print(f"Server: {values['PLEX_URL']}")
    interactive = token is None
    while True:
        if interactive:
            print(f"Where to find the token: {TOKEN_HELP}")
            token = ask_secret("New Plex token (X-Plex-Token)")
        if not token:
            sys.exit("No token entered: nothing changed.")
        plex, error = connect(values["PLEX_URL"], token)
        if plex is not None:
            print(f'  ✓ Connected to "{plex.friendlyName}" (Plex {plex.version})')
            values["PLEX_TOKEN"] = token
            return plex
        print(f"  ✗ Connection failed: {error}")
        if not interactive or not ask_yes("Try again?"):
            sys.exit("The token was not changed.")
        token = None


def step_plex(values):
    title("1. Plex server")
    print("Use the server's LOCAL address (e.g. http://192.168.1.100:32400),")
    print("not a public domain name behind a reverse proxy.")
    while True:
        url = ask("Plex server address", values.get("PLEX_URL", "http://127.0.0.1:32400")).rstrip("/")
        if not re.match(r"^https?://", url):
            url = "http://" + url
        print(f"Plex token: see {TOKEN_HELP}")
        token = ask_secret("Plex token (X-Plex-Token)", values.get("PLEX_TOKEN", ""))
        plex, error = connect(url, token)
        if plex is None:
            print(f"  ✗ Connection failed: {error}")
            if not ask_yes("Try again?"):
                sys.exit("Setup interrupted.")
            continue
        print(f'  ✓ Connected to "{plex.friendlyName}" (Plex {plex.version})')
        values["PLEX_URL"], values["PLEX_TOKEN"] = url, token
        return plex


def step_libraries(values, plex):
    title("2. Libraries to process")
    sections = [s for s in plex.library.sections() if s.type in ("movie", "show")]
    if not sections:
        sys.exit("No movie or TV show library on this server.")
    current = [s.strip() for s in values.get("PLEX_LIBRARIES", "").split(",") if s.strip()]
    for i, s in enumerate(sections, 1):
        mark = "x" if s.title in current else " "
        kind = "movies" if s.type == "movie" else "shows"
        print(f"  [{mark}] {i:>2}. {s.title} ({kind}, language {s.language})")
    default = ",".join(str(i) for i, s in enumerate(sections, 1) if s.title in current) or "all"
    while True:
        answer = ask('Comma-separated numbers, or "all"', default).lower()
        if answer in ("all", "*", "tout"):
            chosen = sections
        else:
            try:
                chosen = [sections[int(n) - 1] for n in re.split(r"[\s,;]+", answer) if n]
            except (ValueError, IndexError):
                print("  Invalid answer.")
                continue
        if chosen:
            break
        print("  Pick at least one library.")
    names = [s.title for s in chosen]
    if any("," in n for n in names):
        sys.exit("A library name contains a comma: rename it in Plex.")
    values["PLEX_LIBRARIES"] = ",".join(names)
    print(f"  ✓ {len(names)} library(ies): {', '.join(names)}")


def step_languages(values, plex=None):
    title("3. Logo language")
    print("Languages to try, in order. With \"auto\", each library uses the language set in Plex")
    print("(then English); the Quebec logo detection runs for French libraries.")
    if plex is not None:
        chosen = [s.strip() for s in values.get("PLEX_LIBRARIES", "").split(",") if s.strip()]
        langs = {s.title: s.language for s in plex.library.sections() if s.title in chosen}
        if langs:
            print("Your libraries: " + ", ".join(f"{t} ({l})" for t, l in langs.items()))
    codes = [c for c, _ in LANGUAGE_CHOICES]
    current = values.get("PLEX_LANGUAGES", "auto") or "auto"
    labels = [label for _, label in LANGUAGE_CHOICES] + [f"other (current: {current})" if current not in codes
                                                        else "other (Plex codes, e.g. de-DE,en-US)"]
    default = codes.index(current) + 1 if current in codes else len(labels)
    choice = ask_choice("Choice", labels, default)
    if choice < len(codes):
        values["PLEX_LANGUAGES"] = codes[choice]
    else:
        values["PLEX_LANGUAGES"] = ask("Language codes in order of preference", current).replace(" ", "")


def describe_target(kind, url):
    if kind == "bark":
        return "Bark"
    if kind == "discord":
        return "Discord"
    return f"generic webhook ({url.split('/')[2] if '//' in url else url})"


def step_notifications(values):
    import notify
    import requests

    title("4. Notifications (optional)")
    targets = notify.parse_targets(values.get("NOTIFY_URLS", ""))
    if targets:
        print("Current webhooks: " + ", ".join(describe_target(k, u) for k, u in targets))
        if not ask_yes("Keep them?"):
            targets = []
    else:
        print("The script can notify you (Discord, Bark…) when titles need review.")
    add = ask_yes("Add a webhook?", default=not targets)
    while add:
        kind = ask_choice("Type", ["Discord", "Bark", "generic webhook (POST JSON)"], 1)
        if kind == 0:
            target = ("discord", ask("Discord webhook URL (Channel settings > Integrations > Webhooks)"))
        elif kind == 1:
            server = ask("Bark server", "https://api.day.app").rstrip("/")
            key = ask("Bark key (shown in the app)").strip("/")
            target = ("bark", f"{server}/{key}" if key else "")
        else:
            target = ("json", ask("Webhook URL"))
        if re.match(r"^https?://\S+$", target[1]):
            targets.append(target)
        else:
            print("  ✗ Invalid address (it must start with http:// or https://): webhook not added.")
        add = ask_yes("Add another webhook?", default=False)
    values["NOTIFY_URLS"] = ",".join(f"{k}:{u}" for k, u in targets)
    if targets and ask_yes("Send a test notification?"):
        session = requests.Session()
        for kind, error in notify.send(session, targets, "Plex logos: test",
                                       "plex-smart-logo-updater notifications are working."):
            print(f"  {'✓' if error is None else '✗'} {kind}" + (f": {error}" if error else ""))

    print()
    print("Monitoring (optional): an Uptime Kuma \"Push\" monitor URL is pinged after every run,")
    print("so you are warned if the automatic run stops working. Type \"none\" to remove it.")
    current = values.get("HEALTHCHECK_URL", "")
    url = ask("Uptime Kuma push URL (Enter to keep / skip)", current)
    if url.lower() in ("none", "-"):
        url = ""
    if url and not re.match(r"^https?://\S+$", url):
        print("  ✗ Invalid address (it must start with http:// or https://): monitoring not changed.")
        url = current
    values["HEALTHCHECK_URL"] = url
    if url and url != current and ask_yes("Send a test ping?"):
        error = notify.heartbeat(requests.Session(), url, True, "plex-smart-logo-updater: test")
        print(f"  {'✓ ping sent' if error is None else '✗ ' + error}")


def current_cron():
    try:
        out = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    except FileNotFoundError:
        return None
    return out.stdout if out.returncode == 0 else ""


def step_cron():
    title("5. Automatic run (optional)")
    existing = current_cron()
    if existing is None:
        print("cron is not available on this machine: step skipped.")
        return
    lines = existing.splitlines()
    ours = [l for l in lines if CRON_MARK in l]
    if ours:
        print("Current automatic run: " + ours[0].split(CRON_MARK)[0].strip())
    print("The script runs a DRY RUN (nothing is changed), writes the review page")
    print("and notifies you when titles need review.")
    choice = ask_choice("Frequency", ["never" + (" (remove the current one)" if ours else ""),
                                      "every day", "once a week",
                                      "keep the current setting"], 4 if ours else 3)
    if choice == 3:
        return
    others = [l for l in lines if CRON_MARK not in l]
    if choice == 0:
        new_lines = others
    else:
        while True:
            hour = parse_hour(ask("Hour (0-23)", "9"))
            if hour is not None:
                break
            print("  Invalid hour, type a number between 0 and 23.")
        dow = "*"
        if choice == 2:
            day = ask_choice("Day", DAYS, 1)
            dow = str((day + 1) % 7)  # cron: 0 = Sunday
        python = os.path.join(HERE, ".venv", "bin", "python")
        command = (f"cd {shlex.quote(HERE)} && mkdir -p logs && {shlex.quote(python)} plex-smart-logo-updater.py "
                   f"--html --notify --quiet >> logs/cron.log 2>&1")
        new_lines = others + [f"0 {hour} * * {dow} {command} {CRON_TAG}"]
    text = "\n".join(new_lines) + ("\n" if new_lines else "")
    subprocess.run(["crontab", "-"], input=text, text=True, check=True)
    print("  ✓ crontab updated.")


def parse_args():
    p = argparse.ArgumentParser(description="plex-smart-logo-updater setup wizard (writes config.env).")
    p.add_argument("--token", nargs="?", const="", metavar="TOKEN",
                   help="change the token only (prompted if not given), after testing it")
    p.add_argument("--server", action="store_true", help="redo the server address and token only")
    p.add_argument("--libraries", action="store_true", help="redo the library selection only")
    p.add_argument("--language", action="store_true", help="redo the logo language only")
    p.add_argument("--notifications", action="store_true", help="redo the notifications only")
    p.add_argument("--cron", action="store_true", help="redo the automatic run only")
    # Former French names, still accepted
    p.add_argument("--serveur", dest="server", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--bibliotheques", dest="libraries", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--langue", dest="language", action="store_true", help=argparse.SUPPRESS)
    return p.parse_args()


def save(values):
    write_config(CONFIG_PATH, values)
    print(f"  ✓ Saved to {CONFIG_PATH} (readable by you only)")


def main():
    args = parse_args()
    values = read_config(CONFIG_PATH)
    partial = args.token is not None or args.server or args.libraries or args.language \
        or args.notifications or args.cron

    if partial:
        if not values and not args.cron:
            sys.exit(f"No configuration yet ({CONFIG_PATH}): run configure.py without options first.")
        plex = None
        if args.token is not None:
            plex = step_token(values, args.token or None)
        if args.server:
            plex = step_plex(values)
        if args.libraries:
            if plex is None:
                plex, error = connect(values.get("PLEX_URL", ""), values.get("PLEX_TOKEN", ""))
                if plex is None:
                    sys.exit(f"Cannot connect to Plex ({error}): run configure.py --token.")
            step_libraries(values, plex)
        if args.language:
            step_languages(values, plex)
        if args.notifications:
            step_notifications(values)
        if values and (args.token is not None or args.server or args.libraries or args.language
                       or args.notifications):
            save(values)
        if args.cron:
            step_cron()
        return

    print("plex-smart-logo-updater setup")
    print(f"File: {CONFIG_PATH}")
    if values:
        print("Existing configuration found: press Enter to keep each value.")
    plex = step_plex(values)
    step_libraries(values, plex)
    step_languages(values, plex)
    step_notifications(values)
    title("Saved")
    save(values)
    step_cron()
    title("What's next")
    print("Run a dry run with the review page:")
    print(f"  cd {shlex.quote(HERE)} && .venv/bin/python plex-smart-logo-updater.py --html")
    print("If your Plex token changes: .venv/bin/python configure.py --token")


if __name__ == "__main__":
    sys.path.insert(0, HERE)
    try:
        main()
    except KeyboardInterrupt:
        print()
        sys.exit("Setup interrupted.")
