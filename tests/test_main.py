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
