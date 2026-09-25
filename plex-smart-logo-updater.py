"""
Gives every movie/show without a logo the one Plex itself recommends for a
given language (French first, English as a fallback).

Plex only sets a logo automatically when one exists in the library language.
This script fills the gap: it asks Plex's metadata service
(metadata.provider.plex.tv) for the recommended logo in each language, finds
it among the server's candidates and selects it.

Plex does not tell French (France) from French (Quebec) apart. When the Quebec
title differs from the French title, the logo is read with OCR (quebec.py): a
Quebec logo is never set, and a Quebec logo set by Plex is replaced with a logo
showing the French (or original) title when one exists.

By default only titles WITHOUT a logo are handled: an existing logo is never
replaced unless it is a Quebec one.

Configuration lives in config.env (next to the script, see config.env.example)
or in environment variables, which take precedence:
  PLEX_URL        e.g. http://192.168.1.100:32400
  PLEX_TOKEN      your X-Plex-Token
  PLEX_LIBRARIES  comma-separated library names, e.g. "Movies,TV Shows"
  PLEX_LANGUAGES  preference order, e.g. "fr-FR,en-US"; default "auto": each library's
                  own language, then English
  PLEX_LOGS_DIR   logs folder, default: logs/ next to the script
  PLEX_OCR_CACHE  OCR cache, default: .cache-ocr.json next to the script
  PLEX_LOGS_KEEP  dry-run log folders to keep, default: 100 (apply folders are always kept)
  PLEX_IGNORE_FILE  ignore list, default: ignored.json next to the script
  NOTIFY_URLS     webhooks for --notify: Discord, Bark or generic (see notify.py)
  HEALTHCHECK_URL Uptime Kuma push URL (or healthchecks.io URL) pinged after every run

See --help for the options.
"""
import argparse
import atexit
import collections
import contextlib
import io
import json
import os
import re
import time
import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from PIL import Image, ImageChops
from plexapi.server import PlexServer

import envfile
import ignorelist
import quebec
import html_report
import notify as notifier

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

__version__ = "1.4.0"

HERE = os.path.dirname(os.path.abspath(__file__))


envfile.load_into_environ(os.environ.get("PLEX_CONFIG", os.path.join(HERE, "config.env")))

PLEX_URL = os.environ.get("PLEX_URL", "http://LOCAL_IP_ADDRESS:32400")
PLEX_TOKEN = os.environ.get("PLEX_TOKEN", "YOUR_PLEX_TOKEN")
TARGET_LIBRARIES = [s.strip() for s in os.environ.get("PLEX_LIBRARIES", "Movies,TV Shows").split(",")]
LANGUAGES_SETTING = os.environ.get("PLEX_LANGUAGES", "auto").strip() or "auto"
FALLBACK_LANGUAGE = "en-US"


def languages_for(library_language, setting=None):
    """
    Languages to try, in order, for a library. "auto" means the library's own
    language (as set in Plex), then English; otherwise the comma-separated list.
    """
    setting = LANGUAGES_SETTING if setting is None else setting
    if setting.lower() != "auto":
        return [s.strip() for s in setting.split(",") if s.strip()]
    lang = (library_language or "").strip()
    # Plex uses "xn" (no linguistic content) or an empty value when no language is set
    if not lang or lang.lower() in ("xn", "none", "und"):
        return [FALLBACK_LANGUAGE]
    languages = [lang]
    if lang.split("-")[0].lower() != FALLBACK_LANGUAGE.split("-")[0]:
        languages.append(FALLBACK_LANGUAGE)
    return languages


def checks_quebec(languages):
    """Quebec logos are only looked for when French (other than Quebec French) comes first."""
    first = languages[0].lower() if languages else ""
    return first.startswith("fr") and first != "fr-ca"
LOGS_DIR = os.environ.get("PLEX_LOGS_DIR", os.path.join(HERE, "logs"))
OCR_CACHE_PATH = os.environ.get("PLEX_OCR_CACHE", os.path.join(HERE, ".cache-ocr.json"))
IGNORE_PATH = os.environ.get("PLEX_IGNORE_FILE", os.path.join(HERE, "ignored.json"))
# Titles queued by tautulli-hook.sh, processed by --process-queue
QUEUE_PATH = os.path.join(LOGS_DIR, "tautulli-queue.txt")
LOGS_KEEP = int(os.environ.get("PLEX_LOGS_KEEP", "100"))
CRON_LOG_MAX_BYTES = 5 * 1024 * 1024
# Uptime Kuma push URL (or healthchecks.io-style URL) pinged after every run
HEALTHCHECK_URL = os.environ.get("HEALTHCHECK_URL", "").strip()
# DISCORD_WEBHOOK is still accepted for backward compatibility
NOTIFY_TARGETS = notifier.parse_targets(
    " ".join(filter(None, [os.environ.get("NOTIFY_URLS", ""), os.environ.get("DISCORD_WEBHOOK", "")])))

METADATA_PROVIDER = "https://metadata.provider.plex.tv"

# Rate limit, only when Plex is modified (seconds)
DELAY_AFTER_CHANGE = 2.0
BATCH_SIZE = 10
BATCH_PAUSE = 10.0

# Bytes read to get an image's dimensions without downloading all of it
HEADER_BYTES = 64 * 1024


