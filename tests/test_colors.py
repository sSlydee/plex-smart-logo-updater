"""
Colored logos (PLEX_PREFER_COLOR): OCR readings and colorfulness are faked, so no
Plex server and no OCR engine are needed.
"""
import argparse

import pytest

import quebec as q
from test_main import main  # noqa: F401  (fixture)

# key prefix -> (text read, colorfulness)
LOGOS = {
    "white": ("RETOUR VERS LE FUTUR", 0.0),
    "color": ("RETOUR VERS LE FUTUR", 0.8),
    "pale": ("RETOUR VERS LE FUTUR", 0.1),
    "english": ("BACK TO THE FUTURE", 0.9),
    "tagline": ("RETOUR VERS LE FUTUR MICHAEL J. FOX CHRISTOPHER LLOYD", 0.7),
    "blank": ("", 0.0),
    # A big Japanese title with a small English subtitle: the OCR engine only reads the subtitle
    "japanese": ("RETOUR VERS LE FUTUR", 0.8),
}
# Share of each logo covered by the text read (1.0 when not listed)
COVERS = {"japanese": 0.05, "drawing": 0.3}
TITLES = ("Retour vers le futur", "Back to the Future")


class FakeLogo:
    def __init__(self, key, selected=False, provider="tmdb"):
        self.ratingKey = self.key = key
        self.selected, self.provider = selected, provider


class Field:
    def __init__(self, name, locked):
        self.name, self.locked = name, locked


class FakeItem:
    guid = None  # no Plex match: no recommended logo, no Quebec titles
    originalTitle = "Back to the Future"

    def __init__(self, logos, locked=False):
        self._logos = logos
        self.fields = [Field("clearLogo", locked)]
        self.ratingKey, self.title, self.year = 7, "Retour vers le futur", 1985

    def logos(self):
        return self._logos


@pytest.fixture
def fake(main, monkeypatch):
    """Fake OCR and colors: each logo's key starts with a key of LOGOS; records the logos read by OCR."""
    read = []

    def info(image):
        return LOGOS[(image if isinstance(image, str) else image.key).split("#")[0]]

    def fake_read(plex, image, poster=False):
        read.append(image if isinstance(image, str) else image.key)
        return info(image)[0], (1000, 300)

    monkeypatch.setattr(main.OCR, "read", fake_read)
    monkeypatch.setattr(main.OCR, "color", lambda plex, image: info(image)[1])
    monkeypatch.setattr(main.OCR, "dark", lambda plex, image: 0.4 if "dark" in image.key else 0.0)
    monkeypatch.setattr(main.OCR, "coverage", lambda plex, image: COVERS.get(
        (image if isinstance(image, str) else image.key).split("#")[0], 1.0))
    monkeypatch.setattr(main, "PREFER_COLOR", True)
    return read


def alternative(main, logos, chosen, **kw):
    return main.colored_alternative(None, logos, chosen, TITLES, **kw)


def test_a_colored_logo_with_the_same_title_replaces_a_white_one(main, fake):
    logos = [FakeLogo("white#1"), FakeLogo("pale#2"), FakeLogo("color#3")]
    index, logo, text = alternative(main, logos, logos[0])
    assert (index, text) == (2, "RETOUR VERS LE FUTUR")


def test_a_colored_logo_is_left_alone(main, fake):
    logos = [FakeLogo("color#1"), FakeLogo("color#2")]
    assert alternative(main, logos, logos[0]) == (None,) * 3
    assert fake == []  # nothing read by OCR


def test_the_language_comes_before_the_color(main, fake):
    """Regression guard: a colored English logo never replaces a white French one."""
    logos = [FakeLogo("white#1"), FakeLogo("english#2")]
    assert alternative(main, logos, logos[0]) == (None,) * 3


def test_a_white_original_title_logo_takes_a_colored_original_one(main, fake):
    logos = [FakeLogo("english#0"), FakeLogo("color#1")]
    LOGOS["white_en"] = ("BACK TO THE FUTURE", 0.0)
    try:
        chosen = FakeLogo("white_en#2")
        assert alternative(main, logos + [chosen], chosen)[0] == 0
    finally:
        del LOGOS["white_en"]


