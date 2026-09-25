"""
Quebec posters (--posters): OCR readings are faked, so no Plex server and no
OCR engine are needed. Texts are real readings of the posters of "The Banker".
"""
import argparse

import pytest

import ignorelist
import quebec as q
from test_main import main, FakeSection  # noqa: F401  (fixture and helper)

BANKER = ("The Banker", "Le financier", "The Banker")
READINGS = {
    "qc": "LE FINANCIER",
    "qc_credits": "'tv+ ANTHONY NICHOLAS NIA ANDSAMUEL L. MACKIE HOULT LONG JACKSON LE FINANCIER UN FILm",
    "fr": "THE BANKER",
    "fr_tagline": "THE BANKER INSPIREDBYTRUEEVENTS DON'TPAYTHEMAN. BETHEMAN.",
    "blank": "",
}


@pytest.mark.parametrize("key, expected", [
    ("qc", q.QC), ("qc_credits", q.QC), ("fr", q.FR), ("fr_tagline", q.FR), ("blank", q.UNKNOWN)])
def test_poster_verdicts(key, expected):
    assert q.verdict(READINGS[key], *BANKER)[0] == expected


class FakePoster:
    def __init__(self, key, selected=False, provider="tmdb"):
        self.ratingKey = self.key = key
        self.selected, self.provider = selected, provider


class Field:
    def __init__(self, name, locked):
        self.name, self.locked = name, locked


class FakeItem:
    guid = None  # no Plex match: no recommended poster

    def __init__(self, posters, locked=False, rating_key=7, title="The Banker", year=2020):
        self._posters = posters
        self.fields = [Field("thumb", locked)]
        self.ratingKey, self.title, self.year = rating_key, title, year

    def posters(self):
        return self._posters


@pytest.fixture
def ocr(main, monkeypatch):
    """Fake OCR: each poster's key is a key of READINGS; records the posters read."""
    read = []

    def fake_read(plex, image, poster=False):
        read.append(image.key)
        return READINGS[image.key.split("#")[0]], (1000, 1500)

    monkeypatch.setattr(main.OCR, "read", fake_read)
    return read


def opts(**kw):
    values = dict(apply=False, choices=None, replace=False, include_locked=False, fix_locked_quebec=False,
                  posters=True)
    values.update(kw)
    return argparse.Namespace(**values)


def test_best_poster_prefers_french_and_skips_quebec_and_unreadable(main, ocr):
    posters = [FakePoster("qc#1"), FakePoster("blank#2"), FakePoster("fr_tagline#3"), FakePoster("fr#4")]
    index, poster, text, kind, mention = main.best_french_poster(None, posters, BANKER)
    assert (index, kind, mention) == (2, q.FR, None)  # the first French one read exactly stops the search
    assert ocr == ["qc#1", "blank#2", "fr_tagline#3"]


def test_best_poster_reads_at_most_poster_candidates(main, ocr, monkeypatch):
    monkeypatch.setattr(main, "POSTER_CANDIDATES", 3)
    posters = [FakePoster(f"qc#{i}") for i in range(10)] + [FakePoster("fr#10")]
    assert main.best_french_poster(None, posters, BANKER)[1] is None
    assert len(ocr) == 3


def test_plan_poster_not_quebec_reports_nothing(main, ocr):
    item = FakeItem([FakePoster("fr#1", selected=True), FakePoster("qc#2")])
    assert main.plan_poster(None, item, lambda m: None, opts(), ["fr-FR"], BANKER) is None


def test_plan_poster_replaces_a_quebec_poster(main, ocr):
    item = FakeItem([FakePoster("qc#1", selected=True), FakePoster("qc_credits#2"), FakePoster("fr#3")])
    plan = main.plan_poster(None, item, lambda m: None, opts(), ["fr-FR"], BANKER)
    assert plan.category == "replace" and plan.asset is main.POSTER
    assert plan.candidate.key == "fr#3" and plan.target_id == "fr#3"
    assert "qc#1" not in ocr[1:]  # the current poster is not a candidate


def test_plan_poster_without_french_poster_is_manual(main, ocr):
    item = FakeItem([FakePoster("qc#1", selected=True), FakePoster("blank#2")])
    assert main.plan_poster(None, item, lambda m: None, opts(), ["fr-FR"], BANKER).category == "check"


@pytest.mark.parametrize("fix, category", [(False, "locked"), (True, "replace")])
def test_plan_poster_locked(main, ocr, fix, category):
    item = FakeItem([FakePoster("qc#1", selected=True), FakePoster("fr#2")], locked=True)
    plan = main.plan_poster(None, item, lambda m: None, opts(fix_locked_quebec=fix), ["fr-FR"], BANKER)
    assert plan.category == category


class RunItem(FakeItem):
    def logos(self):
        return []


@pytest.mark.parametrize("reason, key, logo_checked, poster_checked", [
    (ignorelist.REASON_REJECTED, "7", False, True),          # logo rejected in the review page: poster still checked
    (ignorelist.REASON_MANUAL, "7", False, False),           # title ignored by hand: nothing is checked
    (ignorelist.REASON_REJECTED, "7:poster", True, False),   # poster rejected: only the logo is checked
])
def test_ignore_list_and_posters(main, ocr, monkeypatch, tmp_path, reason, key, logo_checked, poster_checked):
    ctx = main.Context()
    ctx.ignored = ignorelist.IgnoreList(str(tmp_path / "ignored.json"))
    ctx.ignored.add(key, "Films", "The Banker", 2020, reason, asset="poster" if key.endswith("poster") else None)
    monkeypatch.setattr(main, "quebec_titles", lambda item, languages: BANKER)
    logo_plans = []

    def fake_plan_item(*args):
        plan = main.Plan()
        plan.category, plan.titles = "kept", BANKER
        logo_plans.append(plan)
        return plan

    monkeypatch.setattr(main, "plan_item", fake_plan_item)
    item = RunItem([FakePoster("qc#1", selected=True), FakePoster("fr#2")])
    results = main.process_library(None, FakeSection([item]), lambda m: None, opts(), ctx, ["fr-FR", "en-US"])
    assert not results["error"]
    assert bool(logo_plans) is logo_checked
    assert bool(results["ignored"]) is (key == "7")
    assert bool(results["poster_replace"]) is poster_checked
    assert ctx.pending == ({"7:poster": "fr#2"} if poster_checked else {})


def test_ignore_list_label_for_posters(tmp_path):
    ignored = ignorelist.IgnoreList(str(tmp_path / "ignored.json"))
    ignored.add("7:poster", "Films", "The Banker", 2020, ignorelist.REASON_REJECTED, asset="poster")
    assert ignored.label("7:poster") == "Films > The Banker (2020) [poster]"
    assert ignored.find("The Banker") == ["7:poster"]
    assert "7" not in ignored