def parse_args():
    p = argparse.ArgumentParser(
        description="Sets French logos on Plex (English as a fallback), without Quebec logos.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  plex-smart-logo-updater.py                          dry run (nothing is changed)
  plex-smart-logo-updater.py --html                   dry run + review page review.html
  plex-smart-logo-updater.py --apply --choices logs/<simulation>/choices.json
                                           apply only what was approved in the review page
  plex-smart-logo-updater.py --apply                  apply everything
  plex-smart-logo-updater.py --undo logs/<application> [--apply]
                                           undo an application (dry run without --apply)
  plex-smart-logo-updater.py --ignore "Movies/Edge of Tomorrow"
                                           never touch this title again (see --unignore)""")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--apply", action="store_true", help="actually change Plex (otherwise: dry run)")
    p.add_argument("--html", action="store_true",
                   help="write the review page review.html in the logs folder")
    p.add_argument("--choices", metavar="FILE",
                   help="choices.json exported from the review page: only apply the approved changes")
    p.add_argument("--choix", dest="choices", help=argparse.SUPPRESS)  # former French name
    p.add_argument("--replace", action="store_true",
                   help="also replace logos set by Plex that differ from its recommendation")
    p.add_argument("--include-locked", action="store_true",
                   help="with --replace: also replace hand-picked (locked) logos (not recommended)")
    p.add_argument("--fix-locked-quebec", action="store_true",
                   help="also replace locked logos detected as Quebec logos")
    p.add_argument("--quiet", action="store_true",
                   help="only print the summary (details stay in the logs): handy for cron")
    p.add_argument("--notify", action="store_true",
                   help="send a summary to the NOTIFY_URLS webhooks (Discord, Bark…) when there is something to do")
    p.add_argument("--rating-key", metavar="KEY", action="append", dest="rating_keys",
                   help="only process these titles (Plex ratingKey; an episode or season counts as its show). "
                        "Used by the Tautulli hook (tautulli-hook.sh)")
    p.add_argument("--process-queue", action="store_true",
                   help="process the titles queued by tautulli-hook.sh (does nothing when the queue is empty)")
    p.add_argument("--ignore", metavar="TITLE", action="append",
                   help='never touch this title again: "Library/Title", "Title (year)" or a ratingKey '
                        "(repeatable)")
    p.add_argument("--unignore", metavar="TITLE", action="append",
                   help="remove a title from the ignore list (repeatable)")
    p.add_argument("--list-ignored", action="store_true", help="show the ignore list")
    p.add_argument("--undo", metavar="FOLDER",
                   help="undo the application recorded in this logs folder (undo.json)")
    return p.parse_args()


# ---------------------------------------------------------------------------
# HTTP access, Plex metadata, images
# ---------------------------------------------------------------------------

def make_session():
    """HTTP session that automatically retries transient errors (429, 5xx)."""
    session = requests.Session()
    session.verify = False
    # Only idempotent methods are retried: a retried POST could upload a logo or notify twice
    retry = Retry(total=4, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET", "PUT", "DELETE"])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


HTTP = make_session()
_PROVIDER_CACHE = {}

TOKEN_FIX = "change it with: .venv/bin/python configure.py --token"


class TokenError(Exception):
    """The Plex token is rejected (401): no point in going on."""


def is_unauthorized(error):
    """True only for a real 401: plexapi's Unauthorized or an HTTP response with status 401."""
    from plexapi.exceptions import Unauthorized
    if isinstance(error, (TokenError, Unauthorized)):
        return True
    return getattr(getattr(error, "response", None), "status_code", None) == 401


def provider_info(item, language):
    """(title, recommended logo URL) from Plex's metadata service, for this language."""
    if not item.guid or not item.guid.startswith("plex://"):
        return None, None
    key = (item.guid, language)
    if key not in _PROVIDER_CACHE:
        headers = {"X-Plex-Token": PLEX_TOKEN, "Accept": "application/json", "X-Plex-Language": language}
        url = f"{METADATA_PROVIDER}/library/metadata/{item.guid.split('/')[-1]}?includeImages=1"
        r = HTTP.get(url, headers=headers, timeout=20)
        if r.status_code == 401:
            raise TokenError("token rejected by Plex's metadata service (401)")
        r.raise_for_status()
        metadata = r.json()["MediaContainer"].get("Metadata", [])
        if not metadata:
            _PROVIDER_CACHE[key] = (None, None)
        else:
            logo = next((i.get("url") for i in metadata[0].get("Image", []) if i.get("type") == "clearLogo"), None)
            _PROVIDER_CACHE[key] = (metadata[0].get("title"), logo)
    return _PROVIDER_CACHE[key]


def recommended_logo(item, language):
    return provider_info(item, language)[1]


def logo_url(plex, logo_or_url):
    if isinstance(logo_or_url, str):
        return logo_or_url
    if logo_or_url.key.startswith("http"):
        return logo_or_url.key
    return plex.url(logo_or_url.key, includeToken=True)


def logo_id(logo_or_url):
    """Stable logo identifier (no token): used as cache key and in choices.json."""
    return logo_or_url if isinstance(logo_or_url, str) else logo_or_url.ratingKey


def image_size(plex, logo_or_url):
    """Image dimensions, reading only the start of the file."""
    with HTTP.get(logo_url(plex, logo_or_url), timeout=30, stream=True) as r:
        r.raise_for_status()
        head = r.raw.read(HEADER_BYTES, decode_content=True)
    return Image.open(io.BytesIO(head)).size


# The last few images downloaded, so the same logo is not fetched again for the
# OCR, the image comparison and the review page thumbnail of the same title
_IMAGE_CACHE = collections.OrderedDict()
IMAGE_CACHE_SIZE = 4  # some logos are 8000 px wide: keep the cache small


def fetch_image(plex, logo_or_url):
    key = logo_id(logo_or_url)
    if key in _IMAGE_CACHE:
        _IMAGE_CACHE.move_to_end(key)
        return _IMAGE_CACHE[key]
    r = HTTP.get(logo_url(plex, logo_or_url), timeout=30)
    r.raise_for_status()
    img = Image.open(io.BytesIO(r.content)).convert("RGBA")
    _IMAGE_CACHE[key] = img
    if len(_IMAGE_CACHE) > IMAGE_CACHE_SIZE:
        _IMAGE_CACHE.popitem(last=False)
    return img


def same_image(a, b):
    return a.size == b.size and ImageChops.difference(a, b).getbbox() is None


def find_candidate(plex, logos, target_url, target_size):
    """
    Finds the server logo matching the recommended logo.
    Returns (index, logo, method) or (None, None, reason).
    """
    for i, logo in enumerate(logos):
        if logo.ratingKey == target_url or logo.key == target_url:
            return i, logo, "same URL"

    same_size = []
    for i, logo in enumerate(logos):
        try:
            if image_size(plex, logo) == target_size:
                same_size.append((i, logo))
        except Exception:
            continue
    if not same_size:
        return None, None, "no candidate of the same size"

    target_img = fetch_image(plex, target_url)
    for i, logo in same_size:
        try:
            if same_image(fetch_image(plex, logo), target_img):
                return i, logo, f"identical image (out of {len(same_size)} of the same size)"
        except Exception:
            continue
    return None, None, f"{len(same_size)} of the same size but none identical"


def is_locked(item):
    return any(f.name == "clearLogo" and f.locked for f in item.fields)


def fmt_size(size):
    return f"{size[0]}x{size[1]}"


# ---------------------------------------------------------------------------
# OCR reading with cache
# ---------------------------------------------------------------------------

class OcrCache:
    """
    Stores the text read, size and colorfulness of each logo. Logos are keyed by
    their URL or Plex key, which change whenever the image changes: the cache
    never goes stale.
    """

    def __init__(self, path):
        self.path = path
        self.dirty = False
        try:
            with open(path, encoding="utf-8") as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}
        self.hits = self.misses = 0

    def read(self, plex, logo_or_url):
        """Returns (text read, (width, height))."""
        key = logo_id(logo_or_url)
        entry = self.data.get(key)
        # Readings made by an older version of the OCR code are redone
        if entry is not None and entry.get("v") == quebec.OCR_VERSION:
            self.hits += 1
            return entry["text"], (entry["w"], entry["h"])
        self.misses += 1
        img = fetch_image(plex, logo_or_url)
        text = quebec.read_text(img)
        self.data[key] = {"text": text, "w": img.width, "h": img.height, "color": colorfulness(img),
                          "v": quebec.OCR_VERSION}
        self.dirty = True
        return text, img.size

    def color(self, plex, logo_or_url):
        """How colorful the logo is (0 = white/grey/black, 1 = very colorful)."""
        key = logo_id(logo_or_url)
        entry = self.data.get(key)
        if entry is not None and "color" in entry:
            return entry["color"]
        value = colorfulness(fetch_image(plex, logo_or_url))
        if entry is not None:
            entry["color"] = value
            self.dirty = True
        return value

    def save(self):
        if not self.dirty:
            return
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False)
        os.replace(tmp, self.path)
        self.dirty = False


