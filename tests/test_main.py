"""
Main script and setup wizard logic that needs no Plex server: token error
detection, log retention, choices files, undo journal, notification
de-duplication, config.env handling.
"""
import importlib.util
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def main(tmp_path_factory):
    """Imports plex-smart-logo-updater.py without touching the real config, cache or logs."""
    tmp = tmp_path_factory.mktemp("main")
    for key in list(os.environ):
        if key.startswith("PLEX_") or key in ("NOTIFY_URLS", "DISCORD_WEBHOOK"):
            del os.environ[key]
    os.environ["PLEX_CONFIG"] = str(tmp / "missing.env")
    os.environ["PLEX_OCR_CACHE"] = str(tmp / "ocr.json")
    os.environ["PLEX_LOGS_DIR"] = str(tmp / "logs")
    spec = importlib.util.spec_from_file_location("plex_smart_logo_updater",
                                                  os.path.join(ROOT, "plex-smart-logo-updater.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class FakeHTTPError(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.response = FakeResponse(status_code)


# --- token errors -----------------------------------------------------------

def test_real_401_is_a_token_error(main):
    assert main.is_unauthorized(FakeHTTPError("401 Client Error", 401))
    assert main.is_unauthorized(main.TokenError("rejected"))
    from plexapi.exceptions import Unauthorized
    assert main.is_unauthorized(Unauthorized("(401) unauthorized"))


def test_401_inside_an_unrelated_error_is_not_a_token_error(main):
    """Regression: a ratingKey or port containing 401 used to stop the whole run."""
    error = FakeHTTPError("500 Server Error for url: http://plex:32400/library/metadata/14012/clearLogos", 500)
    assert not main.is_unauthorized(error)
    assert not main.is_unauthorized(ValueError("port 32401 unreachable"))


# --- log retention ----------------------------------------------------------

def test_prune_logs_keeps_recent_dry_runs_and_every_apply_folder(main, tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    for day in range(1, 7):
        (logs / f"2026-01-0{day}_10h00m00s_simulation").mkdir(parents=True)
    apply_dir = logs / "2026-01-01_11h00m00s_application"
    apply_dir.mkdir()
    (apply_dir / "undo.json").write_text("{}")
    old_undo = logs / "2026-01-01_12h00m00s_simulation"  # older French name, kept too
    old_undo.mkdir()
    (old_undo / "annulation.json").write_text("{}")
    monkeypatch.setattr(main, "LOGS_DIR", str(logs))
    monkeypatch.setattr(main, "LOGS_KEEP", 2)

    main.prune_logs()

    remaining = sorted(p.name for p in logs.iterdir())
    assert remaining == ["2026-01-01_11h00m00s_application", "2026-01-01_12h00m00s_simulation",
                         "2026-01-05_10h00m00s_simulation", "2026-01-06_10h00m00s_simulation"]


def test_prune_logs_trims_cron_log(main, tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    cron_log = logs / "cron.log"
    cron_log.write_text("x" * 99 + "\n" * 1 + ("line\n" * 3000))
    monkeypatch.setattr(main, "LOGS_DIR", str(logs))
    monkeypatch.setattr(main, "CRON_LOG_MAX_BYTES", 1000)
    main.prune_logs()
    text = cron_log.read_text()
    assert len(text) <= 1000 and text.startswith("line") and text.endswith("line\n")


# --- choices file -----------------------------------------------------------

@pytest.mark.parametrize("fmt", ["plex-smart-logo-updater/choices-v1", "plex-logo-fr/choices-v1",
                                 "plex-logo-fr/choix-v1"])
def test_load_choices_accepts_current_and_older_formats(main, tmp_path, fmt):
    path = tmp_path / "choices.json"
    path.write_text(json.dumps({"format": fmt, "decisions": {"1": {"ok": True, "target": "x"}}}))
    assert main.load_choices(str(path)) == {"1": {"ok": True, "target": "x"}}


def test_load_choices_rejects_other_files(main, tmp_path):
    path = tmp_path / "other.json"
    path.write_text(json.dumps({"format": "something-else"}))
    with pytest.raises(SystemExit):
        main.load_choices(str(path))


# --- undo journal -----------------------------------------------------------

def test_undo_entry_is_written_before_the_change(main, tmp_path):
    """Regression: a change interrupted halfway must still be in undo.json."""
    path = tmp_path / "undo.json"
    journal = main.UndoJournal(str(path))
    entry = journal.add({"ratingKey": 1, "before": None, "before_locked": False, "after": None})
    saved = json.loads(path.read_text())
    assert saved["entries"] == [{"ratingKey": 1, "before": None, "before_locked": False, "after": None}]
    journal.complete(entry, "metadata://new")
    assert json.loads(path.read_text())["entries"][0]["after"] == "metadata://new"


# --- notifications ----------------------------------------------------------

def test_titles_to_handle_by_hand_are_only_reported_once(main, tmp_path):
    """Regression: persistent [CHECK] titles used to notify every week."""
    state = str(tmp_path / "state.json")
    assert main.new_manual_titles(["Films > A", "Films > B"], state) == ["Films > A", "Films > B"]
    assert main.new_manual_titles(["Films > A", "Films > B"], state) == []
    assert main.new_manual_titles(["Films > A", "Films > C"], state) == ["Films > C"]
    # B was fixed, then comes back: reported again
    assert main.new_manual_titles(["Films > A", "Films > B", "Films > C"], state) == ["Films > B"]


def test_targeted_run_does_not_forget_reported_titles(main, tmp_path):
    """Regression: a Tautulli run (one title) wiped the state, so the next weekly run reported everything again."""
    state = str(tmp_path / "state.json")
    assert main.new_manual_titles(["Films > Happy Birthdead"], state) == ["Films > Happy Birthdead"]
    assert main.new_manual_titles([], state, targeted=True) == []                    # Tautulli: One Piece, nothing
    assert main.new_manual_titles(["Films > X"], state, targeted=True) == ["Films > X"]
    assert main.new_manual_titles(["Films > Happy Birthdead", "Films > X"], state) == []  # next weekly run: quiet


def test_notification_names_the_titles(main):
    totals = main.empty_results()
    totals["add"] = ["Films > Real Steel (2011) (English)"]
    totals["poster_replace"] = ["Films > Bad Boys 2 (2003) (picked by OCR, replaces a Quebec poster)"]
    assert main.change_titles(totals, applied=False) == [
        "Films > Real Steel (2011): logo to add", "Films > Bad Boys 2 (2003): Quebec poster to replace"]
    totals["add"] = [f"Films > T{i} (English)" for i in range(7)]
    assert main.change_titles(totals, applied=True)[-1] == "… and 3 more"


def test_retries_skip_non_idempotent_methods(main):
    retry = main.HTTP.get_adapter("https://example.org").max_retries
    assert "POST" not in retry.allowed_methods
    assert "GET" in retry.allowed_methods


# --- config.env and setup wizard ---------------------------------------------

def test_envfile_parse(tmp_path):
    import envfile
    path = tmp_path / "config.env"
    path.write_text('# comment\nA=1\nB="two words"\nC=\'x\'\nD=it"s\n\nE=a=b\n')
    assert envfile.parse(str(path)) == {"A": "1", "B": "two words", "C": "x", "D": 'it"s', "E": "a=b"}
    assert envfile.parse(str(tmp_path / "missing.env")) == {}


@pytest.fixture()
def configure():
    sys.path.insert(0, ROOT)
    import configure as module
    return module


def test_write_config_keeps_keys_it_does_not_know(configure, tmp_path):
    """Regression: `configure.py --token` used to drop PLEX_LOGS_KEEP and other extra keys."""
    path = tmp_path / "config.env"
    path.write_text("PLEX_URL=http://x:32400\nPLEX_TOKEN=old\nPLEX_LIBRARIES=Movies\n"
                    "PLEX_LANGUAGES=fr-FR,en-US\nNOTIFY_URLS=\nPLEX_LOGS_KEEP=300\nDISCORD_WEBHOOK=https://d/x\n")
    values = configure.read_config(str(path))
    values["PLEX_TOKEN"] = "new"
    configure.write_config(str(path), values)
    saved = configure.read_config(str(path))
    assert saved["PLEX_TOKEN"] == "new"
    assert saved["PLEX_LOGS_KEEP"] == "300"
    assert saved["DISCORD_WEBHOOK"] == "https://d/x"
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"


@pytest.mark.parametrize("text, hour", [("6", 6), ("06", 6), ("6h", 6), ("6H", 6), ("06:00", 6), ("23", 23),
                                        ("24", None), ("six", None), ("", None), ("-1", None)])
def test_parse_hour(configure, text, hour):
    assert configure.parse_hour(text) == hour


# --- languages ---------------------------------------------------------------

@pytest.mark.parametrize("library_language, setting, expected", [
    ("fr-FR", "auto", ["fr-FR", "en-US"]),
    ("en-US", "auto", ["en-US"]),
    ("en", "auto", ["en"]),
    ("de-DE", "auto", ["de-DE", "en-US"]),
    ("xn", "auto", ["en-US"]),          # Plex's "no language"
    (None, "auto", ["en-US"]),
    ("en-US", "fr-FR,en-US", ["fr-FR", "en-US"]),   # a fixed list applies to every library
    ("de-DE", " de-DE , ja-JP ", ["de-DE", "ja-JP"]),
])
def test_languages_for(main, library_language, setting, expected):
    assert main.languages_for(library_language, setting) == expected


@pytest.mark.parametrize("languages, checked", [
    (["fr-FR", "en-US"], True),
    (["fr", "en-US"], True),
    (["fr-CA", "en-US"], False),   # a Quebec library keeps its Quebec logos
    (["en-US"], False),
    (["en-US", "fr-FR"], False),
    ([], False),
])
def test_quebec_detection_only_for_french_first(main, languages, checked):
    assert main.checks_quebec(languages) is checked


# --- ignore list in a run --------------------------------------------------------

class FakeItem:
    def __init__(self, rating_key, title, year=None):
        self.ratingKey, self.title, self.year = rating_key, title, year

    def logos(self):
        raise AssertionError("an ignored title must not be queried")


class FakeSection:
    title = "Films"

    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


def test_ignored_titles_are_skipped_without_querying_plex(main, tmp_path):
    import argparse
    import ignorelist
    ctx = main.Context()
    ctx.ignored = ignorelist.IgnoreList(str(tmp_path / "ignored.json"))
    ctx.ignored.add(7, "Films", "Edge of Tomorrow", 2014, ignorelist.REASON_REJECTED)
    lines = []
    opts = argparse.Namespace(apply=False, choices=None, replace=False, include_locked=False,
                              fix_locked_quebec=False)
    results = main.process_library(None, FakeSection([FakeItem(7, "Edge of Tomorrow", 2014)]),
                                   lines.append, opts, ctx, ["fr-FR", "en-US"])
    assert results["ignored"] == ["Edge of Tomorrow (2014)"]
    assert any("[IGNORED]" in line for line in lines)


# --- locked fields -----------------------------------------------------------------

@pytest.mark.parametrize("locked, has_logo, is_qc, replace, include_locked, fix_qc, kept", [
    (True, True, False, False, False, False, True),    # hand-picked logo: left alone
    (True, False, False, False, False, False, False),  # locked but empty: a logo is proposed
    (False, True, False, False, False, False, False),  # not locked: not protected by the lock
    (True, True, True, False, False, True, False),     # locked Quebec logo + --fix-locked-quebec
    (True, True, True, False, False, False, True),     # locked Quebec logo without the option
    (True, True, False, True, True, False, False),     # --replace --include-locked
])
def test_keeps_locked_logo(main, locked, has_logo, is_qc, replace, include_locked, fix_qc, kept):
    import argparse
    plan = main.Plan()
    plan.locked, plan.current, plan.current_is_qc = locked, (object() if has_logo else None), is_qc
    opts = argparse.Namespace(replace=replace, include_locked=include_locked, fix_locked_quebec=fix_qc)
    assert main.keeps_locked_logo(plan, opts) is kept


# --- Tautulli: targeted runs -------------------------------------------------------

class FakePlexItem:
    def __init__(self, key, type_, title="T", library="Séries TV", parent=None, grandparent=None):
        self.ratingKey, self.type, self.title, self.librarySectionTitle = key, type_, title, library
        self.parentRatingKey, self.grandparentRatingKey = parent, grandparent


class FakePlex:
    def __init__(self, items):
        self.items = {i.ratingKey: i for i in items}

    def fetchItem(self, key):
        if key not in self.items:
            raise KeyError(f"no item {key}")
        return self.items[key]


def test_select_titles_climbs_to_the_show_and_deduplicates(main, monkeypatch):
    monkeypatch.setattr(main, "TARGET_LIBRARIES", ["Séries TV", "Films"])
    plex = FakePlex([
        FakePlexItem(1, "show", "Show"),
        FakePlexItem(2, "season", parent=1),
        FakePlexItem(3, "episode", parent=2, grandparent=1),
        FakePlexItem(4, "episode", parent=2, grandparent=1),
        FakePlexItem(5, "movie", "Movie", library="Films"),
        FakePlexItem(6, "movie", "Home video", library="Autres vidéos"),   # not a configured library
        FakePlexItem(7, "track", "Song", library="Music"),
    ])
    lines = []
    selected = main.select_titles(plex, ["3", "4,2", "5 6", "7", "99"], lines.append)
    assert {lib: [i.ratingKey for i in items] for lib, items in selected.items()} == {"Séries TV": [1], "Films": [5]}
    assert any("99" in line for line in lines)            # unknown key reported
    assert any("Autres vidéos" in line for line in lines)  # outside PLEX_LIBRARIES reported


def test_pending_changes_are_notified_once_in_targeted_runs(main, tmp_path):
    state = str(tmp_path / "pending.json")
    # Tautulli: first episode of a new show -> notified; the next episodes -> quiet
    assert main.new_pending_changes({"1": "logo-a"}, state, targeted=True) == {"1": "logo-a"}
    assert main.new_pending_changes({"1": "logo-a"}, state, targeted=True) == {}
    # the planned logo changed -> notified again
    assert main.new_pending_changes({"1": "logo-b"}, state, targeted=True) == {"1": "logo-b"}
    # weekly full run: every pending change is a reminder
    assert main.new_pending_changes({"1": "logo-b", "2": "logo-c"}, state, targeted=False) == \
        {"1": "logo-b", "2": "logo-c"}


def test_new_run_dir_is_unique(main, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "LOGS_DIR", str(tmp_path))
    first, second = main.new_run_dir("simulation"), main.new_run_dir("simulation")
    assert first != second and second.startswith(first)


def test_prune_logs_handles_suffixed_folders(main, tmp_path, monkeypatch):
    for name in ["2026-01-01_10h00m00s_simulation", "2026-01-01_10h00m00s_simulation_2",
                 "2026-01-02_10h00m00s_simulation"]:
        (tmp_path / name).mkdir()
    monkeypatch.setattr(main, "LOGS_DIR", str(tmp_path))
    monkeypatch.setattr(main, "LOGS_KEEP", 1)
    main.prune_logs()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["2026-01-02_10h00m00s_simulation"]


# --- Tautulli queue ------------------------------------------------------------------

def test_take_queue_returns_unique_keys_and_empties_the_queue(main, tmp_path):
    queue = tmp_path / "queue.txt"
    queue.write_text("123\n456\n123\nnot-a-key\n789 101\n")
    assert main.take_queue(str(queue)) == ["123", "456", "789", "101"]
    assert not queue.exists()
    assert main.take_queue(str(queue)) == []   # empty queue: nothing to do


def test_cron_lines_are_told_apart(configure):
    run_line = "0 6 * * 1 cd x && python plex-smart-logo-updater.py --html " + configure.CRON_TAG
    old_run_line = "0 6 * * 1 cd x && python run.py # plex-smart-logo-updater (géré par configure.py)"
    queue_line = "*/5 * * * * cd x && python plex-smart-logo-updater.py --process-queue " + configure.QUEUE_TAG
    assert configure.is_run_line(run_line) and configure.is_run_line(old_run_line)
    assert not configure.is_run_line(queue_line)
    assert not configure.is_run_line("*/3 * * * * other-script.py")


# --- outcome of a run (exit code) ------------------------------------------------

def run_options(**kw):
    import argparse
    values = dict(apply=True, choices=None, html=False, rating_keys=None, notify=False, quiet=True,
                  replace=False, include_locked=False, fix_locked_quebec=False, posters=False)
    values.update(kw)
    return argparse.Namespace(**values)


def test_unreachable_plex_is_a_failed_run(main, monkeypatch):
    """Regression: a run stopped on a connection error exited with 0, so the review server showed it applied."""
    def refuse(*a, **k):
        raise ConnectionError("connection refused")
    monkeypatch.setattr(main, "PlexServer", refuse)
    monkeypatch.setattr(main, "HEALTHCHECK_URL", "")
    assert main.run(run_options()) == main.STOPPED != 0


def test_requeue_puts_titles_back(main, tmp_path):
    queue = str(tmp_path / "queue.txt")
    main.requeue(["12", "34"], queue)
    assert main.take_queue(queue) == ["12", "34"]


def test_a_lasting_failure_is_notified_once(main, tmp_path):
    """Regression: the Tautulli queue is retried every 5 minutes while Plex is down: one notification, not one per retry."""
    state = str(tmp_path / "failure.json")
    message = "Cannot connect to the Plex server: refused"
    assert main.failure_is_new(message, state) is True
    assert main.failure_is_new(message, state) is False
    main.clear_failure(state)  # a run went fine
    assert main.failure_is_new(message, state) is True


def test_errors_never_show_the_plex_token(main, monkeypatch):
    """Regression: a failed image download quoted its URL, with X-Plex-Token, in the logs and the monitoring."""
    monkeypatch.setattr(main, "PLEX_TOKEN", "SecretTok3n")
    error = ("404 Client Error: Not Found for url: http://127.0.0.1:32400/library/metadata/1/file"
             "?url=x&X-Plex-Token=SecretTok3n&size=2")
    shown = main.redact(error)
    assert "SecretTok3n" not in shown and "X-Plex-Token=<hidden>&size=2" in shown
    assert main.redact("token SecretTok3n in a message") == "token <hidden> in a message"


def test_library_errors_are_logged_without_the_token(main, monkeypatch, tmp_path):
    import argparse
    import ignorelist

    class Item:
        ratingKey, title, year = 5, "Real Steel", 2011

        def logos(self):
            return []

    def failing_plan(*args):
        raise RuntimeError("404 Client Error for url: http://h/file?X-Plex-Token=SecretTok3n")

    monkeypatch.setattr(main, "PLEX_TOKEN", "SecretTok3n")
    monkeypatch.setattr(main, "plan_item", failing_plan)
    ctx = main.Context()
    ctx.ignored = ignorelist.IgnoreList(str(tmp_path / "ignored.json"))
    lines = []
    opts = argparse.Namespace(apply=False, choices=None, replace=False, include_locked=False,
                              fix_locked_quebec=False, posters=False)
    results = main.process_library(None, FakeSection([Item()]), lines.append, opts, ctx, ["fr-FR", "en-US"])
    assert results["error"] and not any("SecretTok3n" in t for t in results["error"] + lines)


def test_applying_an_old_dry_run_keeps_its_folder(main, monkeypatch, tmp_path):
    """Regression: pruning at the start of an application could delete the folder of the choices being applied."""
    logs = tmp_path / "logs"
    old = logs / "2026-01-01_00h00m00_simulation"
    newer = logs / "2026-01-02_00h00m00_simulation"
    for folder in (old, newer):
        folder.mkdir(parents=True)
    monkeypatch.setattr(main, "LOGS_DIR", str(logs))
    monkeypatch.setattr(main, "LOGS_KEEP", 1)
    main.prune_logs(keep={str(old)})
    assert old.exists()
    main.prune_logs()
    assert not old.exists()


def test_a_rejected_token_is_not_logged(main, monkeypatch, tmp_path):
    """Regression: a 401 on an image stopped the run with the HTTPError text, token included, in the library log."""
    import argparse
    import ignorelist

    class Response:
        status_code = 401

    class Unauthorized(Exception):
        response = Response()

    class Item:
        ratingKey, title, year = 5, "Real Steel", 2011

        def logos(self):
            return []

    def failing_plan(*args):
        raise Unauthorized("401 Client Error for url: http://h/file?X-Plex-Token=SecretTok3n")

    monkeypatch.setattr(main, "PLEX_TOKEN", "SecretTok3n")
    monkeypatch.setattr(main, "plan_item", failing_plan)
    ctx = main.Context()
    ctx.ignored = ignorelist.IgnoreList(str(tmp_path / "ignored.json"))
    opts = argparse.Namespace(apply=False, choices=None, replace=False, include_locked=False,
                              fix_locked_quebec=False, posters=False)
    with pytest.raises(main.TokenError) as stopped:
        main.process_library(None, FakeSection([Item()]), lambda m: None, opts, ctx, ["fr-FR"])
    assert "SecretTok3n" not in str(stopped.value)


def test_ignore_list_changes_wait_for_running_runs(main, monkeypatch, tmp_path):
    """Regression: --unignore/--ignore rewrote ignored.json without the run lock, losing a run's rejections."""
    import argparse
    import contextlib
    import ignorelist
    path = tmp_path / "ignored.json"
    lst = ignorelist.IgnoreList(str(path))
    lst.add(7, "Films", "Edge of Tomorrow", 2014, ignorelist.REASON_MANUAL)
    lst.save()
    events = []

    @contextlib.contextmanager
    def lock():
        events.append("locked")
        yield

    monkeypatch.setattr(main, "IGNORE_PATH", str(path))
    monkeypatch.setattr(main, "run_lock", lock)
    main.manage_ignore(argparse.Namespace(ignore=None, unignore=["7"], list_ignored=False))
    assert events == ["locked"] and "7" not in ignorelist.IgnoreList(str(path))


def test_ocr_cache_save_keeps_other_runs_readings(main, tmp_path):
    """Regression: a run that waited behind another saved its stale copy of the cache, erasing that run's readings."""
    path = str(tmp_path / "ocr.json")
    waiting = main.OcrCache(path)          # loaded at start-up, then waits for the lock
    other = main.OcrCache(path)
    other.data["logo-A"] = {"text": "A"}
    other.changed.add("logo-A")
    other.dirty = True
    other.save()                           # the other run finishes first
    waiting.data["logo-B"] = {"text": "B"}
    waiting.changed.add("logo-B")
    waiting.dirty = True
    waiting.save()
    saved = json.loads(open(path).read())
    assert set(saved) == {"logo-A", "logo-B"}


def test_titles_plex_could_not_return_are_errors_and_requeued(main, monkeypatch, tmp_path):
    """Regression: a queued title whose fetch failed (503) was skipped silently: exit 0, lost from the queue."""
    class Plex:
        friendlyName, version = "Fake", "1"

        class library:
            @staticmethod
            def sections():
                return []

        def fetchItem(self, key):
            raise RuntimeError("503 Server Error")

    monkeypatch.setattr(main, "PlexServer", lambda *a, **k: Plex())
    monkeypatch.setattr(main, "HEALTHCHECK_URL", "")
    opts = run_options(apply=False, rating_keys=["555"])
    assert main.run(opts) == main.ERRORS
    assert opts.unprocessed == ["555"]


def test_requeue_gives_up_after_a_few_tries(main, tmp_path):
    queue = str(tmp_path / "queue.txt")
    for _ in range(main.MAX_REQUEUE):
        assert main.requeue(["9"], queue) == ["9"]
        main.take_queue(queue)
    assert main.requeue(["9"], queue) == []
    assert main.take_queue(queue) == []


class RecordingSender:
    def __init__(self, error):
        self.error, self.calls = error, 0

    def __call__(self, session, targets, title, body, markdown=None):
        self.calls += 1
        return [("discord", self.error)]


def test_a_failed_notification_is_sent_again(main, monkeypatch, tmp_path):
    """Regression: the 'already notified' state was saved before sending: one failed webhook call lost the alert."""
    import argparse
    monkeypatch.setattr(main, "LOGS_DIR", str(tmp_path))
    monkeypatch.setattr(main, "NOTIFY_TARGETS", [("discord", "https://d/x")])
    totals = main.empty_results()
    totals["check"] = ["Films > Happy Birthdead (2017)"]
    opts = argparse.Namespace(apply=False, rating_keys=None, choices=None)
    failing = RecordingSender("503 Service Unavailable")
    monkeypatch.setattr(main.notifier, "send", failing)
    main.notify(opts, str(tmp_path / "run"), totals, None, 1.0, {})
    working = RecordingSender(None)
    monkeypatch.setattr(main.notifier, "send", working)
    main.notify(opts, str(tmp_path / "run"), totals, None, 1.0, {})
    assert working.calls == 1  # reported again, since the first attempt failed
    main.notify(opts, str(tmp_path / "run"), totals, None, 1.0, {})
    assert working.calls == 1  # delivered: not repeated


def test_a_failed_failure_alert_is_sent_again(main, tmp_path):
    state = str(tmp_path / "failure.json")
    assert main.failure_is_new("down", state, save=False) is True
    assert main.failure_is_new("down", state) is True  # nothing was saved by the unsent attempt


def test_queue_is_where_the_tautulli_hook_writes_it(main):
    """Regression: with PLEX_LOGS_DIR set, the hook wrote logs/tautulli-queue.txt and --process-queue read elsewhere."""
    hook = open(os.path.join(ROOT, "tautulli-hook.sh"), encoding="utf-8").read()
    assert "logs/tautulli-queue.txt" in hook
    assert main.QUEUE_PATH == os.path.join(ROOT, "logs", "tautulli-queue.txt")


def test_undo_reports_failures_in_its_exit_code(main, monkeypatch, tmp_path):
    """Regression: --undo exited with 0 even when Plex was unreachable."""
    import argparse
    folder = tmp_path / "2026-01-01_00h00m00_application"
    folder.mkdir()
    (folder / "undo.json").write_text(json.dumps({"entries": []}))
    monkeypatch.setattr(main, "LOGS_DIR", str(tmp_path / "logs"))

    def refuse(*a, **k):
        raise ConnectionError("refused")
    monkeypatch.setattr(main, "PlexServer", refuse)
    assert main.undo(argparse.Namespace(undo=str(folder), apply=False)) == main.STOPPED


def test_prune_never_deletes_the_current_run(main, monkeypatch, tmp_path):
    """Regression: with PLEX_LOGS_KEEP=0 a run deleted its own new folder, then crashed writing its logs."""
    def refuse(*a, **k):
        raise ConnectionError("refused")
    monkeypatch.setattr(main, "LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(main, "LOGS_KEEP", 0)
    monkeypatch.setattr(main, "PlexServer", refuse)
    monkeypatch.setattr(main, "HEALTHCHECK_URL", "")
    assert main.run(run_options(apply=False)) == main.STOPPED
    [folder] = os.listdir(tmp_path / "logs")
    assert os.path.exists(tmp_path / "logs" / folder / "_summary.txt")


def test_timeouts_with_changing_texts_are_notified_once(main, monkeypatch, tmp_path):
    """Regression: a connect timeout quotes an object address that changes at every attempt, so each retry notified again."""
    import argparse
    sender = RecordingSender(None)
    monkeypatch.setattr(main.notifier, "send", sender)
    monkeypatch.setattr(main, "NOTIFY_TARGETS", [("discord", "https://d/x")])
    monkeypatch.setattr(main, "FAILURE_STATE", str(tmp_path / "failure.json"))
    monkeypatch.setattr(main, "HEALTHCHECK_URL", "")
    for address in ("0x7fa5d3963f40", "0x7f11aa22bb30", "0x7fee00ff1120"):
        summary = main.Log(str(tmp_path / "summary.txt"), echo=False)
        error = TimeoutError(f"ConnectTimeoutError(<HTTPConnection(host='10.0.0.1', port=32400) at {address}>)")
        main.stop(argparse.Namespace(notify=True), summary, error)
    assert sender.calls == 1


def test_retry_count_restarts_once_a_title_was_processed(main, tmp_path):
    """Regression: requeue counts were never reset, so a title that used its retries in one outage was dropped at
    its first failure in any later outage."""
    queue = str(tmp_path / "queue.txt")
    for _ in range(main.MAX_REQUEUE):
        main.requeue(["123"], queue)
        main.take_queue(queue)
    main.forget_retries(["123"], queue)  # processed fine later on
    assert main.requeue(["123"], queue) == ["123"]


def test_unignore_of_an_unknown_title_fails(main, monkeypatch, tmp_path):
    import argparse
    monkeypatch.setattr(main, "IGNORE_PATH", str(tmp_path / "ignored.json"))
    assert main.manage_ignore(argparse.Namespace(ignore=None, unignore=["Nope"], list_ignored=False)) is False


def test_application_reuses_the_dry_run_options(main, monkeypatch, tmp_path):
    """Regression: the Apply button ran without the dry run's --replace/--posters/--fix-locked-quebec, so approved
    changes were planned differently (kept, locked, posters skipped) and dropped, yet marked applied."""
    import runstate
    dry = tmp_path / "logs" / "2026-01-01_00h00m00_simulation"
    dry.mkdir(parents=True)
    runstate.write_run_info(str(dry), False, ["Films"], True, options={"replace": True, "posters": True})
    (dry / "choices.json").write_text(json.dumps({"format": "plex-smart-logo-updater/choices-v1", "decisions": {}}))

    def refuse(*a, **k):
        raise ConnectionError("refused")
    monkeypatch.setattr(main, "LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(main, "PlexServer", refuse)
    monkeypatch.setattr(main, "HEALTHCHECK_URL", "")
    monkeypatch.setattr(main, "CHECK_POSTERS", False)
    opts = run_options(choices=str(dry / "choices.json"))
    main.run(opts)
    assert opts.replace is True and opts.posters is True and opts.fix_locked_quebec is False
