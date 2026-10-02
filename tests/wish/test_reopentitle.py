from __future__ import annotations

"""`#811 (After Wish is reopened over a running Amiga Silver Blades, the map
uses Pool of Radiance's place names and notes file)`.

A player runs Silver Blades with only that title's disks folder set and no
save open. The map tab names New Verdigris. The player closes Wish and opens
it again with the game still running, and the reopened map must still be
Silver Blades': its place names, and the squares the first window saved.

A window built with no maps handed to it reads them off the configured folder
itself. It used to take the title from that folder only for an Amiga-only
title, so every other title opened labelled Pool of Radiance. The machine was
drawing a map those same disks hold, so the title check read it as ours and
nothing ever corrected the label. The disks here are synthetic and hold no
game data.
"""

import struct

import pytest
from gamedata import _disk_with, synthetic_geo

from automap import c64, paths
from automap.area import RESIDENT_GEO
from automap.config import Settings
from automap.maps import AMIGA_ONLY_TITLES
from automap.target import MemoryTarget
from goldbox import c64_port
from goldbox.amiga_adf import AmigaDisk
from goldbox.geo import (
    BARRIERS,
    GRID,
    SOLID,
    WALLS_NORTH_EAST,
    WALLS_SOUTH_WEST,
    Geo,
)
from wish import backends as bk

POOL = c64_port.POOL_OF_RADIANCE
CURSE = c64_port.CURSE_OF_THE_AZURE_BONDS
SILVER = c64_port.SECRET_OF_THE_SILVER_BLADES
POD = AMIGA_ONLY_TITLES[0]

pytestmark = pytest.mark.usefixtures("no_registry")

#: The map the machine is drawing in every test here, by its file stem.
AREA = "GEO10"


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    monkeypatch.delenv("POR_DISKS", raising=False)
    monkeypatch.delenv(bk.AMIGA_FSUAE_ENV, raising=False)


@pytest.fixture
def amiga_on(monkeypatch):
    monkeypatch.setenv(bk.AMIGA_FSUAE_ENV, "1")


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def nowhere(tmp_path, monkeypatch):
    empty = tmp_path / "empty-home"
    empty.mkdir(exist_ok=True)
    monkeypatch.setattr(paths, "_home", lambda: empty)
    monkeypatch.chdir(empty)


def walled_geo(art: int = 1, rooms: int = 4) -> Geo:
    """A generated map with walls drawn from both sides, as real ones are."""
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


def glib(maps: dict[int, bytes]) -> bytes:
    """A `GEO.GLB`: the index block, then one block per map."""
    ids = sorted(maps)
    index = struct.pack(">H", len(ids)) + b"".join(
        struct.pack(">HH", ident, n + 1) for n, ident in enumerate(ids))
    blocks = [index] + [maps[i] for i in ids]
    body = b"".join(blocks)
    head = (b"GLIB" + struct.pack(">I", len(body))
            + struct.pack(">HH", len(blocks), 0) + b"GEO ")
    offsets, at = [], len(head) + 4 * (len(blocks) + 1)
    for block in blocks:
        offsets.append(at)
        at += len(block)
    offsets.append(at)
    return head + b"".join(struct.pack(">I", o) for o in offsets) + body


#: Each title's synthetic disk, as the folder a player would set: an Amiga
#: image named by its volume, or a C64 image named by the title's glob.
AMIGA_VOLUMES = {SILVER.key: "SECRET B", CURSE.key: "CURSE B",
                 POD.key: "POD 3"}
C64_IMAGES = {SILVER.key: "SILVER1.D64", CURSE.key: "CURSE1.D64"}


def amiga_folder(where, game, geo: Geo):
    image = AmigaDisk.blank(AMIGA_VOLUMES[game.key])
    image.make_dir("DISKB")
    image.write_file("DISKB/GEO.GLB", glib({int(AREA[3:], 16): geo.to_bytes()}))
    where.mkdir(parents=True, exist_ok=True)
    (where / "disk2.adf").write_bytes(image.to_bytes())
    return where