def test_a_logo_with_dark_parts_is_left_out(main, fake):
    """Regression guard: an orange logo with black lettering was picked, unreadable on Plex's dark screens."""
    logos = [FakeLogo("white#1"), FakeLogo("color#2-dark")]
    assert alternative(main, logos, logos[0]) == (None,) * 3


def test_extra_text_is_refused_when_the_white_logo_has_none(main, fake):
    logos = [FakeLogo("white#1"), FakeLogo("tagline#2")]
    assert alternative(main, logos, logos[0]) == (None,) * 3


def test_an_unreadable_white_logo_is_kept(main, fake):
    logos = [FakeLogo("blank#1"), FakeLogo("color#2")]
    assert alternative(main, logos, logos[0]) == (None,) * 3


def test_quebec_logos_are_left_out(main, fake, monkeypatch):
    logos = [FakeLogo("white#1"), FakeLogo("color#2")]
    quebec_titles = ("Retour vers le futur", "Retour dans le futur", "Back to the Future")
    assert alternative(main, logos, logos[0], quebec_titles=quebec_titles)[0] == 1
    monkeypatch.setattr(main.quebec, "verdict", lambda text, *titles: (q.QC, 1.0))
    assert alternative(main, logos, logos[0], quebec_titles=quebec_titles) == (None,) * 3


def test_only_the_first_color_candidates_are_looked_at(main, fake, monkeypatch):
    monkeypatch.setattr(main, "COLOR_CANDIDATES", 2)
    logos = [FakeLogo("white#1"), FakeLogo("pale#2"), FakeLogo("color#3")]
    assert alternative(main, logos, logos[0]) == (None,) * 3


def opts(**kw):
    values = dict(apply=False, choices=None, replace=False, include_locked=False, fix_locked_quebec=False,
                  posters=False)
    values.update(kw)
    return argparse.Namespace(**values)


def test_a_white_logo_already_set_is_proposed_for_replacement(main, fake):
    logos = [FakeLogo("white#1", selected=True), FakeLogo("color#2")]
    plan = main.plan_item(None, FakeItem(logos), logos, lambda *a: None, opts(), ["fr-FR", "en-US"])
    assert (plan.category, plan.index, plan.mention) == ("replace", 1, "colored")


def test_option_off_keeps_the_white_logo(main, fake, monkeypatch):
    monkeypatch.setattr(main, "PREFER_COLOR", False)
    logos = [FakeLogo("white#1", selected=True), FakeLogo("color#2")]
    plan = main.plan_item(None, FakeItem(logos), logos, lambda *a: None, opts(), ["fr-FR", "en-US"])
    assert plan.category == "kept"


def test_a_locked_white_logo_is_left_untouched(main, fake):
    logos = [FakeLogo("white#1", selected=True), FakeLogo("color#2")]
    plan = main.plan_item(None, FakeItem(logos, locked=True), logos, lambda *a: None, opts(), ["fr-FR", "en-US"])
    assert plan.category == "locked"


def test_colors_of_unread_logos_are_cached(main, monkeypatch, tmp_path):
    """Regression guard: a logo's color was only kept once OCR had read it, so it was downloaded every run."""
    from PIL import Image
    fetched = []

    def fetch(plex, image):
        fetched.append(image)
        return Image.new("RGBA", (10, 10), (200, 30, 30, 255))

    monkeypatch.setattr(main, "fetch_image", fetch)
    cache = main.OcrCache(str(tmp_path / "cache.json"))
    assert cache.color(None, "https://x/logo.png") > 0.5
    assert cache.dark(None, "https://x/logo.png") == 0.0
    cache.save()
    again = main.OcrCache(str(tmp_path / "cache.json"))
    assert again.color(None, "https://x/logo.png") > 0.5
    assert again.dark(None, "https://x/logo.png") == 0.0
    assert len(fetched) == 2  # once per measure, then never again
    assert q.OCR_VERSION != again.data["https://x/logo.png"].get("v")  # the OCR reading is still to do


# --- plan_item paths with a recommended logo or a Quebec logo ----------------------

