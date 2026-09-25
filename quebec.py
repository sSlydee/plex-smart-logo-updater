"""
Quebec logo (and poster) detection by reading the image text (OCR).

Plex does not tell French (France) from French (Quebec) apart: for a fr-FR
library it may pick a Quebec logo ("Le financier" instead of "The Banker").
The logo text is read and compared with the French, Quebec and original titles.

The verdict is deliberately cautious: when in doubt, it answers UNKNOWN.
"""
import os

# On machines with many cores, OpenCV/onnxruntime spawn too many threads
for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_var, "2")

import difflib
import re
import unicodedata

import numpy as np
from PIL import Image, ImageOps

_ENGINE = None

QC, FR, FR_GUESS, ORIGINAL, UNKNOWN = "Quebec", "French", "French (inferred)", "original title", "uncertain"

# Preference between acceptable logos (higher is better)
PREFERENCE = {FR: 3, FR_GUESS: 2, ORIGINAL: 1}


def _engine():
    """Loads the OCR engine on first use only."""
    global _ENGINE
    if _ENGINE is None:
        import cv2
        cv2.setNumThreads(1)
        from rapidocr_onnxruntime import RapidOCR
        _ENGINE = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
    return _ENGINE


def _prepare(img, height=100):
    """Logo as black on white, cropped and scaled to a fixed height (reads better)."""
    img = img.convert("RGBA")
    alpha = np.array(img.getchannel("A"))
    gray = Image.fromarray(255 - alpha) if alpha.min() < 255 else ImageOps.grayscale(img)
    bbox = ImageOps.invert(gray).getbbox()
    if bbox:
        gray = gray.crop(bbox)
    gray = gray.resize((max(1, int(gray.width * height / max(1, gray.height))), height))
    gray = ImageOps.expand(gray, border=height // 2, fill=255)
    return np.array(gray.convert("RGB"))


# Version of the OCR reading: bump it when read_text() changes, so cached readings are redone
OCR_VERSION = 2


def reading_order(result):
    """
    Text boxes in reading order: line by line, then left to right. The OCR engine
    may return spaced-out letters out of order ("U R S E" for "RUSE") when their
    heights differ slightly.
    """
    boxes = []
    for points, text, _score in result:
        ys = [p[1] for p in points]
        xs = [p[0] for p in points]
        boxes.append({"text": text, "x": min(xs), "top": min(ys), "bottom": max(ys)})
    boxes.sort(key=lambda b: b["top"])
    lines = []
    for box in boxes:
        center = (box["top"] + box["bottom"]) / 2
        # Same line when the box's vertical center falls within the line's extent
        if lines and lines[-1]["top"] <= center <= lines[-1]["bottom"]:
            line = lines[-1]
            line["boxes"].append(box)
            line["bottom"] = max(line["bottom"], box["bottom"])
        else:
            lines.append({"top": box["top"], "bottom": box["bottom"], "boxes": [box]})
    return [b["text"] for line in lines for b in sorted(line["boxes"], key=lambda b: b["x"])]


# Posters are read in color at this size (longest side, in pixels): the title is
# large enough to be read, and the reading stays fast
POSTER_SIDE = 1024


def _prepare_poster(img, side=POSTER_SIDE):
    """Whole poster in color, scaled down: the logo preparation would shrink the title too much."""
    img = img.convert("RGB")
    img.thumbnail((side, side))
    return np.array(img)


def read_text(img, poster=False):
    """Text read on the logo (or poster), in reading order (empty string if nothing is read)."""
    result, _ = _engine()(_prepare_poster(img) if poster else _prepare(img))
    return " ".join(reading_order(result)) if result else ""


def normalize(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]+", " ", text).split()


def titles_differ(fr_title, ca_title):
    return bool(fr_title and ca_title) and normalize(fr_title) != normalize(ca_title)


def _best_ratio(word, text):
    if word in text:
        return 1.0
    best = 0.0
    for size in (len(word) - 1, len(word), len(word) + 1):
        for i in range(0, max(1, len(text) - size + 1)):
            best = max(best, difflib.SequenceMatcher(None, word, text[i:i + size]).ratio())
    return best


def _side_score(words, text, tokens):
    """
    Share of the words found on the logo (0..1), weighted by length.
    Words of 4+ letters are searched in the glued text (OCR often glues words
    together); 3-letter words only as whole words.
    """
    words = [w for w in words if len(w) >= 3 and not w.isdigit()]
    if not words:
        return None
    total = sum(len(w) for w in words)
    got = 0.0
    for w in words:
        if len(w) >= 4:
            r = _best_ratio(w, text)
        else:
            r = max((difflib.SequenceMatcher(None, w, t).ratio() for t in tokens), default=0.0)
        got += len(w) * r ** 4  # the power penalizes approximate matches
    return got / total


def _full_title_score(words, text):
    """Share of the full title found in the glued text (words of 3+ letters)."""
    words = [w for w in words if len(w) >= 3 and not w.isdigit()] or words
    if not words:
        return None
    total = sum(len(w) for w in words)
    return sum(len(w) * _best_ratio(w, text) ** 4 for w in words) / total


def verdict(ocr_text, fr_title, ca_title, original_title=None):
    """
    Returns (verdict, score_fr, score_qc) with verdict = QC, FR, FR_GUESS, ORIGINAL or UNKNOWN.

    - FR / QC: the words specific to one of the two titles are read on the logo.
    - FR_GUESS: the French title is read on the logo and the words specific to the
      Quebec title are missing (e.g. "PUSH" when Quebec says "Push : La division").
    - ORIGINAL: the logo shows the original (English) title, neither French nor
      Quebec (e.g. "BLACK BOX DIARIES" for "Journal intime d'un viol").
    - UNKNOWN: unreadable or ambiguous logo.

    Words shared by the Quebec and original titles do not count as Quebec words:
    when Quebec keeps the original title, the logo is not a Quebec logo.
    """
    fr, ca, en = normalize(fr_title), normalize(ca_title), normalize(original_title)
    tokens = normalize(ocr_text)
    text = "".join(tokens)
    if len(text) < 3:
        return UNKNOWN, None, None
    sf = _side_score([w for w in fr if w not in ca], text, tokens)
    sc = _side_score([w for w in ca if w not in fr and w not in en], text, tokens)
    # Required margin: 0.3; only 0.15 when the winner is read exactly
    # ("DETACHMENT" vs "Détachement", one letter apart)
    def wins(a, b):
        return a is not None and a >= 0.8 and a - (b or 0.0) >= (0.15 if a >= 0.999 else 0.3)
    if wins(sc, sf):
        return QC, sf, sc
    if wins(sf, sc):
        return FR, sf, sc
    no_quebec = sc is None or sc < 0.3
    full = _full_title_score(fr, text)
    if no_quebec and full is not None and full >= 0.8:
        return FR_GUESS, sf, sc
    if en and en != fr:
        full_en = _full_title_score(en, text)
        if no_quebec and full_en is not None and full_en >= 0.8:
            return ORIGINAL, sf, sc
    return UNKNOWN, sf, sc


# ---------------------------------------------------------------------------
# Picking a replacement logo: similarity with the full titles
# ---------------------------------------------------------------------------

def _window_ratio(title, text):
    """Best similarity between the title and a similar-length slice of the text read."""
    n = len(title)
    if not text or not n:
        return 0.0
    best = difflib.SequenceMatcher(None, title, text).ratio() if len(text) <= n else 0.0
    for size in range(max(1, n - 3), n + 4):
        for i in range(0, max(1, len(text) - size + 1)):
            best = max(best, difflib.SequenceMatcher(None, title, text[i:i + size]).ratio())
    return best


def title_similarity(title, ocr_text):
    """
    Similarity 0..1 between a full title and the text read. Extra text
    ("MARVEL STUDIOS"…) is ignored and word order may vary.
    """
    t, o = normalize(title), normalize(ocr_text)
    if not t or not o:
        return 0.0
    in_order = _window_ratio("".join(t), "".join(o))
    any_order = difflib.SequenceMatcher(None, "".join(sorted(t)), "".join(sorted(o))).ratio()
    return max(in_order, any_order)


def replacement_kind(ocr_text, fr_title, ca_title, original_title):
    """
    Classifies a replacement candidate by the full title it is closest to.
    Returns (kind, score) with kind = FR, ORIGINAL or None (Quebec, unreadable
    or too far from the titles).
    """
    if verdict(ocr_text, fr_title, ca_title, original_title)[0] == QC:
        return None, 0.0
    s_fr = title_similarity(fr_title, ocr_text)
    s_ca = title_similarity(ca_title, ocr_text)
    s_en = title_similarity(original_title, ocr_text) if original_title else 0.0
    if s_fr >= 0.8 and s_fr >= s_ca and s_fr >= s_en:
        return FR, s_fr
    if s_en >= 0.8 and s_en > s_ca:
        return ORIGINAL, s_en
    return None, max(s_fr, s_en)


# Studio credits tolerated on a logo (they do not count as extra text)
STUDIO_WORDS = {"marvel", "studios", "studio", "disney", "pixar", "dreamworks", "lucasfilm", "netflix",
                "dc", "presents", "presente", "original", "film", "movie", "the"}


def extra_text(ocr_text, title):
    """
    Number of letters read on top of the title (actor names, taglines…),
    not counting studio credits.
    """
    tokens = [t for t in normalize(ocr_text) if t not in STUDIO_WORDS]
    title_len = len("".join(t for t in normalize(title) if t not in STUDIO_WORDS))
    return max(0, len("".join(tokens)) - title_len)


def is_clean(ocr_text, title):
    """True when the logo shows little more than the title."""
    title_len = len("".join(normalize(title)))
    return extra_text(ocr_text, title) <= max(4, title_len // 4)
