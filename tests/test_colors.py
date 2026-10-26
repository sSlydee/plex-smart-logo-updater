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