def plan_with(main, monkeypatch, logos, recommended=None, quebec_titles=None, same=False, found=None, **kw):
    """plan_item with Plex's recommendation and image comparisons faked."""
    monkeypatch.setattr(main, "recommended_logo", lambda item, lang: recommended)
    monkeypatch.setattr(main, "quebec_titles", lambda item, languages: quebec_titles)
    monkeypatch.setattr(main, "image_size", lambda plex, image: (1000, 300))
    monkeypatch.setattr(main, "fetch_image", lambda plex, image: None)
    monkeypatch.setattr(main, "same_image", lambda a, b: same)
    monkeypatch.setattr(main, "find_candidate", lambda plex, logos, url, size: found or (None, None, "none"))
    return main.plan_item(None, FakeItem(logos), logos, lambda *a: None, opts(**kw), ["fr-FR", "en-US"])


def test_a_white_current_logo_equal_to_the_recommended_one_gives_way(main, fake, monkeypatch):
    """The 'already the recommended logo' branch (with --replace) still prefers a colored logo."""
    logos = [FakeLogo("white#1", selected=True), FakeLogo("color#2")]
    plan = plan_with(main, monkeypatch, logos, recommended="white#url", same=True, replace=True)
    assert (plan.category, plan.index, plan.colored) == ("replace", 1, True)


def test_a_colored_current_logo_is_kept_when_the_recommended_one_is_white(main, fake, monkeypatch):
    logos = [FakeLogo("white#1"), FakeLogo("color#2", selected=True)]
    plan = plan_with(main, monkeypatch, logos, recommended="white#url", found=(0, logos[0], "same URL"),
                     replace=True)
    assert plan.category == "ok"
    assert (plan.colored, plan.mention) == (False, None)  # nothing changes: not counted as colored


def test_a_quebec_logo_is_replaced_with_a_colored_french_one(main, fake, monkeypatch):
    titles = ("Retour vers le futur", "Retour dans le futur", "Back to the Future")
    LOGOS["qc"] = ("RETOUR DANS LE FUTUR", 0.0)
    try:
        assert q.verdict(LOGOS["qc"][0], *titles)[0] == q.QC
        logos = [FakeLogo("qc#1", selected=True), FakeLogo("white#2"), FakeLogo("color#3")]
        plan = plan_with(main, monkeypatch, logos, quebec_titles=titles)
        assert (plan.category, plan.index, plan.current_is_qc, plan.colored) == ("replace", 2, True, True)
    finally:
        del LOGOS["qc"]


def test_titles_are_only_asked_when_a_colored_candidate_exists(main, fake, monkeypatch):
    """Regression: the two titles were asked to Plex's metadata service for every title with a logo."""
    asked = []
    monkeypatch.setattr(main, "library_titles", lambda *a: asked.append(1) or TITLES)
    logos = [FakeLogo("white#1", selected=True), FakeLogo("pale#2")]
    assert main.plan_item(None, FakeItem(logos), logos, lambda *a: None, opts(), ["fr-FR"]).category == "kept"
    logos = [FakeLogo("color#1", selected=True), FakeLogo("color#2")]
    assert main.plan_item(None, FakeItem(logos), logos, lambda *a: None, opts(), ["fr-FR"]).category == "kept"
    assert asked == []


def test_an_ocr_reading_keeps_the_measures_already_cached(main, monkeypatch, tmp_path):
    """Regression: reading a logo by OCR dropped its dark share, measured before."""
    from PIL import Image
    monkeypatch.setattr(main, "fetch_image", lambda plex, image: Image.new("RGBA", (10, 10), (200, 30, 30, 255)))
    monkeypatch.setattr(main.quebec, "read_logo", lambda img: ("SAW", 0.9))
    cache = main.OcrCache(str(tmp_path / "cache.json"))
    cache.dark(None, "https://x/logo.png")
    cache.read(None, "https://x/logo.png")
    assert "dark" in cache.data["https://x/logo.png"] and cache.data["https://x/logo.png"]["text"] == "SAW"


def test_a_colored_logo_mostly_unread_is_left_out(main, fake):
    """Regression: Code Geass got a colored logo with a big Japanese title: the OCR engine only read its
    small English subtitle, which matched the white logo's title."""
    logos = [FakeLogo("white#1"), FakeLogo("japanese#2"), FakeLogo("color#3")]
    assert alternative(main, logos, logos[0])[0] == 2  # the other colored logo is still picked
    assert alternative(main, logos[:2], logos[0]) == (None,) * 3


