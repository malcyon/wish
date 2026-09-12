from __future__ import annotations

"""`#357 (The automapper reads the shared Game disks folder, so setting a
title's own folder does not make it map that title)`.

You set your Curse of the Azure Bonds disks in the field named after that
game. You start Wish with no save open and play Curse. The automapper maps
nothing, for the whole session, and nothing on screen connects the two: the
shared "Folder" field still held the Pool of Radiance disks, and with no
save open that shared folder is what named the window's title before Curse's
own row was ever consulted.

Four things this file pins, one per architect-plan step:

* the shared `disks` setting folds into `game_folders` on every load, for
  every title the folder holds, and blanks itself only once something was
  actually found (step 1);
* `paths.resolve_disks` answers from `game_folders` alone -- the shared
  folder is not a rung in the precedence any more (step 2);
* the Game disks tab carries one row per title and no shared one (step 3);
* with no save open, the machine names which configured title is actually
  running and the window switches to its folder instead of refusing (step 4).
"""

import pathlib

import pytest
from gamedata import _disk_with, synthetic_geo

from automap import c64, paths
from automap.area import RESIDENT_GEO
from automap.config import Settings
from automap.target import MemoryTarget
from automap.window import WRONG_GAME
from goldbox import c64_port
from goldbox.geo import (
    ATTRIBUTES,
    BARRIERS,
    GRID,
    SOLID,
    WALLS_NORTH_EAST,
    WALLS_SOUTH_WEST,
    Geo,
)

POOL = c64_port.POOL_OF_RADIANCE
CURSE = c64_port.CURSE_OF_THE_AZURE_BONDS
SILVER = c64_port.SECRET_OF_THE_SILVER_BLADES


def disks(where, *names):
    """Empty files standing in for disk images -- a glob sees only the name."""
    where.mkdir(parents=True, exist_ok=True)
    for name in names:
        (where / name).write_bytes(b"")
    return where


@pytest.fixture(autouse=True)
def _no_disks_env(monkeypatch):
    monkeypatch.delenv("POR_DISKS", raising=False)


def nowhere(tmp_path, monkeypatch):
    """A machine with no disks anywhere the search looks."""
    empty = tmp_path / "empty-home"
    empty.mkdir(exist_ok=True)
    monkeypatch.setattr(paths, "_home", lambda: empty)
    monkeypatch.chdir(empty)


