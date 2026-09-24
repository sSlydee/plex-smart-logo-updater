"""
Setup wizard for plex-smart-logo-updater.py.

Asks a few questions, tests the Plex connection and the notifications, then
writes config.env (readable by you only). It can also install the automatic
run in cron. Run it again to change the configuration: current values are
offered as defaults (press Enter to keep them). The questions are in French.

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
    ("fr-FR,en-US", "français, sinon anglais (recommandé)"),
    ("fr-FR", "français uniquement"),
    ("en-US", "anglais uniquement"),
]
DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

def title(text):
    print()
    print(f"── {text} " + "─" * max(0, 60 - len(text)))


def ask(question, default=""):
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{question}{suffix} : ").strip()
    except EOFError:
        print()
        sys.exit("Configuration interrompue.")
    return answer or default


def ask_secret(question, default=""):
    shown = f"{default[:4]}…" if default else ""
    suffix = f" [{shown}, Entrée pour garder]" if default else ""
    if sys.stdin.isatty():
        answer = getpass.getpass(f"{question}{suffix} : ").strip()
    else:
        answer = ask(question)
    return answer or default


def ask_yes(question, default=True):
    hint = "O/n" if default else "o/N"
    answer = ask(f"{question} ({hint})").lower()
    if not answer:
        return default
    return answer.startswith(("o", "y"))


def ask_choice(question, options, default=1):
    """options: list of labels. Returns the chosen index (0-based)."""
    for i, label in enumerate(options, 1):
        print(f"  {i}. {label}")
    while True:
        answer = ask(question, str(default))
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return int(answer) - 1
        print("  Réponse invalide, tape un des numéros ci-dessus.")


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
            text = "token refusé par le serveur (401)"
        return None, text


def step_token(values, token=None):
    """Changes the token only, keeping the server address."""
    title("Token Plex")
    if not values.get("PLEX_URL"):
        sys.exit("Aucune adresse de serveur configurée : lance d'abord configure.py sans option.")
    print(f"Serveur : {values['PLEX_URL']}")
    interactive = token is None
    while True:
        if interactive:
            print(f"Où trouver le token : {TOKEN_HELP}")
            token = ask_secret("Nouveau token Plex (X-Plex-Token)")
        if not token:
            sys.exit("Aucun token saisi : rien n'a changé.")
        plex, error = connect(values["PLEX_URL"], token)
        if plex is not None:
            print(f"  ✓ Connecté à « {plex.friendlyName} » (Plex {plex.version})")
            values["PLEX_TOKEN"] = token
            return plex
        print(f"  ✗ Connexion impossible : {error}")
        if not interactive or not ask_yes("Réessayer ?"):
            sys.exit("Le token n'a pas été changé.")
        token = None


def step_plex(values):
    title("1. Serveur Plex")
    print("Utilise l'adresse LOCALE du serveur (ex. http://192.168.1.100:32400),")
    print("pas un nom de domaine public derrière un reverse proxy.")
    while True:
        url = ask("Adresse du serveur Plex", values.get("PLEX_URL", "http://127.0.0.1:32400")).rstrip("/")
        if not re.match(r"^https?://", url):
            url = "http://" + url
        print(f"Token Plex : voir {TOKEN_HELP}")
        token = ask_secret("Token Plex (X-Plex-Token)", values.get("PLEX_TOKEN", ""))
        plex, error = connect(url, token)
        if plex is None:
            print(f"  ✗ Connexion impossible : {error}")
            if not ask_yes("Réessayer ?"):
                sys.exit("Configuration interrompue.")
            continue
        print(f"  ✓ Connecté à « {plex.friendlyName} » (Plex {plex.version})")
        values["PLEX_URL"], values["PLEX_TOKEN"] = url, token
        return plex


def step_libraries(values, plex):
    title("2. Bibliothèques à traiter")
    sections = [s for s in plex.library.sections() if s.type in ("movie", "show")]
    if not sections:
        sys.exit("Aucune bibliothèque de films ou de séries sur ce serveur.")
    current = [s.strip() for s in values.get("PLEX_LIBRARIES", "").split(",") if s.strip()]
    for i, s in enumerate(sections, 1):
        mark = "x" if s.title in current else " "
        kind = "films" if s.type == "movie" else "séries"
        print(f"  [{mark}] {i:>2}. {s.title} ({kind}, langue {s.language})")
    default = ",".join(str(i) for i, s in enumerate(sections, 1) if s.title in current) or "tout"
    while True:
        answer = ask("Numéros séparés par des virgules, ou « tout »", default).lower()
        if answer in ("tout", "all", "*"):
            chosen = sections
        else:
            try:
                chosen = [sections[int(n) - 1] for n in re.split(r"[\s,;]+", answer) if n]
            except (ValueError, IndexError):
                print("  Réponse invalide.")
                continue
        if chosen:
            break
        print("  Choisis au moins une bibliothèque.")
    names = [s.title for s in chosen]
    if any("," in n for n in names):
        sys.exit("Un nom de bibliothèque contient une virgule : renomme-la dans Plex.")
    values["PLEX_LIBRARIES"] = ",".join(names)
    print(f"  ✓ {len(names)} bibliothèque(s) : {', '.join(names)}")


def step_languages(values):
    title("3. Langue des logos")
    codes = [c for c, _ in LANGUAGE_CHOICES]
    current = values.get("PLEX_LANGUAGES", "fr-FR,en-US")
    labels = [label for _, label in LANGUAGE_CHOICES] + [f"autre (actuel : {current})" if current not in codes
                                                        else "autre (codes Plex, ex. fr-FR,en-US)"]
    default = codes.index(current) + 1 if current in codes else len(labels)
    choice = ask_choice("Choix", labels, default)
    if choice < len(codes):
        values["PLEX_LANGUAGES"] = codes[choice]
    else:
        values["PLEX_LANGUAGES"] = ask("Codes de langue par ordre de préférence", current).replace(" ", "")


def describe_target(kind, url):
    if kind == "bark":
        return "Bark"
    if kind == "discord":
        return "Discord"
    return f"webhook générique ({url.split('/')[2] if '//' in url else url})"


def step_notifications(values):
    import notify
    import requests

    title("4. Notifications (facultatif)")
    targets = notify.parse_targets(values.get("NOTIFY_URLS", ""))
    if targets:
        print("Webhooks actuels : " + ", ".join(describe_target(k, u) for k, u in targets))
        if not ask_yes("Les garder ?"):
            targets = []
    else:
        print("Le script peut te prévenir (Discord, Bark…) quand des titres sont à valider.")
    add = ask_yes("Ajouter un webhook ?", default=not targets)
    while add:
        kind = ask_choice("Type", ["Discord", "Bark", "webhook générique (POST JSON)"], 1)
        if kind == 0:
            url = ask("URL du webhook Discord (Paramètres du salon > Intégrations > Webhooks)")
            targets.append(("discord", url))
        elif kind == 1:
            server = ask("Serveur Bark", "https://api.day.app").rstrip("/")
            key = ask("Clé Bark (affichée dans l'application)")
            targets.append(("bark", f"{server}/{key}"))
        else:
            targets.append(("json", ask("URL du webhook")))
        add = ask_yes("Ajouter un autre webhook ?", default=False)
    values["NOTIFY_URLS"] = ",".join(f"{k}:{u}" for k, u in targets)
    if targets and ask_yes("Envoyer une notification de test ?"):
        session = requests.Session()
        for kind, error in notify.send(session, targets, "Logos Plex : test",
                                       "Les notifications de plex-smart-logo-updater fonctionnent."):
            print(f"  {'✓' if error is None else '✗'} {kind}" + (f" : {error}" if error else ""))


def current_cron():
    try:
        out = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    except FileNotFoundError:
        return None
    return out.stdout if out.returncode == 0 else ""


def step_cron():
    title("5. Analyse automatique (facultatif)")
    existing = current_cron()
    if existing is None:
        print("cron n'est pas disponible sur cette machine : étape ignorée.")
        return
    lines = existing.splitlines()
    ours = [l for l in lines if CRON_MARK in l]
    if ours:
        print("Analyse automatique actuelle : " + ours[0].split(CRON_MARK)[0].strip())
    print("Le script lance une SIMULATION (rien n'est modifié), génère la page de")
    print("contrôle et t'envoie une notification s'il y a des titres à valider.")
    choice = ask_choice("Fréquence", ["aucune" + (" (supprimer l'actuelle)" if ours else ""),
                                      "tous les jours", "une fois par semaine",
                                      "garder la configuration actuelle"], 4 if ours else 3)
    if choice == 3:
        return
    others = [l for l in lines if CRON_MARK not in l]
    if choice == 0:
        new_lines = others
    else:
        hour = int(ask("Heure (0-23)", "9") or 9) % 24
        dow = "*"
        if choice == 2:
            day = ask_choice("Jour", DAYS, 1)
            dow = str((day + 1) % 7)  # cron : 0 = dimanche
        python = os.path.join(HERE, ".venv", "bin", "python")
        command = (f"cd {shlex.quote(HERE)} && mkdir -p logs && {shlex.quote(python)} plex-smart-logo-updater.py "
                   f"--html --notify --quiet >> logs/cron.log 2>&1")
        new_lines = others + [f"0 {hour} * * {dow} {command} {CRON_TAG}"]
    text = "\n".join(new_lines) + ("\n" if new_lines else "")
    subprocess.run(["crontab", "-"], input=text, text=True, check=True)
    print("  ✓ crontab mise à jour.")


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
    print(f"  ✓ Enregistré dans {CONFIG_PATH} (lisible par toi seul)")


def main():
    args = parse_args()
    values = read_config(CONFIG_PATH)
    partial = args.token is not None or args.server or args.libraries or args.language \
        or args.notifications or args.cron

    if partial:
        if not values and not args.cron:
            sys.exit(f"Pas encore de configuration ({CONFIG_PATH}) : lance d'abord configure.py sans option.")
        plex = None
        if args.token is not None:
            plex = step_token(values, args.token or None)
        if args.server:
            plex = step_plex(values)
        if args.libraries:
            if plex is None:
                plex, error = connect(values.get("PLEX_URL", ""), values.get("PLEX_TOKEN", ""))
                if plex is None:
                    sys.exit(f"Connexion à Plex impossible ({error}) : lance configure.py --token.")
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

    print("Configuration de plex-smart-logo-updater")
    print(f"Fichier : {CONFIG_PATH}")
    if values:
        print("Configuration existante trouvée : Entrée pour garder chaque valeur.")
    plex = step_plex(values)
    step_libraries(values, plex)
    step_languages(values)
    step_notifications(values)
    title("Enregistré")
    save(values)
    step_cron()
    title("Et maintenant")
    print("Lance une simulation avec la page de contrôle :")
    print(f"  cd {shlex.quote(HERE)} && .venv/bin/python plex-smart-logo-updater.py --html")
    print("Si ton token Plex change : .venv/bin/python configure.py --token")


if __name__ == "__main__":
    sys.path.insert(0, HERE)
    try:
        main()
    except KeyboardInterrupt:
        print()
        sys.exit("Configuration interrompue.")