def test_a_low_text_share_is_fine_when_the_white_logo_has_one_too(main, fake):
    """A logo where the title is a small part of a drawing: compared with the white logo, not absolutely."""
    LOGOS["drawing"] = ("RETOUR VERS LE FUTUR", 0.0)
    try:
        logos = [FakeLogo("drawing#1"), FakeLogo("japanese#2"), FakeLogo("color#3")]
        COVERS["drawing"], COVERS["japanese"] = 0.08, 0.2  # 0.2 is not under half of 0.08: kept
        assert alternative(main, logos[:2], logos[0])[0] == 1
    finally:
        del LOGOS["drawing"]
        COVERS.update(drawing=0.3, japanese=0.05)


def test_read_logo_measures_the_share_covered_by_the_text(monkeypatch):
    """The text boxes the OCR engine returns, against the ink of the prepared logo."""
    from PIL import Image
    img = Image.new("RGBA", (300, 150), (0, 0, 0, 0))  # transparent, like logos
    img.paste((255, 255, 255, 255), (50, 25, 250, 125))  # a 200x100 opaque block: the ink

    class Engine:
        def __call__(self, arr):
            h, w = arr.shape[:2]  # the block scaled to 100 px high, with a 50 px border: 300x200
            middle = w // 2  # a box over the left half of the image: half of the block
            return [([[0, 0], [middle, 0], [middle, h], [0, h]], "BACK", 0.9)], None
    monkeypatch.setattr(q, "_engine", lambda: Engine())
    text, cover = q.read_logo(img)
    assert text == "BACK" and 0.45 < cover < 0.55
    monkeypatch.setattr(q, "_engine", lambda: (lambda arr: (None, None)))
    assert q.read_logo(img) == ("", 0.0)


def test_a_colored_logo_read_with_uncertainty_is_flagged(main, fake, monkeypatch):
    """Regression: on a title with a different Quebec title, a colored logo whose French reading is
    uncertain only carried "Colored", not the "French inferred" warning other OCR picks get."""
    titles = ("Retour vers le futur", "Retour dans le futur", "Back to the Future")
    monkeypatch.setattr(main.quebec, "verdict",
                        lambda text, *t: (q.QC, 1.0) if text.startswith("RETOUR DANS") else (q.FR_GUESS, 1.0))
    LOGOS["qc"] = ("RETOUR DANS LE FUTUR", 0.0)
    try:
        logos = [FakeLogo("qc#1", selected=True), FakeLogo("white#2"), FakeLogo("color#3")]
        plan = plan_with(main, monkeypatch, logos, quebec_titles=titles)
        assert (plan.index, plan.colored, plan.mention) == (2, True, "inferred")
    finally:
        del LOGOS["qc"]


def test_an_empty_setting_means_the_default(main, monkeypatch):
    """Regression: configure.py writes PLEX_PREFER_COLOR= for an older config, which turned the option off."""
    for value, default, expected in (("", True, True), ("  ", True, True), ("no", True, False),
                                     ("yes", False, True), ("", False, False)):
        monkeypatch.setenv("PLEX_TEST_FLAG", value)
        assert main.env_flag("PLEX_TEST_FLAG", default) is expected
    monkeypatch.delenv("PLEX_TEST_FLAG")
    assert main.env_flag("PLEX_TEST_FLAG", True) is True


def test_an_error_while_looking_for_a_colored_logo_never_logs_the_token(main, fake, monkeypatch):
    """Regression: a failed image download was logged as is, with its X-Plex-Token=… URL."""
    def fail(*a, **k):
        raise RuntimeError("404 Client Error for url: http://plex:32400/library/metadata/7/file?X-Plex-Token=SECRET123")
    monkeypatch.setattr(main, "colored_alternative", fail)
    lines = []
    logos = [FakeLogo("white#1", selected=True)]
    plan = main.plan_item(None, FakeItem(logos), logos, lines.append, opts(), ["fr-FR"])
    assert plan.category == "kept"
    logged = "\n".join(lines)
    assert "not checked" in logged and "SECRET123" not in logged and "<hidden>" in logged