def config_here(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


# --- step 1: folding the shared folder into game_folders, on every load ------

def test_a_file_with_both_keys_folds_the_shared_folder_into_the_title_it_holds(
        tmp_path, monkeypatch):
    """Donald's own file: a shared folder that still holds his Pool of
    Radiance disks, and a Curse row he has already set. The old migration
    only ran when `game_folders` was `None`, so a file carrying both keys was
    skipped and his Pool of Radiance folder was never reachable by title."""
    nowhere(tmp_path, monkeypatch)
    config_here(tmp_path, monkeypatch)
    shelf = disks(tmp_path / "shared", "POOL1.D64")
    own = disks(tmp_path / "curse-own", "CURSE1.D64")
    Settings(disks=str(shelf), game_folders={CURSE.key: str(own)}).save()

    again = Settings.load()
    assert again.game_folders == {CURSE.key: str(own), POOL.key: str(shelf)}
    assert again.disks == ""


def test_a_shared_folder_holding_two_titles_fills_both_rows(tmp_path,
                                                              monkeypatch):
    nowhere(tmp_path, monkeypatch)
    config_here(tmp_path, monkeypatch)
    shelf = disks(tmp_path / "shared", "POOL1.D64", "CURSE1.D64")
    Settings(disks=str(shelf)).save()

    again = Settings.load()
    assert again.game_folders == {POOL.key: str(shelf), CURSE.key: str(shelf)}
    assert again.disks == ""


def test_a_row_the_player_set_is_not_overwritten_by_the_shared_folder(
        tmp_path, monkeypatch):
    nowhere(tmp_path, monkeypatch)
    config_here(tmp_path, monkeypatch)
    shelf = disks(tmp_path / "shared", "CURSE1.D64")
    own = disks(tmp_path / "curse-own", "CURSE1.D64")
    Settings(disks=str(shelf), game_folders={CURSE.key: str(own)}).save()

    again = Settings.load()
    assert again.game_folders == {CURSE.key: str(own)}
    assert again.disks == ""


def test_a_shared_folder_recognising_nothing_is_kept_until_it_can_be_read(
        tmp_path, monkeypatch):
    """A folder that is gone, empty, or on a drive not plugged in today has
    no title to key it under, so `disks` is kept rather than dropped -- the
    next load that can read it tries again."""
    nowhere(tmp_path, monkeypatch)
    config_here(tmp_path, monkeypatch)
    empty = tmp_path / "nothing-here"
    empty.mkdir()
    Settings(disks=str(empty)).save()

    again = Settings.load()
    assert again.game_folders == {}
    assert again.disks == str(empty)


# --- step 2: resolve_disks answers from game_folders alone -------------------

def test_with_no_game_named_the_first_configured_title_answers(tmp_path,
                                                                 monkeypatch):
    nowhere(tmp_path, monkeypatch)
    a = disks(tmp_path / "pool", "POOL1.D64")
    b = disks(tmp_path / "curse", "CURSE1.D64")
    settings = Settings(game_folders={POOL.key: str(a), CURSE.key: str(b)})
    assert paths.resolve_disks(settings=settings) == (a, paths.GAME_PREFERENCE)

    settings = Settings(game_folders={CURSE.key: str(b)})
    assert paths.resolve_disks(settings=settings) == (b, paths.GAME_PREFERENCE)


def test_a_configured_row_beats_por_disks_with_no_game_named(tmp_path,
                                                               monkeypatch):
    nowhere(tmp_path, monkeypatch)
    env = disks(tmp_path / "env", "CURSE1.D64")
    monkeypatch.setenv("POR_DISKS", str(env))
    b = disks(tmp_path / "curse", "CURSE1.D64")
    settings = Settings(game_folders={CURSE.key: str(b)})
    assert paths.resolve_disks(settings=settings) == (b, paths.GAME_PREFERENCE)


def test_the_shared_field_is_read_by_nothing(tmp_path, monkeypatch):
    nowhere(tmp_path, monkeypatch)
    shelf = disks(tmp_path / "shelf", "POOL1.D64")
    settings = Settings(disks=str(shelf))
    assert paths.resolve_disks(settings=settings) == (None, paths.NOWHERE)


def test_a_title_with_no_row_is_not_answered_with_another_titles(tmp_path,
                                                                   monkeypatch):
    """The guard the per-title design rests on: a title with nothing set for
    it must never silently be handed somebody else's folder."""
    nowhere(tmp_path, monkeypatch)
    b = disks(tmp_path / "curse", "CURSE1.D64")
    settings = Settings(game_folders={CURSE.key: str(b)})
    assert paths.resolve_disks(settings=settings, game=POOL) == (
        None, paths.NOWHERE)


# --- step 3: the shared Folder row is gone from the dialog --------------------

@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def window(app, save=None, maps={}, **kw):
    """A window with no emulator, no maps unless given, and nothing modal.

    `maps=None` means "load them from disk", the way the real window does --
    the step 4 tests below want that; every other caller here wants the
    ordinary empty default, matching `tests/test_preferences.py`'s helper of
    the same name.
    """
    from wish.session import Session
    from wish.window import WishWindow
    win = WishWindow(save, maps=maps, session=Session(find=lambda pref=None: None),
                     **kw)
    win.announce = lambda title, text: None
    return win


def test_the_game_disks_tab_has_one_row_per_supported_title_and_no_shared_row(
        app, tmp_path, monkeypatch):
    from wish.preferences import GAME_FOLDER_TITLES, PreferencesDialog

    nowhere(tmp_path, monkeypatch)
    win = window(app)
    try:
        dialog = PreferencesDialog(win)
        assert set(dialog.game_folder_edits) == {g.key for g in GAME_FOLDER_TITLES}
        assert not hasattr(dialog, "folder")
        assert not hasattr(dialog, "browse")
        assert not hasattr(dialog, "set_folder")
    finally:
        win.close()


# --- step 4: the machine names the title, among configured titles ------------

def walled_geo(art: int = 1, rooms: int = 4) -> Geo:
    """A generated map whose walls are drawn from both sides, as real ones
    are. Copied from `tests/test_wronggame.py`, which explains why: a map
    that reads like the ones the game ships, rather than
    `gamedata.synthetic_geo`'s deliberately one-sided art."""
    planes = bytearray(synthetic_geo())
    for y in range(GRID):
        for x in range(GRID):
            at = y * GRID + x
            if x % rooms == 0 and x:
                planes[WALLS_SOUTH_WEST + at] |= art
                planes[WALLS_NORTH_EAST + at - 1] |= art
                planes[BARRIERS + at] |= SOLID << 6
            if y % rooms == 0 and y:
                planes[WALLS_NORTH_EAST + at] |= art << 4
                planes[WALLS_SOUTH_WEST + at - GRID] |= art << 4
    return Geo(bytes(planes))


def a_few_bytes_different(geo: Geo, how_many: int) -> Geo:
    """The same map, drifted -- see `tests/test_wronggame.py`."""
    raw = bytearray(geo.to_bytes())
    for i in range(how_many):
        raw[ATTRIBUTES + i] ^= 0x1F
    return Geo(bytes(raw))


def machine(resident: Geo, position=(4, 5, 0)) -> MemoryTarget:
    """A C64 with a block at `$0400` and no status line -- see
    `tests/test_wronggame.py`."""
    blocks = {0xD011: bytes([0x1B]), 0xD018: bytes([0x15]), 0xDD00: bytes([0x17]),
              c64.DEFAULT.live_position: bytes(position),
              RESIDENT_GEO: resident.to_bytes()}
    return MemoryTarget(blocks)


def ticked(binding, times: int = 24):
    for _ in range(times):
        binding.tick()
    return binding


def _disk_with_geo(path: pathlib.Path, name: bytes, geo: Geo) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_disk_with([(name, geo.to_bytes())]))


