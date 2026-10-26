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
}
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
    monkeypatch.setattr(main.quebec, "read_text", lambda img, poster=False: "SAW")
    cache = main.OcrCache(str(tmp_path / "cache.json"))
    cache.dark(None, "https://x/logo.png")
    cache.read(None, "https://x/logo.png")
    assert "dark" in cache.data["https://x/logo.png"] and cache.data["https://x/logo.png"]["text"] == "SAW"


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


def test_an_empty_setting_means_the_default(main, monkeypatch):
    """Regression: configure.py writes PLEX_PREFER_COLOR= for an older config, which turned the option off."""
    for value, default, expected in (("", True, True), ("  ", True, True), ("no", True, False),
                                     ("yes", False, True), ("", False, False)):
        monkeypatch.setenv("PLEX_TEST_FLAG", value)
        assert main.env_flag("PLEX_TEST_FLAG", default) is expected
    monkeypatch.delenv("PLEX_TEST_FLAG")
    assert main.env_flag("PLEX_TEST_FLAG", True) is True


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
