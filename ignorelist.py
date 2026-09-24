"""
Ignore list (ignored.json): titles the script must leave alone, so they are
neither proposed again nor notified on every run.

A title gets there when its change is rejected in the review page (and applied
with --choices), or by hand with --ignore. Titles are keyed by their Plex
ratingKey, which does not change when a title is renamed.
"""
import json
import os
import time

FORMAT = "plex-smart-logo-updater/ignored-v1"
REASON_REJECTED = "rejected in the review page"
REASON_MANUAL = "added with --ignore"


class IgnoreList:
    def __init__(self, path):
        self.path = path
        self.titles = {}
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("format") == FORMAT:
                self.titles = data.get("titles", {})
        except (OSError, ValueError):
            pass

    def __contains__(self, rating_key):
        return str(rating_key) in self.titles

    def __len__(self):
        return len(self.titles)

    def label(self, rating_key):
        v = self.titles[str(rating_key)]
        year = f" ({v['year']})" if v.get("year") else ""
        return f"{v['library']} > {v['title']}{year}"

    def get(self, rating_key):
        return self.titles.get(str(rating_key))

    def add(self, rating_key, library, title, year, reason):
        """Adds a title; returns False if it was already there."""
        key = str(rating_key)
        if key in self.titles:
            return False
        self.titles[key] = {"library": library, "title": title, "year": year, "reason": reason,
                            "added": time.strftime("%Y-%m-%d %H:%M")}
        return True

    def remove(self, rating_key):
        return self.titles.pop(str(rating_key), None) is not None

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"format": FORMAT, "titles": self.titles}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def find(self, spec):
        """Keys of the listed titles matching a spec (ratingKey, "Title" or "Library/Title")."""
        spec = spec.strip()
        if spec in self.titles:
            return [spec]
        library, title = split_spec(spec)
        keys = [k for k, v in self.titles.items()
                if title_matches(title, v["title"], v.get("year"))
                and (library is None or v["library"].casefold() == library.casefold())]
        if not keys and library is not None:
            # The "/" may belong to the title (e.g. "Fate/Zero")
            keys = [k for k, v in self.titles.items() if title_matches(spec, v["title"], v.get("year"))]
        return keys


def split_spec(spec):
    """
    "Library/Title" or "Library > Title" -> (library, title); "Title" -> (None, title).
    Only the first separator counts, so titles like "Fate/Zero" keep working with a library
    ("Anime/Fate/Zero"); without a library, a title containing "/" must be given with " > "
    or as a ratingKey.
    """
    if " > " in spec:
        library, title = spec.split(" > ", 1)
        return library.strip(), title.strip()
    if "/" in spec:
        library, title = spec.split("/", 1)
        return library.strip(), title.strip()
    return None, spec.strip()


def title_matches(wanted, title, year):
    """Case-insensitive match on "Title" or "Title (year)"."""
    wanted = wanted.strip().casefold()
    title = (title or "").strip().casefold()
    return wanted == title or (year is not None and wanted == f"{title} ({year})")