def _configured(tmp_path, pool_geo: Geo | None, curse_geo: Geo | None):
    """A `game_folders` setting with real, readable GEO00 disks behind it."""
    folders = {}
    if pool_geo is not None:
        por = tmp_path / "por"
        _disk_with_geo(por / "POOL1.D64", b"GEO00", pool_geo)
        folders[POOL.key] = str(por)
    if curse_geo is not None:
        curse = tmp_path / "curse"
        _disk_with_geo(curse / "CURSE1.D64", b"GEO00", curse_geo)
        folders[CURSE.key] = str(curse)
    return Settings(game_folders=folders), folders


def test_the_acceptance_case_from_the_issue(app, tmp_path, monkeypatch):
    """The ticket's own Testing paragraph: Curse's own row is set, the
    shared setting no longer exists to get in the way, and the machine is
    running Curse with no save open. The map finds the Curse disks, without
    ever having been told to look there."""
    from automap.area import OURS
    nowhere(tmp_path, monkeypatch)
    pool_geo = walled_geo(art=1)
    curse_geo = walled_geo(art=5, rooms=3)
    settings, folders = _configured(tmp_path, pool_geo, curse_geo)

    win = window(app, maps=None, settings=settings)
    try:
        assert win.map.state.title == POOL.title    # the first configured row
        win.mapper.target = machine(curse_geo)
        ticked(win.map)

        assert win.map.state.title == CURSE.title
        assert str(win.disks) == folders[CURSE.key]
        assert win.disks_source == paths.GAME_PREFERENCE
        assert WRONG_GAME not in [line.split("  ", 1)[-1]
                                  for line in win.map.messages.lines()]
        ticked(win.map)
        assert win.mapper.title_check is OURS
    finally:
        win.close()


