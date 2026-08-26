"""Finding the right game's disks, and telling the map which game it is.

The map used to glob `POOL*.D64` wherever it looked, so the tab was Pool of
Radiance-only even with a Curse save open in the other tab. These pin the two
halves of the fix: which title a directory search settles on, and that the
title reaches the automapper rather than being re-defaulted on the way.

Nothing here touches a real disk image -- an empty file of the right *name* is
all a glob can see, and that is the whole of what is under test.
"""

from __future__ import annotations

import os

import pytest

from automap import paths
from goldbox import games

CURSE = games.CURSE_OF_THE_AZURE_BONDS
POOL = games.POOL_OF_RADIANCE


def disks(where, *names):
    """Empty files standing in for disk images."""
    where.mkdir(parents=True, exist_ok=True)
    for name in names:
        (where / name).write_bytes(b"")
    return where


@pytest.fixture(autouse=True)
def _no_disks_env(monkeypatch):
    """$POR_DISKS is the player's, and would answer every search here."""
    monkeypatch.delenv("POR_DISKS", raising=False)


# -- which directory, and which title -----------------------------------------

def test_pool_of_radiance_is_found_exactly_as_it_always_was(tmp_path,
                                                            monkeypatch):
    home = disks(tmp_path / "home" / "c64" / "Pool of Radiance Disks",
                 "POOL1.D64", "POOL2.D64").parent.parent
    monkeypatch.setattr(paths, "_home", lambda: home)
    monkeypatch.chdir(tmp_path)
    assert paths.find_disks() == home / "c64" / "Pool of Radiance Disks"