def test_concurrent_runs_merge_their_cache_entries(main, monkeypatch, tmp_path):
    """Regression: a run that only measured a logo's colors overwrote the OCR reading another run saved."""
    path = str(tmp_path / "cache.json")
    waiting = main.OcrCache(path)  # loaded before the other run saved
    other = main.OcrCache(path)
    other.data["k"] = {"text": "SAW", "w": 10, "h": 5, "v": q.OCR_VERSION, "color": 0.8}
    other.changed.add("k")
    other.dirty = True
    other.save()
    waiting.data["k"] = {"dark": 0.0}
    waiting.changed.add("k")
    waiting.dirty = True
    waiting.save()
    saved = main.OcrCache(path).data["k"]
    assert saved["text"] == "SAW" and saved["dark"] == 0.0 and saved["color"] == 0.8


def test_the_review_page_knows_every_colored_logo(main, fake, monkeypatch):
    """Regression: the Colored filter and badge only looked at the mention, which can be another one."""
    import html_report
    plan = main.Plan()
    plan.category, plan.mention, plan.colored = "replace", "original", True
    card = html_report.card("Films", FakeItem([]), "Saw (2004)", plan, None, None, True, "Logo to replace",
                            "Original title")
    assert card["colored"] is True
    source = open(html_report.__file__, encoding="utf-8").read()
    assert '["colored", "Colored", c => c.colored]' in source


# --- locked logos set by the script ------------------------------------------------

def journal(main, tmp_path, folder, entries, name="undo.json"):
    path = tmp_path / "logs" / folder
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text(main.json.dumps({"entries": entries}))


def test_script_set_logos_reads_every_journal_oldest_first(main, tmp_path):
    journal(main, tmp_path, "2026-09-23_20h13m28_application", [{"ratingKey": 7, "after": "old"}], "annulation.json")
    journal(main, tmp_path, "2026-10-01_10h00m00_application", [{"ratingKey": 7, "after": "new"},
                                                                {"ratingKey": 8, "after": "p", "asset": "poster"},
                                                                {"ratingKey": 9, "after": None}])
    journal(main, tmp_path, "2026-10-02_10h00m00_simulation", [{"ratingKey": 9, "after": "x"}])
    (tmp_path / "logs" / "2026-10-03_10h00m00_application").mkdir()
    (tmp_path / "logs" / "2026-10-03_10h00m00_application" / "undo.json").write_text("not json")
    assert main.script_set_logos(str(tmp_path / "logs")) == {"7": "new"}


def test_a_locked_white_logo_set_by_the_script_gives_way(main, fake, monkeypatch):
    """The script locks the logos it sets: its own white logos would never get a colored version."""
    monkeypatch.setattr(main, "_SCRIPT_LOGOS", {"7": "white#1"})
    logos = [FakeLogo("white#1", selected=True), FakeLogo("color#2")]
    plan = main.plan_item(None, FakeItem(logos, locked=True), logos, lambda *a: None, opts(), ["fr-FR"])
    assert (plan.category, plan.index, plan.colored, plan.locked) == ("replace", 1, True, True)
    assert "(locked, set by this script)" in plan.detail


def test_a_locked_logo_picked_by_hand_is_never_touched(main, fake, monkeypatch):
    """Changed by hand after the script set another one: the journal no longer matches."""
    monkeypatch.setattr(main, "_SCRIPT_LOGOS", {"7": "white#9"})
    logos = [FakeLogo("white#1", selected=True), FakeLogo("color#2")]
    plan = main.plan_item(None, FakeItem(logos, locked=True), logos, lambda *a: None, opts(), ["fr-FR"])
    assert plan.category == "locked"
    monkeypatch.setattr(main, "_SCRIPT_LOGOS", {})  # no journal at all: every locked logo is protected
    assert main.plan_item(None, FakeItem(logos, locked=True), logos, lambda *a: None, opts(), ["fr-FR"]).category == "locked"


def test_a_locked_script_logo_stays_locked_without_the_option(main, fake, monkeypatch):
    monkeypatch.setattr(main, "_SCRIPT_LOGOS", {"7": "white#1"})
    monkeypatch.setattr(main, "PREFER_COLOR", False)
    logos = [FakeLogo("white#1", selected=True), FakeLogo("color#2")]
    assert main.plan_item(None, FakeItem(logos, locked=True), logos, lambda *a: None, opts(), ["fr-FR"]).category == "locked"


# --- third review --------------------------------------------------------------------