def test_the_switch_says_which_title_it_is_now_mapping(app, tmp_path,
                                                       monkeypatch):
    """The one sentence a player reads when the machine names the title.

    Donald approved the wording on 2026-09-07, choosing it over two longer
    ones that named the disks or the folder: `"Now mapping <title>."`  It is
    the only evidence on screen that the automapper changed what it is
    following, so a switch that happens silently is the bug this ticket was
    filed about wearing different clothes (`#357 (The automapper reads the
    shared Game disks folder, so setting a title's own folder does not make
    it map that title)`).
    """
    from wish.window import SWITCHED_TITLE
    nowhere(tmp_path, monkeypatch)
    pool_geo = walled_geo(art=1)
    curse_geo = walled_geo(art=5, rooms=3)
    settings, _ = _configured(tmp_path, pool_geo, curse_geo)

    win = window(app, maps=None, settings=settings)
    try:
        win.mapper.target = machine(curse_geo)
        ticked(win.map)
        said = [line.split("  ", 1)[-1] for line in win.map.messages.lines()]
        assert SWITCHED_TITLE.format(title=CURSE.title) in said
        assert f"Now mapping {CURSE.title}." in said
        # Nothing a player reads may carry a marker, an address or a path.
        for line in said:
            assert "(NOT APPROVED)" not in line
    finally:
        win.close()


def test_a_title_with_no_row_still_gets_the_refusal(app, tmp_path, monkeypatch):
    """The fail-closed guard the per-title design rests on: a machine
    running an unconfigured title still gets no candidate to switch to."""
    nowhere(tmp_path, monkeypatch)
    pool_geo = walled_geo(art=1)
    curse_geo = walled_geo(art=5, rooms=3)
    settings, _folders = _configured(tmp_path, pool_geo, None)

    win = window(app, maps=None, settings=settings)
    try:
        win.mapper.target = machine(curse_geo)
        ticked(win.map)

        assert WRONG_GAME in [line.split("  ", 1)[-1]
                              for line in win.map.messages.lines()]
        assert win.map.state.title == POOL.title
    finally:
        win.close()


def test_an_open_save_decides_and_the_machine_does_not_override_it(
        app, tmp_path, monkeypatch):
    """`#21 (The running game is guessed from a preference, so both title
    safeguards can fail open)`'s guard: with a save open, the save decides
    the title, and the machine drawing another configured title's map is
    not license to switch out from under the player."""
    import types
    nowhere(tmp_path, monkeypatch)
    pool_geo = walled_geo(art=1)
    curse_geo = walled_geo(art=5, rooms=3)
    settings, _folders = _configured(tmp_path, pool_geo, curse_geo)

    win = window(app, maps=None, settings=settings)
    try:
        win.editor.party = types.SimpleNamespace(game=POOL)
        win.mapper.target = machine(curse_geo)
        ticked(win.map)

        assert WRONG_GAME in [line.split("  ", 1)[-1]
                              for line in win.map.messages.lines()]
        assert win.map.state.title == POOL.title
    finally:
        win.close()


def test_the_switch_is_exact_match_only(app, tmp_path, monkeypatch):
    """A drifted copy of another configured title's map is not a switch --
    `identify_elsewhere` never uses `ResidentGeo`'s `NEAR_ENOUGH` tolerance,
    only an exact hit."""
    from automap.area import NEAR_ENOUGH
    nowhere(tmp_path, monkeypatch)
    pool_geo = walled_geo(art=1)
    curse_geo = walled_geo(art=5, rooms=3)
    settings, _folders = _configured(tmp_path, pool_geo, curse_geo)

    win = window(app, maps=None, settings=settings)
    try:
        drifted = a_few_bytes_different(curse_geo, NEAR_ENOUGH - 1)
        win.mapper.target = machine(drifted)
        ticked(win.map)

        assert WRONG_GAME in [line.split("  ", 1)[-1]
                              for line in win.map.messages.lines()]
        assert win.map.state.title == POOL.title
    finally:
        win.close()