def colorfulness(img):
    """Mean saturation of the logo's visible pixels (0..1)."""
    img = img.convert("RGBA")
    img.thumbnail((200, 200))
    alpha = img.getchannel("A")
    sat = img.convert("RGB").convert("HSV").getchannel("S")
    total = weight = 0
    for a, s in zip(alpha.getdata(), sat.getdata()):
        if a > 128:
            total += s
            weight += 1
    return round(total / weight / 255, 3) if weight else 0.0


# Two logos have the "same style" when their colorfulness differs by less than this
SAME_STYLE = 0.12

OCR = OcrCache(OCR_CACHE_PATH)
atexit.register(OCR.save)


def read_logo(plex, logo_or_url, titles):
    """Reads the logo and returns (verdict, text read)."""
    text, _ = OCR.read(plex, logo_or_url)
    return quebec.verdict(text, *titles)[0], text


def best_french_candidate(plex, logos, titles, exclude=(), plex_picks=(), current=None):
    """
    Best non-Quebec logo among the server's logos: first those whose text is
    closest to the French title, otherwise to the original title; at similar
    closeness, those without extra text (actor names, taglines), then those in
    the same style as the current logo (colored or white), then the one Plex
    recommends (plex_picks), then the largest.
    Returns (index, logo, text read, kind, mention) or (None,) * 5.
    """
    current_color = None
    if current is not None:
        try:
            current_color = OCR.color(plex, current)
        except Exception:
            pass
    best = None
    for i, logo in enumerate(logos):
        if i in exclude:
            continue
        try:
            text, size = OCR.read(plex, logo)
        except Exception:
            continue
        kind, score = quebec.replacement_kind(text, *titles)
        if kind is None:
            continue
        title = titles[0] if kind == quebec.FR else titles[2]
        clean = quebec.is_clean(text, title)
        same_style = current_color is None or abs(OCR.color(plex, logo) - current_color) < SAME_STYLE
        is_pick = logo.ratingKey in plex_picks or logo.key in plex_picks
        rank = (quebec.PREFERENCE[kind], round(score / 0.1), clean, same_style, is_pick, size[0] * size[1])
        if best is None or rank > best[0]:
            best = (rank, i, logo, text, kind)
    if best is None:
        return (None,) * 5
    _, i, logo, text, kind = best
    if kind == quebec.ORIGINAL:
        mention = "original"
    elif quebec.verdict(text, *titles)[0] == quebec.FR:
        mention = None
    else:
        mention = "inferred"
    return i, logo, text, kind, mention


# ---------------------------------------------------------------------------
# Categories, mentions, logs
# ---------------------------------------------------------------------------

LANGUAGE_NAMES = {"fr": "French", "en": "English", "ja": "Japanese", "de": "German",
                  "es": "Spanish", "it": "Italian", "pt": "Portuguese", "nl": "Dutch"}

# Result categories: (short tag in the details, summary label)
CATEGORIES = {
    "add":        ("ADDED",        "Logo added (there was none)"),
    "replace":    ("REPLACED",     "Logo replaced"),
    "ok":         ("OK",           "Already the right logo, nothing to do"),
    "kept":       ("KEPT",         "Skipped: a logo is already set, kept"),
    "locked":     ("LOCKED",       "Skipped: hand-picked logo (locked)"),
    "none":       ("NONE",         "Skipped: Plex offers no logo"),
    "check":      ("CHECK",        "Skipped: only a Quebec logo is available"),
    "refused":    ("REJECTED",     "Skipped: rejected in the review page"),
    "unreviewed": ("NOT REVIEWED", "Skipped: missing from the choices file"),
    "changed":    ("RECHECK",      "Skipped: the planned logo changed since the dry run"),
    "ignored":    ("IGNORED",      "Skipped: on the ignore list"),
    "error":      ("ERROR",        "Error"),
}
SIM_CATEGORIES = dict(CATEGORIES,
                      add=("TO ADD", "Logo to add (there is none)"),
                      replace=("TO REPLACE", "Logo to replace"))
CHOICE_KEYS = ("refused", "unreviewed", "changed")

# Special mentions, appended after the tag (on top of the category)
MENTIONS = {
    "inferred":   ("FRENCH INFERRED", "the French title is read on the logo, the Quebec words are missing"),
    "original":   ("ORIGINAL TITLE", "the logo shows the original title, neither French nor Quebec"),
    "unverified": ("NOT VERIFIED", "logo unreadable by OCR, set without verification: check it"),
}
MENTION_OF = {quebec.FR_GUESS: "inferred", quebec.ORIGINAL: "original", quebec.UNKNOWN: "unverified"}
# locked_qc: locked logo that looks like a Quebec one (reported; only changed with --fix-locked-quebec)
EXTRA_KEYS = ("locked_qc",) + tuple(MENTIONS)

LINE = "=" * 72
THIN = "-" * 72


def categories_for(opts):
    cats = CATEGORIES if opts.apply else SIM_CATEGORIES
    if not opts.choices:
        cats = {k: v for k, v in cats.items() if k not in CHOICE_KEYS}
    return cats


def empty_results():
    return {k: [] for k in list(CATEGORIES) + list(EXTRA_KEYS)}


def lang_name(code):
    return LANGUAGE_NAMES.get(code.split("-")[0], code)


class Log:
    """Writes to a file and, unless echo=False, also prints to the screen."""

    def __init__(self, path, echo=True):
        self.file = open(path, "w", encoding="utf-8")
        self.echo = echo

    def __call__(self, msg=""):
        if self.echo:
            print(msg, flush=True)
        self.file.write(msg + "\n")
        self.file.flush()

    def close(self):
        self.file.close()


def safe_filename(name):
    return "".join("_" if c in '\\/:*?"<>|' else c for c in name).strip()


def minutes(seconds):
    m, s = divmod(int(seconds), 60)
    return f"{m} min {s:02d} s"


def write_header(log, title, opts, extra=(), languages=None):
    log(LINE)
    log(f"  {title}")
    log(LINE)
    log(f"  Date        : {time.strftime('%Y-%m-%d %H:%M')}")
    log(f"  Mode        : {'APPLY (logos are changed)' if opts.apply else 'DRY RUN (nothing is changed)'}")
    if opts.choices:
        log(f"  Choices     : {opts.choices} (only approved changes are applied)")
    for line in extra:
        log(f"  {line}")
    log("")
    log("  Rules:")
    if languages is None:
        if LANGUAGES_SETTING.lower() == "auto":
            log("    1. Use the logo Plex recommends in each library's language, otherwise in English.")
        else:
            log(f"    1. Use the logo Plex recommends in "
                f"{', otherwise in '.join(lang_name(l) for l in languages_for(None))}.")
    else:
        log(f"    1. Use the logo Plex recommends in {', otherwise in '.join(lang_name(l) for l in languages)}.")
    if not opts.replace:
        log("    2. Only titles WITHOUT a logo are handled (even if the field is locked);")
        log("       an existing logo is kept.")
    elif opts.include_locked:
        log("    2. Existing logos may be replaced, including hand-picked ones.")
    else:
        log("    2. Logos set by Plex may be replaced; hand-picked ones never.")
    log("    3. When the Quebec title differs from the French title, the logo is read (OCR):")
    log("       a Quebec logo is never set, and a Quebec logo set by Plex is replaced")
    log("       with a logo showing the French (or original) title when one exists.")
    if opts.fix_locked_quebec:
        log("       Locked logos detected as Quebec logos are ALSO replaced.")
    log("")
    log("  Legend:")
    cats = categories_for(opts)
    width = max(len(tag) for tag, _ in list(cats.values()) + list(MENTIONS.values())) + 2
    for tag, label in cats.values():
        log(f"    {('[' + tag + ']').ljust(width)}  {label}")
    log("")
    log("  Special mentions (after the tag, only when the Quebec title differs")
    log("  from the French title):")
    for tag, label in MENTIONS.values():
        log(f"    {('[' + tag + ']').ljust(width)}  {label}")
    log(LINE)


