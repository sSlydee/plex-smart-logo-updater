"""
Quebec logo detection, checked on real cases (OCR text as actually read on the
logos, titles as provided by Plex). These tests need no Plex server and no OCR
engine: they only exercise the text logic in quebec.py.
"""
import pytest

import quebec as q

# (text read on the logo, French title, Quebec title, original title, expected verdict)
VERDICT_CASES = [
    # Quebec logos set by Plex in a French library
    ("UN JOUR SANS LENDEMAIN", "Edge of Tomorrow", "Un jour sans lendemain", "Edge of Tomorrow", q.QC),
    ("TRAIN A C GRANDE VITESSE", "Bullet Train", "Train à grande vitesse", "Bullet Train", q.QC),
    ("MAUVAIS CARCONS POUR LA VIE", "Bad Boys for Life", "Mauvais garçons pour la vie", "Bad Boys for Life", q.QC),
    ("DECADENCEX", "Saw X", "Décadence X", "Saw X", q.QC),
    ("STUDIOS DOCTEUR STRANGE", "Doctor Strange", "Docteur Strange", "Doctor Strange", q.QC),
    ("STUDIOS CAPITAINE MARVEL", "Captain Marvel", "Capitaine Marvel", "Captain Marvel", q.QC),
    ("LeVer De Lune", "Moonrise", "Lever de lune", "Moonrise", q.QC),
    ("LE FINANCIER", "The Banker", "Le financier", "The Banker", q.QC),
    # French logos (including when France keeps the original title)
    (":BANKER THE", "The Banker", "Le financier", "The Banker", q.FR),
    ("BULLET TRAIT", "Bullet Train", "Train à grande vitesse", "Bullet Train", q.FR),
    ("UNDERWORLD", "Underworld", "Monde infernal", "Underworld", q.FR),
    ("DETACHMENT", "Detachment", "Détachement", "Detachment", q.FR),
    ("OSS 117 ALERTEROUGE ENAFRIQUENOIRE", "OSS 117 : Alerte rouge en Afrique noire",
     "OSS 117 : Bons baisers d'Afrique", "OSS 117: From Africa with Love", q.FR),
    # Original title: neither French nor Quebec (Quebec keeps the original title)
    ("BLACK BOX DIARIES", "Journal intime d'un viol", "Black Box Diaries", "Black Box Diaries", q.ORIGINAL),
    ("HAPPY DEATHt DAY", "Happy Birthdead", "Bonne fête encore", "Happy Death Day", q.ORIGINAL),
    # French inferred: the Quebec title only adds words that are missing on the logo
    ("PUSH", "Push", "Push : La division", "Push", q.FR_GUESS),
    ("BUGONIA", "Bugonia", "La bugonia", "Bugonia", q.FR_GUESS),
    # Unreadable or ambiguous: the verdict stays cautious
    ("", "Gladiator II", "Gladiateur II", "Gladiator II", q.UNKNOWN),
    ("5", "Tron : Ares", "Tron 3", "TRON: Ares", q.UNKNOWN),
    ("SHAUN ETLES ZOMBIES", "Shaun of the Dead", "Shaun et les zombies", "Shaun of the Dead", q.UNKNOWN),
]


@pytest.mark.parametrize("ocr, fr, ca, en, expected", VERDICT_CASES,
                         ids=[f"{c[1]}<-{c[0] or 'empty'}" for c in VERDICT_CASES])
def test_verdict(ocr, fr, ca, en, expected):
    assert q.verdict(ocr, fr, ca, en)[0] == expected


CAPTAIN_AMERICA = ("Captain America : Le Soldat de l'hiver", "Capitaine America : Le soldat de l'hiver",
                   "Captain America: The Winter Soldier")
AVATAR = ("Avatar : De feu et de cendres", "Avatar : Feu et cendre", "Avatar: Fire and Ash")

REPLACEMENT_CASES = [
    # The French logo must win over the English one sharing the word "Captain"
    ("STUDIOS CAPTAIN AmERICA LESDLIDATDIELHIVER", CAPTAIN_AMERICA, q.FR),
    ("CAPTAINAMERICA THEWINTERSOLDIER 30", CAPTAIN_AMERICA, q.ORIGINAL),
    ("STUDIOS CAPITAINEAMERICA EAIHEICI.IVCOSETI", CAPTAIN_AMERICA, None),
    # "De feu et de cendres" (France) vs "Feu et cendre" (Quebec)
    ("AVATAR DE FEU ETDE CENDRES", AVATAR, q.FR),
    ("AVATAR FEUETCENDRE", AVATAR, None),
    ("AVATAR FIREAND ASH", AVATAR, q.ORIGINAL),
]


@pytest.mark.parametrize("ocr, titles, expected", REPLACEMENT_CASES, ids=[c[0] for c in REPLACEMENT_CASES])
def test_replacement_kind(ocr, titles, expected):
    assert q.replacement_kind(ocr, *titles)[0] == expected


def test_french_candidate_ranks_above_original():
    """A French logo must be preferred over the original-title logo."""
    assert q.PREFERENCE[q.FR] > q.PREFERENCE[q.FR_GUESS] > q.PREFERENCE[q.ORIGINAL]


@pytest.mark.parametrize("ocr, title, clean", [
    ("BULLET TRAIN", "Bullet Train", True),
    ("BRAD PITT BULLET TRAIN", "Bullet Train", False),
    ("LIVE DIE REPEAT TOM CRUISE EMILY BLUNT EDGE OF TOMORROW", "Edge of Tomorrow", False),
    ("MARVEL STUDIOS SPIDER-MAN FAR FROM HOME", "Spider-Man : Far From Home", True),  # studio credits tolerated
])
def test_is_clean(ocr, title, clean):
    assert q.is_clean(ocr, title) is clean


@pytest.mark.parametrize("fr, ca, differ", [
    ("The Banker", "Le financier", True),
    ("Frieren", "Frieren", False),
    ("Spider-Man : No Way Home", "Spider-Man: No Way Home", False),  # punctuation only
    ("Titre", None, False),
])
def test_titles_differ(fr, ca, differ):
    assert q.titles_differ(fr, ca) is differ


def test_normalize_strips_accents_and_punctuation():
    assert q.normalize("L'Été : Décadence!") == ["l", "ete", "decadence"]


def box(x, top, height, text):
    """A text box as returned by the OCR engine: 4 corner points, text, score."""
    return [[[x, top], [x + 10, top], [x + 10, top + height], [x, top + height]], text, 0.9]


def test_reading_order_fixes_spaced_letters():
    """Regression: "RUSE" with spaced letters was read "U R S E" and not detected as Quebec."""
    result = [box(30, 11, 40, "U"), box(10, 12, 40, "R"), box(50, 10, 41, "S"), box(70, 12, 40, "E")]
    assert q.reading_order(result) == ["R", "U", "S", "E"]
    assert q.verdict(" ".join(q.reading_order(result)), "Sharper", "Ruse", "Sharper")[0] == q.QC


def test_reading_order_keeps_lines():
    result = [box(10, 60, 30, "WINTER SOLDIER"), box(40, 10, 30, "FALCON"), box(10, 10, 30, "THE"),
              box(10, 35, 20, "AND THE")]
    assert q.reading_order(result) == ["THE", "FALCON", "AND THE", "WINTER SOLDIER"]