def test_a_title_asked_for_by_name_is_the_only_one_looked_for(tmp_path,
                                                              monkeypatch):
    disks(tmp_path / "Pool of Radiance Disks", "POOL1.D64")
    disks(tmp_path / "Curse of the Azure Bonds", "CURSE1.D64")
    monkeypatch.setattr(paths, "_home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    assert paths.find_disks(CURSE) == tmp_path / "Curse of the Azure Bonds"
    assert paths.find_disks(POOL) == tmp_path / "Pool of Radiance Disks"


def test_a_title_with_no_disks_is_not_answered_with_another_title(tmp_path,
                                                                  monkeypatch):
    """The confident wrong guess this change exists to prevent."""
    monkeypatch.setenv("POR_DISKS", str(disks(tmp_path, "POOL1.D64")))
    assert paths.find_disks(CURSE) is None
    assert paths.locate_disks(CURSE) is None


def test_locate_disks_says_which_title_it_settled_on(tmp_path, monkeypatch):
    monkeypatch.setenv("POR_DISKS", str(disks(tmp_path, "CURSE1.D64")))
    where, game = paths.locate_disks()
    assert (where, game) == (tmp_path, CURSE)


def test_por_disks_still_wins_and_now_works_for_any_title(tmp_path,
                                                          monkeypatch):
    monkeypatch.setenv("POR_DISKS", str(disks(tmp_path, "SILVER1.D64")))
    assert paths.find_disks() == tmp_path


def test_pool_of_radiance_wins_a_directory_holding_two_titles(tmp_path,
                                                              monkeypatch):
    """Not a guess about the party -- a fallback for when nothing says."""
    monkeypatch.setenv("POR_DISKS",
                       str(disks(tmp_path, "CURSE1.D64", "POOL1.D64")))
    assert paths.locate_disks()[1] is POOL
    assert paths.titles_in(tmp_path) == [POOL, CURSE]


def test_titles_in_an_empty_directory_is_empty(tmp_path):
    assert paths.titles_in(tmp_path) == []


def test_candidate_directories_carry_every_title_when_none_is_named(tmp_path,
                                                                    monkeypatch):
    monkeypatch.setattr(paths, "_home", lambda: tmp_path)
    named = {p.name for p in paths.disk_candidates()}
    assert "Pool of Radiance Disks" in named
    assert "Curse of the Azure Bonds" in named
    only = {p.name for p in paths.disk_candidates(CURSE)}
    assert "Pool of Radiance Disks" not in only


def test_disk_globs_cover_a_lower_cased_unpack():
    assert paths.disk_globs(POOL) == ("POOL*.[dD]64", "pool*.[dd]64")
    assert paths.disk_globs() == paths.disk_globs(POOL)


# -- the maps, and the title they came with -----------------------------------

def _no_geo_reading(monkeypatch, seen):
    from automap import __main__ as automain
    monkeypatch.setattr(automain, "load_geo_files",
                        lambda path: seen.append(path) or {})


def test_load_maps_reads_only_the_named_title_s_disks(tmp_path, monkeypatch):
    disks(tmp_path, "POOL1.D64", "CURSE1.D64")
    seen: list[str] = []
    _no_geo_reading(monkeypatch, seen)
    from automap.__main__ import load_maps_titled
    _, game = load_maps_titled(str(tmp_path), CURSE)
    assert [os.path.basename(p) for p in seen] == ["CURSE1.D64"]
    assert game is CURSE


def test_load_maps_without_a_title_takes_what_the_directory_holds(tmp_path,
                                                                  monkeypatch):
    disks(tmp_path, "SILVER1.D64")
    seen: list[str] = []
    _no_geo_reading(monkeypatch, seen)
    from automap.__main__ import load_maps_titled
    _, game = load_maps_titled(str(tmp_path))
    assert game is games.SECRET_OF_THE_SILVER_BLADES
    assert len(seen) == 1


def test_a_disk_matched_by_both_patterns_is_read_once(tmp_path, monkeypatch):
    """`disk_globs` returns an upper- and a lower-cased pattern.

    On a case-insensitive filesystem -- Windows, or a Mac -- both match the
    same file, and every image was being opened twice. Linux cannot reproduce
    that with real files, so the double match is staged directly.
    """
    disks(tmp_path, "POOL1.D64")
    seen: list[str] = []
    _no_geo_reading(monkeypatch, seen)
    from automap import __main__ as automain
    hit = str(tmp_path / "POOL1.D64")
    monkeypatch.setattr(automain.glob, "glob", lambda _pattern: [hit])
    automain.load_maps_titled(str(tmp_path))
    assert seen == [hit]


def test_load_maps_for_a_title_that_is_not_there_reads_nothing(tmp_path,
                                                               monkeypatch):
    disks(tmp_path, "POOL1.D64")
    seen: list[str] = []
    _no_geo_reading(monkeypatch, seen)
    from automap.__main__ import load_maps_titled
    maps, game = load_maps_titled(str(tmp_path), CURSE)
    assert (maps, game, seen) == ({}, CURSE, [])


def test_load_maps_of_nowhere_is_empty_and_nameless(tmp_path, monkeypatch):
    monkeypatch.setenv("POR_DISKS", str(tmp_path))
    from automap.__main__ import load_maps_titled
    assert load_maps_titled() == ({}, None)


# -- the save decides ---------------------------------------------------------

def test_game_of_a_disk_that_is_not_one_is_no_answer_at_all(tmp_path):
    from wish.__main__ import game_of
    assert game_of(None) is None
    assert game_of(str(tmp_path / "nothing.d64")) is None


def test_the_cli_looks_for_the_open_title_s_disks_beside_the_save(tmp_path,
                                                                  monkeypatch):
    disks(tmp_path, "POOL1.D64", "CURSE1.D64", "CURSE2.D64")
    import tools.wish as cli
    monkeypatch.delenv("POR_GAME_DISK", raising=False)
    save = str(tmp_path / "SAVE.D64")
    monkeypatch.setattr(cli, "game_of", lambda _s: CURSE)
    assert cli.find_game_disk(None, save).endswith("CURSE1.D64")
    monkeypatch.setattr(cli, "game_of", lambda _s: None)
    assert cli.find_game_disk(None, save).endswith("POOL1.D64")


# -- the title reaches the map ------------------------------------------------

def test_the_window_hands_the_title_to_the_automapper():
    from wish.window import WishWindow
    win = WishWindow(maps={}, title="Curse of the Azure Bonds")
    try:
        assert win.mapper.state.title == "Curse of the Azure Bonds"
        # The point of carrying it: GEO15 is Sokol Keep in one game only.
        assert win.mapper.state.title != games.DEFAULT.title
    finally:
        win.session.close()


def test_with_nothing_open_the_window_is_pool_of_radiance_as_before():
    from wish.window import WishWindow
    win = WishWindow(maps={})
    try:
        assert win.mapper.state.title == "Pool of Radiance"
    finally:
        win.session.close()


# -- P34: the backend preference ----------------------------------------------

class FakeBackend:
    def __init__(self, name):
        self.name = name
        self.default_interval_ms = 200
        self.closed = False

    def connect(self):
        return self

    def close(self):
        self.closed = True


def a_session(backend):
    from wish.session import Session
    s = Session(find=lambda pref=None: backend)
    s.attach()
    return s


def test_prefer_drops_a_different_backend_so_the_next_poll_reattaches():
    vice = FakeBackend("VICE")
    s = a_session(vice)
    assert s.target is vice
    s.prefer("Ultimate 64")
    assert s._preferred == "Ultimate 64"
    assert s.target is None and vice.closed


def test_prefer_keeps_the_backend_it_is_already_on():
    vice = FakeBackend("VICE")
    s = a_session(vice)
    s.prefer("vice")                     # the menu's spelling, not the class's
    assert s.target is vice and not vice.closed


def test_preferring_nothing_in_particular_disturbs_nothing():
    vice = FakeBackend("VICE")
    s = a_session(vice)
    s.prefer("")
    assert s._preferred is None
    assert s.target is vice and not vice.closed


def test_the_constructor_argument_still_sets_the_preference():
    from wish.session import Session
    seen = []
    s = Session(preferred="Ultimate 64", find=lambda pref=None: seen.append(pref))
    s.attach()
    assert seen == ["Ultimate 64"]
    s.prefer(None)
    s.attach()
    assert seen == ["Ultimate 64", None]


def test_the_map_says_where_the_party_is_not_which_file_it_came_from():
    """The regression Donald caught by eye: the label led with `GEO00`.

    Built the way the window builds it -- no save open, Pool of Radiance maps,
    nothing telling it the title -- because that is the path that lost it.
    """
    from gamedata import synthetic_geo

    from goldbox.geo import Geo
    from wish.window import WishWindow
    win = WishWindow(maps={"GEO00": Geo(synthetic_geo())})
    try:
        win.mapper.state.area = "GEO00"
        assert win.mapper.state.area_label == "New Phlan"
        win.mapper.state.area = "GEO14"
        assert win.mapper.state.area_label == "The Slums"
    finally:
        win.session.close()


def test_a_curse_party_still_gets_no_pool_of_radiance_place_name():
    from wish.window import WishWindow
    win = WishWindow(maps={}, title="Curse of the Azure Bonds")
    try:
        win.mapper.state.area = "GEO15"
        assert win.mapper.state.area_label == "GEO15"
    finally:
        win.session.close()