def write_counts(log, results, cats, indent="  "):
    width = max(len(label) for _, label in cats.values())
    for key, (_, label) in cats.items():
        log(f"{indent}{label.ljust(width + 3, '.')} {len(results[key]):>5}")
    log(f"{indent}{'TOTAL'.ljust(width + 3, '.')} {sum(len(results[k]) for k in cats):>5}")


def write_mentions(log, results):
    """Lists of special mentions, to be checked by hand."""
    sections = [
        ("locked_qc", "WARNING, locked logos that look like Quebec logos"),
        ("unverified", f"[{MENTIONS['unverified'][0]}] logos set without verification, check them"),
        ("original", f"[{MENTIONS['original'][0]}] logos set with the original title"),
        ("inferred", f"[{MENTIONS['inferred'][0]}] logos set where French is inferred"),
    ]
    for key, title in sections:
        if results[key]:
            log("")
            log(f"  {title} ({len(results[key])}):")
            for t in results[key]:
                log(f"    - {t}")


# ---------------------------------------------------------------------------
# Decision for one title
# ---------------------------------------------------------------------------

class Plan:
    """What to do for one title."""

    def __init__(self):
        self.category = None      # key of CATEGORIES
        self.detail = ""
        self.mention = None       # key of MENTIONS
        self.candidate = None     # server logo to select
        self.index = None
        self.target_url = None    # otherwise: URL to upload
        self.language = None
        self.current = None
        self.current_index = None
        self.locked = False
        self.current_is_qc = False
        self.titles = (None, None, None)  # French, Quebec, original
        self.chosen = ""          # description of the chosen logo

    @property
    def target_id(self):
        return logo_id(self.candidate) if self.candidate is not None else self.target_url

    @property
    def is_change(self):
        return self.category in ("add", "replace")


def keeps_locked_logo(plan, opts):
    """
    True when a locked (hand-picked) logo must be left alone. A locked field
    WITHOUT a logo is not protected: a logo is proposed like for any title
    without one, and rejecting it in the review page puts the title on the
    ignore list.
    """
    if not plan.locked or plan.current is None:
        return False
    if opts.replace and opts.include_locked:
        return False
    return not (plan.current_is_qc and opts.fix_locked_quebec)


def plan_item(plex, item, logos, log, opts, languages):
    """Inspects a title and decides what to do, without changing anything."""
    plan = Plan()
    plan.current_index, plan.current = next(((i, l) for i, l in enumerate(logos) if l.selected), (None, None))
    plan.locked = is_locked(item)

    if plan.current is None:
        log("  Current logo     : none")
    else:
        who = "hand-picked (locked)" if plan.locked else "set automatically by Plex"
        log(f"  Current logo     : #{plan.current_index + 1} of {len(logos)} "
            f"({plan.current.provider or 'local file'}), {who}")

    # Risk of a Quebec logo: the Quebec title differs from the French title
    risky = False
    if checks_quebec(languages):
        fr_title = provider_info(item, languages[0])[0]
        ca_title = provider_info(item, "fr-CA")[0]
        risky = quebec.titles_differ(fr_title, ca_title)
        if risky:
            en_title = provider_info(item, "en-US")[0]
            plan.titles = (fr_title, ca_title, en_title)
            log(f"  Titles           : France \"{fr_title}\" | Quebec \"{ca_title}\" | original \"{en_title}\"")

    if plan.current is not None and risky:
        v, text = read_logo(plex, plan.current, plan.titles)
        plan.current_is_qc = v == quebec.QC
        log(f"  Logo reads       : \"{text}\" -> {v}")

    if keeps_locked_logo(plan, opts):
        plan.category = "locked"
        plan.detail = "left untouched"
        if plan.current_is_qc:
            plan.detail += " (WARNING: this logo looks like a Quebec logo, see --fix-locked-quebec)"
        return plan
    if plan.locked and plan.current is None:
        log("  Note             : the logo field is locked but empty: a logo is proposed "
            "(reject it to keep the title without a logo)")

    if plan.current is not None and not opts.replace and not plan.current_is_qc:
        plan.category, plan.detail = "kept", "a logo is already set, left untouched"
        return plan

    # Logo recommended by Plex
    searched = []
    for lang in languages:
        url = recommended_logo(item, lang)
        searched.append(f"{lang_name(lang)}: {'found' if url else 'none'}")
        if url:
            plan.target_url, plan.language = url, lang
            break
    log(f"  Plex search      : {' | '.join(searched)}")

    if not plan.target_url and not plan.current_is_qc:
        plan.category = "none"
        plan.detail = f"{len(logos)} logo(s) available, but Plex recommends none"
        return plan

    # Is the recommended logo really French? A Quebec one is discarded; if it is
    # not clearly French, look for a logo showing the French title first
    rec_verdict = None
    if plan.target_url and risky:
        rec_verdict, text = read_logo(plex, plan.target_url, plan.titles)
        log(f"  Recommended reads: \"{text}\" -> {rec_verdict}")
        if rec_verdict == quebec.QC:
            plan.target_url = None
        else:
            plan.mention = MENTION_OF.get(rec_verdict)
    # Looking for something better than the recommended logo only makes sense when
    # the French title differs from the original one (otherwise Plex's pick is kept)
    fr_differs = quebec.normalize(plan.titles[0]) != quebec.normalize(plan.titles[2])
    if risky and (plan.current_is_qc or plan.target_url is None or (rec_verdict != quebec.FR and fr_differs)):
        exclude = {plan.current_index} if plan.current_is_qc else set()
        picks = {u for u in (recommended_logo(item, lang) for lang in languages) if u}
        index, candidate, text, kind, mention = best_french_candidate(
            plex, logos, plan.titles, exclude, picks, current=plan.current if plan.current_is_qc else None)
        # An acceptable recommended logo is only replaced by one showing the French title
        if candidate is not None and (plan.target_url is None or kind == quebec.FR):
            plan.index, plan.candidate, plan.target_url = index, candidate, None
            plan.mention = mention
            plan.chosen = f"logo \"{text}\" ({kind})"
            log(f"  OCR choice       : candidate #{index + 1} of {len(logos)} ({candidate.provider}), \"{text}\" -> {kind}")

    if plan.candidate is None and plan.target_url is None:
        what = "the current logo is a Quebec logo" if plan.current_is_qc else "the recommended logo is a Quebec logo"
        plan.category = "check"
        plan.detail = f"{what} and no other acceptable logo was found: do it by hand"
        return plan

    if plan.candidate is None:
        target_size = image_size(plex, plan.target_url)
        log(f"  Recommended logo : {lang_name(plan.language)}, {fmt_size(target_size)} px")
        log(f"  Image link       : {plan.target_url}")

        if plan.current is not None and not plan.current_is_qc and image_size(plex, plan.current) == target_size \
                and same_image(fetch_image(plex, plan.current), fetch_image(plex, plan.target_url)):
            plan.category = "ok"
            plan.detail = f"the current logo is already the recommended {lang_name(plan.language)} one"
            return plan

        index, candidate, method = find_candidate(plex, logos, plan.target_url, target_size)
        if candidate is not None:
            plan.index, plan.candidate = index, candidate
            log(f"  Found on Plex    : candidate #{index + 1} of {len(logos)} ({candidate.provider}), {method}")
            plan.target_url = None
        else:
            log(f"  Found on Plex    : no ({method}), it will be uploaded from its link")
        plan.chosen = f"{lang_name(plan.language)} logo {fmt_size(target_size)} px"

    plan.category = "replace" if plan.current is not None else "add"
    plan.detail = plan.chosen
    if plan.current is not None:
        plan.detail += f", instead of #{plan.current_index + 1}" + (" (Quebec)" if plan.current_is_qc else "")
    if plan.mention:
        plan.detail += f"  [{MENTIONS[plan.mention][0]}]"
    return plan