def c64_folder(where, game, geo: Geo):
    where.mkdir(parents=True, exist_ok=True)
    (where / C64_IMAGES[game.key]).write_bytes(
        _disk_with([(AREA.encode(), geo.to_bytes())]))
    return where


def machine(game, resident: Geo, position) -> MemoryTarget:
    """A machine drawing `resident` with the party at `position`."""
    blocks = {0xD011: bytes([0x1B]), 0xD018: bytes([0x15]),
              0xDD00: bytes([0x17]), RESIDENT_GEO: resident.to_bytes(),
              c64.DEFAULT.live_position: bytes(position)}
    own = c64_port.by_title(game.title)
    if own is not None:
        blocks[c64.machine_for(own).live_position] = bytes(position)
    return MemoryTarget(blocks)


def window(app, settings):
    """A window as `tools/amiga/fsuaegdb.py wish` opens it: no save, no maps
    handed in, the title's folder only in the settings."""
    from wish.session import Session
    from wish.window import WishWindow
    win = WishWindow(None, settings=settings,
                     session=Session(find=lambda pref=None: None))
    win.announce = lambda title, text: None
    return win


def walked(win, game, geo, *squares):
    """The party stands on each square in turn, with the window ticking."""
    for square in squares:
        win.mapper.target = machine(game, geo, (*square, 0))
        for _ in range(24):
            win.map.tick()


def open_close_open(app, settings, game, geo):
    """The issue's sequence: open, settle, walk, close, reopen over the same
    running machine and settings. Returns the squares the first window saw
    and the second window."""
    first = window(app, settings)
    try:
        walked(first, game, geo, (4, 5), (5, 5), (6, 5))
        assert first.map.state.title == game.title
        before = set(first.map.state.exploration.seen)
        assert before
    finally:
        first.close()
    second = window(app, settings)
    walked(second, game, geo, (6, 5))
    return before, second


@pytest.mark.parametrize("game", [SILVER, CURSE], ids=lambda g: g.key)
def test_a_reopened_window_over_a_running_amiga_title_maps_that_title(
        app, tmp_path, monkeypatch, amiga_on, game):
    nowhere(tmp_path, monkeypatch)
    geo = walled_geo(art=5, rooms=3)
    folder = amiga_folder(tmp_path / "disks", game, geo)
    settings = Settings(game_folders={game.key: str(folder)})

    before, win = open_close_open(app, settings, game, geo)
    try:
        assert win.map.state.title == game.title
        assert win.map.state.area == AREA
        assert before <= win.map.state.exploration.seen
        assert win.map.state.notes_path().parent.name == game.key
    finally:
        win.close()


def test_a_reopened_window_over_pools_of_darkness_maps_pools_of_darkness(
        app, tmp_path, monkeypatch, amiga_on):
    """The Amiga-only title, which the window already named from its folder.
    It has no C64 descriptor, so the test machine here cannot place the party
    and only the title is asserted."""
    nowhere(tmp_path, monkeypatch)
    geo = walled_geo(art=5, rooms=3)
    folder = amiga_folder(tmp_path / "disks", POD, geo)
    settings = Settings(game_folders={POD.key: str(folder)})

    for _ in range(2):
        win = window(app, settings)
        try:
            walked(win, POD, geo, (4, 5))
            assert win.map.state.title == POD.title
        finally:
            win.close()


def test_the_reopened_silver_blades_map_is_named_new_verdigris(
        app, tmp_path, monkeypatch, amiga_on):
    """The issue's own observation: `area_label` read The Lizardman Keep,
    Pool of Radiance's name for the same file stem."""
    nowhere(tmp_path, monkeypatch)
    geo = walled_geo(art=5, rooms=3)
    folder = amiga_folder(tmp_path / "disks", SILVER, geo)
    settings = Settings(game_folders={SILVER.key: str(folder)})

    _before, win = open_close_open(app, settings, SILVER, geo)
    try:
        assert win.map.state.area_label == "New Verdigris"
        assert not (paths.data_dir() / "maps" / POOL.key).exists()
    finally:
        win.close()


