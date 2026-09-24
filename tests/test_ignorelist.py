"""Ignore list: storage, lookup of titles to remove, title matching."""
import json

import pytest

import ignorelist as il


def make(tmp_path):
    ignored = il.IgnoreList(str(tmp_path / "ignored.json"))
    ignored.add(101, "Films", "Edge of Tomorrow", 2014, il.REASON_REJECTED)
    ignored.add(102, "Animations Japonaise", "Fate/Zero", 2011, il.REASON_MANUAL)
    ignored.add(103, "Films", "Dune", 2021, il.REASON_MANUAL)
    ignored.add(104, "Films", "Dune", 1984, il.REASON_MANUAL)
    return ignored


def test_add_save_reload(tmp_path):
    ignored = make(tmp_path)
    assert not ignored.add(101, "Films", "Edge of Tomorrow", 2014, il.REASON_MANUAL)  # already there
    ignored.save()
    reloaded = il.IgnoreList(str(tmp_path / "ignored.json"))
    assert len(reloaded) == 4 and 101 in reloaded and "101" in reloaded
    assert reloaded.get(101)["reason"] == il.REASON_REJECTED
    assert reloaded.label(101) == "Films > Edge of Tomorrow (2014)"
    assert json.loads((tmp_path / "ignored.json").read_text())["format"] == il.FORMAT


def test_missing_or_foreign_file_gives_an_empty_list(tmp_path):
    assert len(il.IgnoreList(str(tmp_path / "missing.json"))) == 0
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"format": "something-else", "titles": {"1": {}}}))
    assert len(il.IgnoreList(str(other))) == 0


@pytest.mark.parametrize("spec, keys", [
    ("101", ["101"]),
    ("Edge of Tomorrow", ["101"]),
    ("edge of tomorrow (2014)", ["101"]),
    ("Films/Edge of Tomorrow", ["101"]),
    ("Films > Edge of Tomorrow", ["101"]),
    ("Séries/Edge of Tomorrow", []),
    ("Fate/Zero", ["102"]),                          # no "Fate" library: the "/" is part of the title
    ("Animations Japonaise/Fate/Zero", ["102"]),
    ("Dune", ["103", "104"]),                         # ambiguous: two titles
    ("Dune (1984)", ["104"]),
    ("Unknown", []),
])
def test_find(tmp_path, spec, keys):
    assert sorted(make(tmp_path).find(spec)) == keys


def test_remove(tmp_path):
    ignored = make(tmp_path)
    assert ignored.remove(101) and 101 not in ignored
    assert not ignored.remove(101)


@pytest.mark.parametrize("spec, expected", [
    ("Films/Title", ("Films", "Title")),
    ("Films > Title", ("Films", "Title")),
    ("Title", (None, "Title")),
    ("Anime/Fate/Zero", ("Anime", "Fate/Zero")),
])
def test_split_spec(spec, expected):
    assert il.split_spec(spec) == expected