# ---------------------------------------------------------------------------
# Applying, undo journal, review page
# ---------------------------------------------------------------------------

class UndoJournal:
    """
    undo.json: the state of each logo before and after the change. An entry is
    written BEFORE the change and completed afterwards, so a change interrupted
    halfway (Plex error, crash) can still be undone: its "after" stays null.
    """

    def __init__(self, path):
        self.path = path
        self.entries = []

    def add(self, entry):
        """Records an entry and returns it; update it with complete()."""
        self.entries.append(entry)
        self._save()
        return entry

    def complete(self, entry, after):
        entry["after"] = after
        self._save()

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"format": "plex-smart-logo-updater/undo-v1", "entries": self.entries},
                      f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)


def selected_key(item):
    return next((l.ratingKey for l in item.logos() if l.selected), None)


def apply_plan(item, plan):
    """Selects (or uploads) the planned logo."""
    if plan.candidate is not None:
        plan.candidate.select()
    else:
        item.uploadLogo(url=plan.target_url)


def thumb(plex, logo_or_url):
    try:
        return html_report.thumbnail(fetch_image(plex, logo_or_url))
    except Exception:
        return None


def html_card(plex, section, item, label, plan, cats, decidable):
    before = thumb(plex, plan.current) if plan.current is not None else None
    after = None
    if plan.is_change:
        after = thumb(plex, plan.candidate if plan.candidate is not None else plan.target_url)
    category_label = cats.get(plan.category, CATEGORIES[plan.category])[1]
    if plan.category == "locked" and plan.current_is_qc:
        category_label = "Locked logo that looks like a Quebec logo (--fix-locked-quebec to replace it)"
    mention_label = MENTIONS[plan.mention][0].capitalize() if plan.mention else ""
    return html_report.card(section.title, item, label, plan, before, after, decidable,
                            category_label, mention_label)


