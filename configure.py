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

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("PLEX_CONFIG", os.path.join(HERE, "config.env"))
CRON_TAG = "# plex-smart-logo-updater (managed by configure.py)"
CRON_MARK = "# plex-smart-logo-updater"

TOKEN_HELP = "https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/"
LANGUAGE_CHOICES = [
    ("fr-FR,en-US", "French, otherwise English (recommended for French libraries)"),
    ("fr-FR", "French only"),
    ("en-US", "English only"),
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

def read_config(path):
    values = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return values


def write_config(path, values):
    lines = [
        "# plex-smart-logo-updater configuration, written by configure.py.",
        "# Do not publish: this file contains your Plex token and webhooks.",
        f"PLEX_URL={values['PLEX_URL']}",
        f"PLEX_TOKEN={values['PLEX_TOKEN']}",
        f"PLEX_LIBRARIES={values['PLEX_LIBRARIES']}",
        f"PLEX_LANGUAGES={values['PLEX_LANGUAGES']}",
        "# Webhooks for --notify (Discord, Bark or json:<url>), comma-separated",
        f"NOTIFY_URLS={values.get('NOTIFY_URLS', '')}",
    ]
    for key in ("PLEX_LOGS_DIR", "PLEX_OCR_CACHE"):
        if values.get(key):
            lines.append(f"{key}={values[key]}")
    old_umask = os.umask(0o077)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    finally:
        os.umask(old_umask)
    os.chmod(path, 0o600)


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
        text = str(e)
        if "401" in text or "nauthorized" in text:
            text = "token rejected by the server (401)"
        return None, text


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


def step_languages(values):
    title("3. Logo language")
    print("Languages to try, in order. The Quebec logo detection only runs when French comes first.")
    codes = [c for c, _ in LANGUAGE_CHOICES]
    current = values.get("PLEX_LANGUAGES", "fr-FR,en-US")
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
        hour = int(ask("Hour (0-23)", "9") or 9) % 24
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
            step_languages(values)
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
    step_languages(values)
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