def test_a_window_switched_by_the_machine_keeps_the_title_after_a_reopen(
        app, tmp_path, monkeypatch, amiga_on):
    """The live run's own sequence: its first window opened labelled Pool of
    Radiance and was switched to Silver Blades by the machine ("Now mapping
    Secret of the Silver Blades."), so the squares were saved under Silver
    Blades. The reopened window must find them."""
    nowhere(tmp_path, monkeypatch)
    geo = walled_geo(art=5, rooms=3)
    folder = amiga_folder(tmp_path / "disks", SILVER, geo)
    settings = Settings(game_folders={SILVER.key: str(folder)})

    first = window(app, settings)
    try:
        first.observe_title(SILVER.title)
        walked(first, SILVER, geo, (4, 5), (5, 5))
        before = set(first.map.state.exploration.seen)
    finally:
        first.close()
    win = window(app, settings)
    try:
        walked(win, SILVER, geo, (5, 5))
        assert win.map.state.title == SILVER.title
        assert win.map.state.area_label == "New Verdigris"
        assert before <= win.map.state.exploration.seen
    finally:
        win.close()


@pytest.mark.parametrize("game", [SILVER, CURSE], ids=lambda g: g.key)
def test_a_reopened_window_over_a_running_c64_title_maps_that_title(
        app, tmp_path, monkeypatch, game):
    """The same window path with C64 disks: the folder named the title for
    neither, flag or no flag."""
    nowhere(tmp_path, monkeypatch)
    geo = walled_geo(art=5, rooms=3)
    folder = c64_folder(tmp_path / "disks", game, geo)
    settings = Settings(game_folders={game.key: str(folder)})

    before, win = open_close_open(app, settings, game, geo)
    try:
        assert win.map.state.title == game.title
        assert before <= win.map.state.exploration.seen
    finally:
        win.close()



# --- the paths the folder's title leaves alone --------------------------------

def test_an_open_save_names_the_title_over_the_folder(
        app, tmp_path, monkeypatch, amiga_on):
    """A save is the player's choice: a Curse save open beside Silver Blades'
    folder labels the map Curse, not Silver Blades."""
    from gamedata import synthetic_save

    from wish.session import Session
    from wish.window import WishWindow
    nowhere(tmp_path, monkeypatch)
    folder = amiga_folder(tmp_path / "disks", SILVER, walled_geo())
    settings = Settings(game_folders={SILVER.key: str(folder)})
    save = synthetic_save(tmp_path, game=CURSE)

    win = WishWindow(str(save), settings=settings,
                     session=Session(find=lambda pref=None: None))
    try:
        assert win.editor.party is not None
        assert win.editor.party.game.title == CURSE.title
        assert win.map.state.title == CURSE.title
    finally:
        win.close()


def test_with_no_folder_set_the_window_is_pool_of_radiance(
        app, tmp_path, monkeypatch, amiga_on):
    """No save, no folder, no disks anywhere: the default title, as before."""
    nowhere(tmp_path, monkeypatch)
    win = window(app, Settings())
    try:
        assert win.disks is None
        assert win.map.state.title == POOL.title
    finally:
        win.close()


def test_with_two_folders_set_the_first_in_games_order_names_the_title(
        app, tmp_path, monkeypatch, amiga_on):
    """Silver Blades' and Curse's folders both set: Curse comes first in
    `c64_port.GAMES`, so its folder and title answer, and `reload_disks`
    agrees with the window it was built in."""
    nowhere(tmp_path, monkeypatch)
    silver = amiga_folder(tmp_path / "silver", SILVER, walled_geo(art=5))
    curse = amiga_folder(tmp_path / "curse", CURSE, walled_geo(art=3))
    assert ([g.key for g in c64_port.GAMES].index(CURSE.key)
            < [g.key for g in c64_port.GAMES].index(SILVER.key))
    settings = Settings(game_folders={SILVER.key: str(silver),
                                      CURSE.key: str(curse)})

    win = window(app, settings)
    try:
        assert str(win.disks) == str(curse)
        assert win.map.state.title == CURSE.title
        win.reload_disks()
        assert str(win.disks) == str(curse)
        assert win.map.state.title == CURSE.title
    finally:
        win.close()