def load_choices(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("format") not in html_report.CHOICES_FORMATS:
        raise SystemExit(f"[!] {path} is not a choices file from the review page.")
    return data.get("decisions", {})


def process_library(plex, section, log, opts, ctx, languages, items=None):
    cats = categories_for(opts)
    results = empty_results()
    items = section.all() if items is None else items

    def status(key, detail):
        log(f"  ==> [{cats.get(key, CATEGORIES[key])[0]}] {detail}")

    for n, item in enumerate(items, 1):
        year = f" ({item.year})" if getattr(item, "year", None) else ""
        label = f"{item.title}{year}"
        log("")
        log(f"[{n}/{len(items)}] {label}")
        if item.ratingKey in ctx.ignored:
            status("ignored", f"on the ignore list ({ctx.ignored.get(item.ratingKey)['reason']})")
            results["ignored"].append(label)
            continue
        try:
            logos = item.logos()
            plan = plan_item(plex, item, logos, log, opts, languages)

            if plan.category == "locked" and plan.current_is_qc:
                results["locked_qc"].append(label)

            if not plan.is_change:
                status(plan.category, plan.detail)
                results[plan.category].append(label)
                if ctx.html is not None and (plan.category == "check" or
                                             (plan.category == "locked" and plan.current_is_qc)):
                    ctx.html.append(html_card(plex, section, item, label, plan, cats, decidable=False))
                continue

            # Filter by the choices made in the review page
            if ctx.choices is not None:
                decision = ctx.choices.get(str(item.ratingKey))
                if decision is None:
                    status("unreviewed", "this title was not in the review page")
                    results["unreviewed"].append(label)
                    continue
                if not decision.get("ok"):
                    detail = plan.detail
                    if opts.apply:
                        ctx.ignored.add(item.ratingKey, section.title, item.title, getattr(item, "year", None),
                                        ignorelist.REASON_REJECTED)
                        ctx.ignored.save()
                        detail += " (added to the ignore list, see --unignore)"
                    status("refused", detail)
                    results["refused"].append(label)
                    continue
                if decision.get("target") != plan.target_id:
                    status("changed", "the planned logo is no longer the same as in the dry run: run a new dry run")
                    results["changed"].append(label)
                    continue

            if opts.apply:
                entry = ctx.journal.add({
                    "ratingKey": item.ratingKey, "library": section.title, "title": label,
                    "before": logo_id(plan.current) if plan.current is not None else None,
                    "before_locked": plan.locked, "after": None,
                })
                apply_plan(item, plan)
                if plan.locked and not opts.include_locked:
                    item.lockLogo()  # keep a hand-picked logo locked (--fix-locked-quebec)
                ctx.journal.complete(entry, selected_key(item))
                ctx.changes += 1
                status(plan.category, plan.detail)
                if ctx.changes % BATCH_SIZE == 0:
                    log(f"  (pausing {BATCH_PAUSE:.0f} s to spare the server)")
                    time.sleep(BATCH_PAUSE)
                else:
                    time.sleep(DELAY_AFTER_CHANGE)
            else:
                status(plan.category, plan.detail)

            note = lang_name(plan.language) if plan.language and plan.chosen.startswith(lang_name(plan.language) + " logo") \
                else "picked by OCR"
            if plan.current_is_qc:
                note += ", replaces a Quebec logo"
            results[plan.category].append(f"{label} ({note})")
            if plan.mention:
                results[plan.mention].append(label)

            if not opts.apply:
                ctx.pending[str(item.ratingKey)] = plan.target_id
            if ctx.html is not None:
                ctx.html.append(html_card(plex, section, item, label, plan, cats, decidable=not opts.apply))

        except Exception as e:
            if is_unauthorized(e):
                raise TokenError(str(e)) from e
            status("error", str(e))
            results["error"].append(f"{label}: {e}")

    return results


def write_library_summary(log, name, results, opts, duration):
    cats = categories_for(opts)
    log("")
    log(LINE)
    log(f"  SUMMARY: {name}")
    log(LINE)
    log(f"  Duration: {minutes(duration)}")
    log("")
    write_counts(log, results, cats)
    for key in ("add", "replace", "check", "refused", "changed", "unreviewed", "none", "ignored", "error"):
        if key in cats and results[key]:
            log("")
            log(f"  {cats[key][1]} ({len(results[key])}):")
            for title in results[key]:
                log(f"    - {title}")
    write_mentions(log, results)
    if not opts.apply and (results["add"] or results["replace"]):
        log("")
        log("  Dry run only: run again with --apply to apply.")
    log(LINE)


class Context:
    def __init__(self):
        self.changes = 0
        self.journal = None
        self.choices = None
        self.html = None
        self.ignored = None
        self.pending = {}  # ratingKey -> planned logo, for changes to review


def new_run_dir(mode):
    """A new, unique logs folder: two runs started in the same second get "_2", "_3"…"""
    base = os.path.join(LOGS_DIR, time.strftime("%Y-%m-%d_%Hh%Mm%S") + "_" + mode)
    path, n = base, 1
    while True:
        try:
            os.makedirs(path)
            return path
        except FileExistsError:
            n += 1
            path = f"{base}_{n}"


@contextlib.contextmanager
def run_lock():
    """
    Runs one at a time: Tautulli may start several runs at once (one per imported
    episode); they wait for each other instead of sharing the cache and logs.
    """
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(os.path.join(LOGS_DIR, ".run.lock"), "w") as lock:
        try:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        except ImportError:  # not available on Windows
            pass
        yield


def prune_logs():
    """
    Deletes the oldest dry-run log folders beyond LOGS_KEEP. Folders holding an
    undo journal (apply runs) are always kept. cron.log is trimmed to its most
    recent part when it grows beyond CRON_LOG_MAX_BYTES.
    """
    import shutil
    try:
        names = sorted(os.listdir(LOGS_DIR))
    except OSError:
        return
    dry_runs = [n for n in names
                if os.path.isdir(os.path.join(LOGS_DIR, n))
                and re.search(r"_(simulation|undo-simulation)(_\d+)?$", n)
                and not any(os.path.exists(os.path.join(LOGS_DIR, n, f)) for f in ("undo.json", "annulation.json"))]
    for name in dry_runs[:max(0, len(dry_runs) - LOGS_KEEP)]:
        shutil.rmtree(os.path.join(LOGS_DIR, name), ignore_errors=True)

    cron_log = os.path.join(LOGS_DIR, "cron.log")
    try:
        if os.path.getsize(cron_log) > CRON_LOG_MAX_BYTES:
            with open(cron_log, "rb") as f:
                f.seek(-CRON_LOG_MAX_BYTES // 2, os.SEEK_END)
                tail = f.read()
            with open(cron_log, "wb") as f:
                f.write(tail[tail.find(b"\n") + 1:])
    except OSError:
        pass


def run(opts):
    start = time.time()
    mode = "application" if opts.apply else "simulation"
    cats = categories_for(opts)

    run_dir = new_run_dir(mode)
    prune_logs()
    summary = Log(os.path.join(run_dir, "_summary.txt"))

    ctx = Context()
    ctx.ignored = ignorelist.IgnoreList(IGNORE_PATH)
    if opts.choices:
        ctx.choices = load_choices(opts.choices)
    if opts.apply:
        ctx.journal = UndoJournal(os.path.join(run_dir, "undo.json"))
    if opts.html:
        ctx.html = []

    try:
        plex = PlexServer(PLEX_URL, PLEX_TOKEN, session=HTTP)
        server = f"{plex.friendlyName} (Plex {plex.version})"
    except Exception as e:
        stop(opts, summary, e)
        return

    write_header(summary, "OVERALL SUMMARY — Plex logos", opts,
                 [f"Server      : {server}", f"Folder      : {run_dir}"])

    sections = {s.title: s for s in plex.library.sections()}
    missing = [name for name in TARGET_LIBRARIES if name not in sections]
    if missing:
        summary("")
        summary(f"  [!] Libraries not found: {', '.join(missing)}")
        summary(f"      Available: {', '.join(sections)}")

    totals = empty_results()
    per_library = []

    selected = None
    if opts.rating_keys:
        selected = select_titles(plex, opts.rating_keys, summary)

    for name in TARGET_LIBRARIES:
        section = sections.get(name)
        if section is None or (selected is not None and name not in selected):
            continue
        lib_start = time.time()
        log = Log(os.path.join(run_dir, safe_filename(name) + ".txt"), echo=not opts.quiet)
        languages = languages_for(section.language)
        write_header(log, f"LIBRARY: {name}", opts,
                     [f"Content     : {section.totalSize} title(s), language {section.language}"
                      + (f"; {len(selected[name])} selected with --rating-key" if selected is not None else ""),
                      f"Logo langs  : {' > '.join(languages)}"
                      + (" (+ Quebec logo detection)" if checks_quebec(languages) else "")],
                     languages=languages)
        try:
            results = process_library(plex, section, log, opts, ctx, languages,
                                      selected[name] if selected is not None else None)
        except TokenError as e:
            log(f"\n[!] Stopped: {e}")
            log.close()
            stop(opts, summary, e)
            return
        write_library_summary(log, name, results, opts, time.time() - lib_start)
        log.close()
        OCR.save()
        if not opts.quiet:
            print()

        per_library.append((name, results))
        for key in totals:
            totals[key].extend(f"{name} > {t}" for t in results[key])

    # Per-library table
    cols = [("add", "Add"), ("replace", "Replace"), ("ok", "OK"), ("kept", "Kept"),
            ("locked", "Locked"), ("none", "None"), ("check", "Check"), ("ignored", "Ignored"), ("error", "Error")]
    if opts.choices:
        cols[-1:-1] = [("refused", "Rejected"), ("changed", "Recheck"), ("unreviewed", "NoReview")]
    cols += [("inferred", "Inferred"), ("original", "Original"), ("unverified", "NotVerif")]
    name_w = max([len(n) for n, _ in per_library] + [12])
    summary("")
    summary("  PER LIBRARY")
    summary("  (Inferred / Original / NotVerif: special mentions, already counted in Add or Replace)")
    summary("  " + "Library".ljust(name_w) + "".join(f"{c:>9}" for _, c in cols))
    summary("  " + "-" * (name_w + 9 * len(cols)))
    for name, results in per_library:
        row = "".join(f"{len(results[k]) if results[k] else '-':>9}" for k, _ in cols)
        summary("  " + name.ljust(name_w) + row)
    summary("  " + "-" * (name_w + 9 * len(cols)))
    summary("  " + "TOTAL".ljust(name_w) + "".join(f"{len(totals[k]):>9}" for k, _ in cols))

    summary("")
    summary(LINE)
    summary(f"  TOTAL ({minutes(time.time() - start)})")
    summary(LINE)
    write_counts(summary, totals, cats)
    # Details of the additions are in each library's file
    for key in ("replace", "check", "refused", "changed", "unreviewed", "none", "ignored", "error"):
        if key in cats and totals[key]:
            summary("")
            summary(f"  {cats[key][1]} ({len(totals[key])}):")
            for title in totals[key]:
                summary(f"    - {title}")
    write_mentions(summary, totals)
    summary("")
    summary(f"  OCR reads: {OCR.misses} new, {OCR.hits} from the cache.")
    summary("  Title-by-title details: one file per library in this folder.")
    to_do = len(totals["add"]) + len(totals["replace"])
    page = None
    if ctx.html:
        page = os.path.join(run_dir, "review.html")
        html_report.write(page, run_dir=os.path.basename(run_dir), apply=opts.apply, cards=ctx.html)
        summary(f"  Review page: {page}")
        if not opts.apply and to_do:
            summary("  Open it, approve or reject each change, then export choices.json and run:")
            summary(f"    plex-smart-logo-updater.py --apply --choices {os.path.join(run_dir, 'choices.json')}")
    elif ctx.html is not None:
        summary("  Review page: not generated, there is nothing to review.")
    if opts.apply:
        if to_do:
            summary(f"  To undo everything: plex-smart-logo-updater.py --undo {run_dir} --apply")
    elif to_do:
        summary("  Dry run only: run again with --apply to apply.")
    else:
        summary("  Nothing to do: all titles are up to date.")
    summary(LINE)
    summary.close()

    if opts.notify:
        notify(opts, run_dir, totals, page, time.time() - start, ctx.pending)
    to_do = len(totals["add"]) + len(totals["replace"])
    ping_healthcheck(not totals["error"],
                     f"{len(totals['error'])} error(s)" if totals["error"]
                     else f"{to_do} change(s) to review" if to_do and not opts.apply
                     else "ok", time.time() - start)


def select_titles(plex, rating_keys, summary):
    """
    Titles to process for --rating-key, grouped by library: {library: [items]}.
    An episode or a season counts as its show; unknown keys and titles outside the
    configured libraries are reported and skipped.
    """
    selected, seen = {}, set()
    keys = [k for value in rating_keys for k in re.split(r"[\s,]+", value) if k]
    for key in keys:
        try:
            item = plex.fetchItem(int(key))
            if item.type == "episode":
                item = plex.fetchItem(int(item.grandparentRatingKey))
            elif item.type == "season":
                item = plex.fetchItem(int(item.parentRatingKey))
        except Exception as e:
            summary(f"  [!] ratingKey {key}: {e}")
            continue
        if item.type not in ("movie", "show"):
            summary(f"  [!] ratingKey {key}: {item.type} titles have no logo, skipped")
            continue
        library = item.librarySectionTitle
        if library not in TARGET_LIBRARIES:
            summary(f"  [i] {item.title}: library \"{library}\" is not in PLEX_LIBRARIES, skipped")
            continue
        if item.ratingKey in seen:
            continue
        seen.add(item.ratingKey)
        selected.setdefault(library, []).append(item)
    summary(f"  Selected    : {len(seen)} title(s) from {len(keys)} ratingKey(s)")
    return selected


def ping_healthcheck(ok, message, duration=None):
    """Heartbeat for Uptime Kuma (HEALTHCHECK_URL): up after a run, down when it failed."""
    if not HEALTHCHECK_URL:
        return
    error = notifier.heartbeat(HTTP, HEALTHCHECK_URL, ok, message, duration)
    print(f"Healthcheck: {'sent' if error is None else 'failed (' + error + ')'} ({'up' if ok else 'down'})")


def stop(opts, summary, error):
    """Stops on a connection error: clear message, notification and healthcheck "down"."""
    if is_unauthorized(error):
        message = f"Plex token rejected: {TOKEN_FIX}"
    else:
        message = f"Cannot connect to the Plex server ({PLEX_URL}): {error}"
    summary("")
    summary(f"  [!] {message}")
    summary(LINE)
    summary.close()
    if opts.notify and NOTIFY_TARGETS:
        for kind, err in notifier.send(HTTP, NOTIFY_TARGETS, "Plex logos: run failed", message):
            print(f"Notification {kind}: {'sent' if err is None else 'failed (' + err + ')'}")
    ping_healthcheck(False, message)


def new_manual_titles(manual, state_path):
    """
    Titles to handle by hand ([CHECK], locked Quebec logos) that were not already
    reported by a previous notification. The state file is updated with the
    current list, so a title that is fixed and comes back is reported again.
    """
    try:
        with open(state_path, encoding="utf-8") as f:
            already = set(json.load(f))
    except (OSError, ValueError):
        already = set()
    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(sorted(manual), f, ensure_ascii=False, indent=1)
    except OSError:
        pass
    return [t for t in manual if t not in already]


def new_pending_changes(pending, state_path, targeted):
    """
    Changes to review that were not already notified. A full run notifies every
    pending change (weekly reminder) and resets the state; a targeted run
    (--rating-key, e.g. from Tautulli) only reports changes not notified yet, so
    a season of 10 episodes does not send 10 notifications for the same show.
    """
    try:
        with open(state_path, encoding="utf-8") as f:
            already = json.load(f)
    except (OSError, ValueError):
        already = {}
    new = {k: v for k, v in pending.items() if already.get(k) != v}
    state = dict(already, **pending) if targeted else dict(pending)
    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
    except OSError:
        pass
    return new if targeted else dict(pending)


def notify(opts, run_dir, totals, page, duration, pending=None):
    """
    Summary sent to the webhooks, only when there is something to do (changes,
    errors) or NEW titles to handle by hand: those already reported by an
    earlier run do not trigger a notification every week.
    """
    to_do = len(totals["add"]) + len(totals["replace"])
    manual = totals["check"] + totals["locked_qc"]
    new_manual = new_manual_titles(manual, os.path.join(LOGS_DIR, ".notified-manual.json"))
    if not opts.apply:
        new_pending = new_pending_changes(pending or {}, os.path.join(LOGS_DIR, ".notified-pending.json"),
                                          targeted=bool(opts.rating_keys))
        if not new_pending:
            to_do = 0  # already notified: a targeted run stays quiet
    if not (to_do or totals["error"] or new_manual):
        return
    if not NOTIFY_TARGETS:
        print("[!] --notify: no webhook in NOTIFY_URLS, no notification sent.")
        return
    verb = "applied" if opts.apply else "to review"
    title = f"Plex logos: {to_do} change(s) {verb}" if to_do else "Plex logos: titles to handle by hand"
    lines = []
    if to_do:
        lines.append(f"{len(totals['add'])} addition(s), {len(totals['replace'])} Quebec logo(s) replaced")
    if totals["unverified"]:
        lines.append(f"{len(totals['unverified'])} not verified by OCR, look at them first")
    if new_manual:
        lines.append(f"{len(new_manual)} new title(s) to handle by hand ({len(manual)} in total): "
                     + ", ".join(new_manual[:5]) + ("…" if len(new_manual) > 5 else ""))
    if totals["error"]:
        lines.append(f"{len(totals['error'])} error(s)")
    if page and not opts.apply and to_do:
        lines.append(f"Review page: {page}")
    lines.append(f"Logs: {os.path.basename(run_dir.rstrip('/'))} ({minutes(duration)})")
    body = "\n".join(lines)
    markdown = "\n".join(f"• {l}" if not l.startswith(("Review page", "Logs")) else f"`{l}`" for l in lines)
    for kind, error in notifier.send(HTTP, NOTIFY_TARGETS, title, body, markdown):
        print(f"Notification {kind}: {'sent' if error is None else 'failed (' + error + ')'}")


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------

def undo(opts):
    # undo.json; annulation.json is the former French name
    path = os.path.join(opts.undo, "undo.json")
    if not os.path.exists(path) and os.path.exists(os.path.join(opts.undo, "annulation.json")):
        path = os.path.join(opts.undo, "annulation.json")
    try:
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)["entries"]
    except (OSError, ValueError, KeyError) as e:
        raise SystemExit(f"[!] Cannot read {path}: {e}")

    mode = "undo" if opts.apply else "undo-simulation"
    run_dir = new_run_dir(mode)
    log = Log(os.path.join(run_dir, "_summary.txt"))
    log(LINE)
    log(f"  UNDO of {opts.undo}")
    log(LINE)
    log(f"  Mode: {'APPLY (logos are restored)' if opts.apply else 'DRY RUN (nothing is changed)'}")
    log(f"  {len(entries)} recorded change(s)")
    log(LINE)

    try:
        plex = PlexServer(PLEX_URL, PLEX_TOKEN, session=HTTP)
    except Exception as ex:
        log(f"  [!] {'Plex token rejected: ' + TOKEN_FIX if is_unauthorized(ex) else ex}")
        log.close()
        return
    done, skipped, errors = [], [], []
    for n, e in enumerate(reversed(entries), 1):
        log("")
        log(f"[{n}/{len(entries)}] {e['library']} > {e['title']}")
        try:
            item = plex.fetchItem(int(e["ratingKey"]))
            now = selected_key(item)
            # "after" is null when the change was interrupted: the current state is unknown,
            # so the previous state is restored anyway
            if e.get("after") is not None and now != e["after"]:
                log("  ==> [SKIPPED] the logo was changed since: left untouched")
                skipped.append(e["title"])
                continue
            if e["before"] is None:
                what = "remove the logo (there was none)"
                if opts.apply:
                    item.deleteLogo()
                    # Restore the lock state too (a field can be locked with no logo)
                    item.lockLogo() if e.get("before_locked") else item.unlockLogo()
            else:
                old = next((l for l in item.logos() if l.ratingKey == e["before"]), None)
                if old is None:
                    log("  ==> [SKIPPED] Plex no longer offers the old logo")
                    skipped.append(e["title"])
                    continue
                what = "restore the old logo"
                if opts.apply:
                    old.select()
                    if e["before_locked"]:
                        item.lockLogo()
                    else:
                        item.unlockLogo()
            log(f"  ==> [{'RESTORED' if opts.apply else 'TO RESTORE'}] {what}")
            done.append(e["title"])
            if opts.apply:
                time.sleep(DELAY_AFTER_CHANGE)
        except Exception as ex:
            log(f"  ==> [ERROR] {ex}")
            errors.append(f"{e['title']}: {ex}")

    log("")
    log(LINE)
    log(f"  {'Restored' if opts.apply else 'To restore'}: {len(done)} | skipped: {len(skipped)} | errors: {len(errors)}")
    for t in skipped:
        log(f"    - skipped: {t}")
    for t in errors:
        log(f"    - error: {t}")
    if not opts.apply:
        log(f"  Dry run only: run again with --undo {opts.undo} --apply to restore.")
    log(LINE)
    log.close()


def take_queue(path=None):
    """
    Returns the ratingKeys queued by tautulli-hook.sh and empties the queue.
    The file is renamed first, so keys added meanwhile go to a new queue file.
    """
    path = path or QUEUE_PATH
    taking = path + ".processing"
    try:
        os.replace(path, taking)
    except FileNotFoundError:
        return []
    try:
        with open(taking, encoding="utf-8") as f:
            keys = [k for line in f for k in re.split(r"[\s,]+", line) if k.isdigit()]
    finally:
        os.remove(taking)
    return list(dict.fromkeys(keys))  # without duplicates, in order


# ---------------------------------------------------------------------------
# Ignore list
# ---------------------------------------------------------------------------

def find_titles(plex, spec):
    """Plex titles matching "Library/Title", "Library > Title", "Title", "Title (year)" or a ratingKey."""
    spec = spec.strip()
    if spec.isdigit():
        return [plex.fetchItem(int(spec))]
    sections = [s for s in plex.library.sections() if s.type in ("movie", "show")]
    library, title = ignorelist.split_spec(spec)
    wanted = [s for s in sections if library is not None and s.title.casefold() == library.casefold()]
    if library is not None and not wanted:
        # No such library: the "/" belonged to the title (e.g. "Fate/Zero")
        library, title = None, spec
    if library is None:
        wanted = [s for s in sections if s.title in TARGET_LIBRARIES] or sections
    m = re.match(r"^(.*) \((\d{4})\)$", title)
    search = m.group(1) if m else title
    matches = []
    for section in wanted:
        for item in section.search(title=search):
            if ignorelist.title_matches(title, item.title, getattr(item, "year", None)):
                matches.append(item)
    return matches


def manage_ignore(opts):
    ignored = ignorelist.IgnoreList(IGNORE_PATH)
    changed = False
    if opts.ignore:
        plex = PlexServer(PLEX_URL, PLEX_TOKEN, session=HTTP)
        for spec in opts.ignore:
            matches = find_titles(plex, spec)
            if not matches:
                print(f'[!] "{spec}": no title found. Use "Library/Title", "Title (year)" or a ratingKey.')
            elif len(matches) > 1:
                print(f'[!] "{spec}" matches several titles, be more specific:')
                for item in matches:
                    year = f" ({item.year})" if getattr(item, "year", None) else ""
                    print(f"      {item.librarySectionTitle}/{item.title}{year}   (ratingKey {item.ratingKey})")
            else:
                item = matches[0]
                if ignored.add(item.ratingKey, item.librarySectionTitle, item.title, getattr(item, "year", None),
                               ignorelist.REASON_MANUAL):
                    changed = True
                    print(f"  + ignored: {ignored.label(item.ratingKey)}")
                else:
                    print(f"  = already ignored: {ignored.label(item.ratingKey)}")
    for spec in opts.unignore or []:
        keys = ignored.find(spec)
        if not keys:
            print(f'[!] "{spec}" is not on the ignore list (see --list-ignored).')
        elif len(keys) > 1:
            print(f'[!] "{spec}" matches several ignored titles, use "Library/Title" or the ratingKey:')
            for key in keys:
                print(f"      {ignored.label(key)}   (ratingKey {key})")
        else:
            label = ignored.label(keys[0])
            ignored.remove(keys[0])
            changed = True
            print(f"  - no longer ignored: {label}")
    if changed:
        ignored.save()
    if opts.list_ignored or changed:
        print(f"\nIgnore list ({len(ignored)} title(s), {IGNORE_PATH}):")
        for key, v in sorted(ignored.titles.items(), key=lambda kv: ignored.label(kv[0]).casefold()):
            print(f"  - {ignored.label(key)}   [{v['reason']}, {v['added']}, ratingKey {key}]")


if __name__ == "__main__":
    options = parse_args()
    if options.include_locked and not options.replace:
        raise SystemExit("[!] --include-locked requires --replace.")
    if options.ignore or options.unignore or options.list_ignored:
        manage_ignore(options)
    elif options.undo:
        with run_lock():
            undo(options)
    else:
        try:
            with run_lock():
                if options.process_queue:
                    queued = take_queue()
                    if not queued:
                        raise SystemExit(0)  # nothing queued: no run, no log, no ping
                    options.rating_keys = (options.rating_keys or []) + queued
                run(options)
        except Exception as crash:
            # Unexpected crash: tell the monitoring before showing the traceback
            ping_healthcheck(False, f"crash: {type(crash).__name__}: {crash}")
            raise