def test_a_colored_logo_with_the_original_title_is_flagged_original(main, fake, monkeypatch):
    """Regression: when Quebec keeps the original title, a colored logo showing it got "French inferred"."""
    titles = ("Journal intime d'un viol", "Black Box Diaries", "Black Box Diaries")
    LOGOS["bb_white"], LOGOS["bb_color"] = ("BLACK BOX DIARIES", 0.0), ("BLACK BOX DIARIES", 0.8)
    try:
        logos = [FakeLogo("bb_white#1", selected=True), FakeLogo("bb_color#2")]
        plan = plan_with(main, monkeypatch, logos, quebec_titles=titles)
        assert plan.colored and plan.mention == "original"
    finally:
        del LOGOS["bb_white"], LOGOS["bb_color"]


def test_journals_of_runs_started_in_the_same_second_are_read(main, tmp_path):
    journal(main, tmp_path, "2026-10-01_10h00m00_application", [{"ratingKey": 7, "after": "a"}])
    journal(main, tmp_path, "2026-10-01_10h00m00_application_2", [{"ratingKey": 7, "after": "b"}])
    journal(main, tmp_path, "2026-10-01_11h00m00_application", [{"ratingKey": 8, "after": "c"}])
    (tmp_path / "logs" / "2026-10-02_10h00m00_application").mkdir()
    (tmp_path / "logs" / "2026-10-02_10h00m00_application" / "undo.json").write_text('{"entries": null}')
    assert main.script_set_logos(str(tmp_path / "logs")) == {"7": "b", "8": "c"}


def test_a_failed_coverage_read_only_leaves_that_candidate_out(main, fake, monkeypatch):
    real = main.OCR.coverage

    def coverage(plex, image):
        if image.key.startswith("color#2"):
            raise OSError("download failed")
        return real(plex, image)
    monkeypatch.setattr(main.OCR, "coverage", coverage)
    logos = [FakeLogo("white#1"), FakeLogo("color#2"), FakeLogo("color#3")]
    assert alternative(main, logos, logos[0])[0] == 2


def test_an_unknown_coverage_never_leaves_a_logo_out(main, fake, monkeypatch):
    """Opaque logos: their background cannot be told from their letters (coverage None)."""
    COVERS["japanese"] = None
    try:
        logos = [FakeLogo("white#1"), FakeLogo("japanese#2")]
        assert alternative(main, logos, logos[0])[0] == 1
    finally:
        COVERS["japanese"] = 0.05


def test_read_logo_cannot_measure_an_opaque_logo(monkeypatch):
    from PIL import Image
    img = Image.new("RGBA", (200, 100), (0, 0, 0, 255))  # no transparency at all
    monkeypatch.setattr(q, "_engine", lambda: (lambda arr: ([([[0, 0], [10, 0], [10, 10], [0, 10]], "SAW", 0.9)], None)))
    assert q.read_logo(img) == ("SAW", None)


def test_coverage_reads_an_old_entry_again_and_keeps_its_measures(main, monkeypatch, tmp_path):
    """Readings cached before the coverage existed: the logo is read again, its colors are kept."""
    from PIL import Image
    monkeypatch.setattr(main, "fetch_image", lambda plex, image: Image.new("RGBA", (10, 10), (200, 30, 30, 255)))
    reads = []
    monkeypatch.setattr(main.quebec, "read_logo", lambda img: reads.append(1) or ("SAW", 0.7))
    cache = main.OcrCache(str(tmp_path / "cache.json"))
    cache.data["k"] = {"text": "SAW", "w": 10, "h": 10, "v": q.OCR_VERSION, "color": 0.9, "dark": 0.1}
    assert cache.coverage(None, "k") == 0.7 and cache.coverage(None, "k") == 0.7
    assert reads == [1] and cache.data["k"]["dark"] == 0.1 and cache.data["k"]["v"] == q.OCR_VERSION


def test_the_cache_survives_odd_values_on_disk(main, tmp_path):
    path = tmp_path / "cache.json"
    path.write_text('{"k": "not a dict"}')
    cache = main.OcrCache(str(path))
    cache.data["k"] = {"dark": 0.0}
    cache.changed.add("k")
    cache.dirty = True
    cache.save()
    assert main.OcrCache(str(path)).data["k"] == {"dark": 0.0}
