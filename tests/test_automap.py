
def make_root():
    from PyQt6.QtWidgets import QMainWindow

    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    return root

"""Tests for the live automapper's model, geometry and party panel.

Nothing here needs an emulator or a display: `ReplayTarget` and `MemoryTarget`
stand in for VICE, `render.py` emits primitives rather than painting them, and
the widgets run offscreen. A save file *is* a captured snapshot of the two
ranges the live view reads, so the fixtures under `tests/fixtures` serve as
recorded machines.
"""

import inspect
import json
import os
import pathlib

import pytest
from gamedata import disk_dir, game_file, synthetic_geo

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from automap.area import RESIDENT_GEO, Fingerprint
from automap.notes import Note
from automap.render import (
    CELL,
    MARGIN,
    Glyph,
    Label,
    Line,
    Poly,
    Rect,
    edge_primitives,
    map_primitives,
    merged_edge,
    note_primitives,
    party_marker,
    to_svg,
)
from automap.state import Automapper, AutomapState, Exploration, title_dir
from automap.state import data_dir as state_data_dir
from automap.target import Fix, MemoryTarget, ReplayTarget
from goldbox import games
from goldbox.geo import (
    EAST,
    GEO_SIZE,
    GRID,
    LOCKED,
    NORTH,
    PASSABLE,
    SOLID,
    SOUTH,
    WALLS_NORTH_EAST,
    WALLS_SOUTH_WEST,
    WEST,
    WIZARD_LOCKED,
    Geo,
    load_geo_files,
)

# Wherever the player keeps them, not wherever one machine did.
DISKS = str(disk_dir() or "no-disks-here")
FIXTURES = pathlib.Path(__file__).parent / "fixtures"
game_disks = pytest.mark.skipif(not pathlib.Path(f"{DISKS}/POOL3.D64").exists(),
                                reason="needs the game disks")


@pytest.fixture
def geo():
    return Geo.from_bytes(game_file("GEO04"))


@pytest.fixture
def new_phlan():
    """GEO00 off the player's disk, skipping when there is none."""
    if disk_dir() is None:
        pytest.skip("needs the game disks")
    return load_geo_files(f"{DISKS}/POOL3.D64")["GEO00"]


# --- door drawing -----------------------------------------------------------

def _door_edge(geo):
    for y in range(GRID):
        for x in range(GRID):
            for d in (NORTH, EAST):
                e = merged_edge(geo, x, y, d)
                if e and e.barrier == PASSABLE:
                    return e
    pytest.skip("fixture has no door")


def _solid_edge(geo):
    for y in range(GRID):
        for x in range(GRID):
            for d in (NORTH, EAST):
                e = merged_edge(geo, x, y, d)
                if e and e.barrier == SOLID:
                    return e
    pytest.skip("fixture has no solid wall")


def test_a_solid_wall_is_one_unbroken_line(geo):
    prims = list(edge_primitives(_solid_edge(geo)))
    assert len(prims) == 1
    assert isinstance(prims[0], Line) and prims[0].kind == "wall"


def test_a_door_breaks_the_wall_and_gets_a_leaf(geo):
    """The whole point: a barrier is drawn as a door, not as a coloured wall."""
    prims = list(edge_primitives(_door_edge(geo)))
    lines = [p for p in prims if isinstance(p, Line)]
    leaves = [p for p in prims if isinstance(p, Rect)]
    assert len(lines) == 2, "the wall must be broken either side of the doorway"
    assert len(leaves) == 1 and leaves[0].kind == "door"
    gap = CELL * 0.52
    assert sum(abs(ln.x2 - ln.x1) + abs(ln.y2 - ln.y1) for ln in lines) == \
        pytest.approx(CELL - gap)


def test_a_locked_door_adds_a_bar_and_a_wizard_lock_adds_a_star():
    raw = bytearray(1024)
    raw[0x000] = 0x50                       # north wall art on square (0,0)
    raw[0x300] = LOCKED                     # ...locked
    locked = list(edge_primitives(merged_edge(Geo(bytes(raw)), 0, 0, NORTH)))
    assert any(p.kind == "bar" for p in locked if isinstance(p, Line))
    assert not any(p.kind == "star" for p in locked if isinstance(p, Line))

    raw[0x300] = WIZARD_LOCKED
    wiz = list(edge_primitives(merged_edge(Geo(bytes(raw)), 0, 0, NORTH)))
    assert any(p.kind == "star" for p in wiz if isinstance(p, Line))
    assert [p for p in wiz if isinstance(p, Rect)][0].kind == "door-wizard"


def test_an_edge_with_no_art_draws_nothing():
    assert merged_edge(Geo(bytes(1024)), 5, 5, NORTH) is None


def test_an_edge_is_drawn_from_whichever_side_has_art():
    """Wall art is only 0.960 reciprocal, so one-way edges exist. Drawing only
    each square's north and west edges -- what Geo.to_text does -- loses them."""
    raw = bytearray(1024)
    raw[0x100 + (0 + (0 << 4))] = 0x30      # south art on (0,0) only
    geo = Geo(bytes(raw))
    assert geo.wall(0, 1, NORTH) == 0       # the neighbour disagrees
    assert merged_edge(geo, 0, 1, NORTH) is not None


def test_the_easier_reading_of_a_shared_edge_wins():
    raw = bytearray(1024)
    raw[0x100] = 0x30                       # (0,0) south: art, solid
    raw[0x000 + 0x10] = 0x30                # (0,1) north: art
    raw[0x300 + 0x10] = PASSABLE            # ...and passable
    edge = merged_edge(Geo(bytes(raw)), 0, 0, 2)
    assert edge.barrier == PASSABLE


@game_disks
def test_the_inn_door_is_a_door(new_phlan):
    """PORSAVE4 sits at (2,14) inside the inn and PORSAVE5 at (3,14) outside it.
    The west edge of (3,14) is the inn door, and it must draw as one."""
    edge = merged_edge(new_phlan, 3, 14, WEST)
    assert edge is not None and edge.is_door
    assert any(isinstance(p, Rect) and p.kind.startswith("door")
               for p in edge_primitives(edge))


@game_disks
def test_new_phlan_draws_walls_doors_and_roofs(new_phlan):
    prims = list(map_primitives(new_phlan))
    kinds = {p.kind for p in prims}
    assert {"wall", "door", "roofed"} <= kinds
    assert len([p for p in prims if isinstance(p, Rect)
                and p.kind.startswith("door")]) > 20


def test_the_party_marker_points_where_it_faces():
    north = party_marker(5, 5, NORTH)
    south = party_marker(5, 5, 2)
    assert isinstance(north, Poly)
    assert min(p[1] for p in north.points) < min(p[1] for p in south.points)


@game_disks
def test_svg_renders(new_phlan):
    svg = to_svg(new_phlan, party=(3, 14, 0))
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert "polygon" in svg


# --- exploration ------------------------------------------------------------

def test_without_a_map_only_the_square_itself_is_revealed():
    """Passability cannot be checked before the area is known, so claim nothing."""
    e = Exploration()
    e.visit(5, 5)
    assert e.seen == {(5, 5)}


@game_disks
def test_sight_stops_at_walls(new_phlan):
    """The bug this replaced: revealing all four neighbours drew the far wall of
    a corridor the party had never entered and could not see, because there was
    a wall between them and it."""
    e = Exploration()
    e.visit(3, 14, new_phlan)
    assert (3, 14) in e
    assert not new_phlan.is_passable(3, 14, SOUTH)
    assert (3, 15) not in e, "revealed a square behind a wall"


@game_disks
def test_sight_runs_down_an_open_corridor(new_phlan):
    """North up the street is open; west is the inn door, and sight stops at it
    -- the party is standing outside a closed door and cannot see the room."""
    e = Exploration()
    e.visit(3, 14, new_phlan)
    assert {(3, 13), (3, 12), (3, 11)} <= e.seen      # north, up the street
    assert {(4, 14), (5, 14), (6, 14)} <= e.seen      # east, along it
    assert new_phlan.is_passable(3, 14, WEST)         # walkable...
    assert (2, 14) not in e.seen                      # ...but not see-through


@game_disks
def test_sight_is_bounded(new_phlan):
    """Four squares, not the whole street -- the 3D view does not show forever."""
    e = Exploration(sight=2)
    e.visit(3, 14, new_phlan)
    assert (3, 12) in e and (3, 11) not in e


def _geo_with_a_door_north_of(x, y, barrier=PASSABLE):
    raw = bytearray(1024)
    raw[0x000 + x + (y << 4)] = 0x50          # north wall art: a door leaf
    raw[0x300 + x + (y << 4)] = barrier       # ...and it opens
    return Geo(bytes(raw))


@pytest.mark.parametrize("barrier", [PASSABLE, LOCKED, WIZARD_LOCKED])
def test_sight_does_not_pass_through_a_door(barrier):
    """The fog used to lift off rooms behind doors the party never opened:
    `is_passable` is true for a shut door, a locked one and a wizard-locked
    one alike."""
    geo = _geo_with_a_door_north_of(5, 5, barrier)
    e = Exploration()
    e.visit(5, 5, geo)
    assert (5, 5) in e
    assert (5, 4) not in e, "revealed the square behind a door"
    assert (5, 6) in e, "the other directions are open and must still reveal"


def test_sight_runs_to_full_depth_where_there_is_no_art():
    """A corridor with nothing drawn on it reveals SIGHT squares each way."""
    e = Exploration(sight=4)
    e.visit(5, 5, Geo(bytes(1024)))
    assert {(5, 1), (5, 9), (1, 5), (9, 5)} <= e.seen
    assert (5, 0) not in e.seen and (10, 5) not in e.seen


def test_a_wall_with_no_barrier_bits_still_blocks_sight():
    """An edge with art and a SOLID barrier is a wall; it always blocked."""
    e = Exploration()
    e.visit(5, 5, _geo_with_a_door_north_of(5, 5, SOLID))
    assert (5, 4) not in e


def test_exploration_does_not_run_off_the_grid():
    e = Exploration()
    e.visit(0, 0)
    assert all(0 <= x < GRID and 0 <= y < GRID for x, y in e.seen)


def test_fog_hides_what_has_not_been_seen():
    st = AutomapState()
    st.reveal = True
    st.exploration.visit(3, 3)
    assert st.is_visible(3, 3) and not st.is_visible(10, 10)


def test_fog_is_on_by_default_and_the_choice_is_remembered(tmp_path,
                                                          monkeypatch):
    """Discovering the map is the point, but unchecking the box must stick."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from automap.config import Settings

    assert Settings().reveal is True
    Settings(reveal=False).save()
    assert Settings.load().reveal is False


# --- area identification ----------------------------------------------------

@game_disks
def test_the_fingerprint_narrows_to_new_phlan():
    """The walk Donald recorded: out of the inn at (2,14), north to (3,11),
    then west to the block edge at (0,11)."""
    maps = load_geo_files(f"{DISKS}/POOL3.D64")
    for disk in ("POOL1", "POOL2", "POOL4", "POOL5", "POOL6", "POOL7", "POOL8"):
        for name, geo in load_geo_files(f"{DISKS}/{disk}.D64").items():
            maps.setdefault(name, geo)
    route = [(2, 14), (3, 14), (3, 13), (3, 12), (3, 11),
             (2, 11), (1, 11), (0, 11)]
    fp = Fingerprint(maps)
    before = len(fp.names)
    for a, b in zip(route, route[1:]):
        fp.moved(*a, *b)
    assert "GEO00" in fp.names
    assert len(fp.names) < before


@game_disks
def test_a_refused_step_narrows_hard():
    maps = load_geo_files(f"{DISKS}/POOL3.D64")
    fp = Fingerprint(maps)
    fp.refused(0, 0, NORTH)               # the map edge blocks everyone
    assert fp.names


def test_an_observation_that_fits_nothing_is_counted_not_obeyed():
    """A contradiction says the observation was wrong, not that the map is
    unknown -- keep the last set that fitted, and say how often it happened."""
    fp = Fingerprint({"X": Geo(bytes(1024))})       # nothing is blocked here
    fp.refused(5, 5, NORTH)
    assert fp.names == ["X"]
    assert fp.contradictions == 1


# --- a refused step, inferred from the clock ---------------------------------

def _mapper_over(fixes, tmp_path, monkeypatch, geo=None):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    mapper = Automapper(ReplayTarget(fixes), {"X": geo or Geo(bytes(1024))},
                        area="X")
    for _ in fixes:
        mapper.poll()
    return mapper


def test_a_step_the_game_refused_is_recorded(tmp_path, monkeypatch):
    """The whole point of A3: the mapper cannot see key presses, but the clock
    advancing while the party stays put and keeps facing the same way is a bump
    -- and one bump identifies an area that 111 successful steps would not."""
    fixes = [Fix(5, 5, NORTH, "status", 16 * 60 + 47),
             Fix(5, 5, NORTH, "status", 16 * 60 + 48)]
    mapper = _mapper_over(fixes, tmp_path, monkeypatch)
    assert mapper.fingerprint.blocked == [(5, 5, NORTH)]


def test_standing_still_is_not_a_refused_step(tmp_path, monkeypatch):
    """The clock does not run while the party does nothing, and doing nothing
    must not be evidence about anything."""
    fixes = [Fix(5, 5, NORTH, "status", 1000)] * 3
    assert _mapper_over(fixes, tmp_path, monkeypatch).fingerprint.blocked == []


def test_a_long_wait_is_not_a_refused_step(tmp_path, monkeypatch):
    """Searching, resting and camping all move the clock without a step."""
    fixes = [Fix(5, 5, NORTH, "status", 1000),
             Fix(5, 5, NORTH, "status", 1010)]
    assert _mapper_over(fixes, tmp_path, monkeypatch).fingerprint.blocked == []


def test_turning_on_the_spot_is_not_a_refused_step(tmp_path, monkeypatch):
    fixes = [Fix(5, 5, NORTH, "status", 1000),
             Fix(5, 5, EAST, "status", 1001)]
    assert _mapper_over(fixes, tmp_path, monkeypatch).fingerprint.blocked == []


def test_a_memory_fix_never_counts_as_refused(tmp_path, monkeypatch):
    """$49C0 lags a move, so a real step read from memory looks exactly like a
    bump. Only the status line is trusted for this."""
    fixes = [Fix(5, 5, NORTH, "memory", 1000),
             Fix(5, 5, NORTH, "memory", 1001)]
    assert _mapper_over(fixes, tmp_path, monkeypatch).fingerprint.blocked == []


@game_disks
def test_one_refused_step_beats_a_hundred_successful_ones(new_phlan):
    """Positive evidence needs 111 steps to settle New Phlan. Count what one
    bump is worth against what standing on a square is worth."""
    maps = load_geo_files(f"{DISKS}/POOL3.D64")
    for disk in ("POOL1", "POOL2", "POOL4", "POOL5"):
        for name, g in load_geo_files(f"{DISKS}/{disk}.D64").items():
            maps.setdefault(name, g)
    seen = Fingerprint(maps)
    seen.saw(3, 14)
    bumped = Fingerprint(maps)
    bumped.refused(3, 14, SOUTH)          # the wall south of the inn door
    assert len(bumped.names) < len(seen.names)


# --- the mapper loop --------------------------------------------------------

@game_disks
def test_polling_tracks_movement(new_phlan, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    fixes = [Fix(3, 14, 0, "status"), Fix(3, 13, 0, "status"),
             Fix(3, 12, 0, "status")]
    mapper = Automapper(ReplayTarget(fixes), {"GEO00": new_phlan}, area="GEO00")
    for _ in fixes:
        mapper.poll()
    assert (mapper.state.x, mapper.state.y) == (3, 12)
    assert (3, 13) in mapper.state.exploration
    assert mapper.state.exploration.trail[0] == (3, 14)


def test_a_missing_fix_changes_nothing():
    mapper = Automapper(ReplayTarget([]))
    assert mapper.poll() is False


@game_disks
def test_notes_survive_a_round_trip(new_phlan, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    mapper = Automapper(ReplayTarget([Fix(1, 1, 0, "status")]),
                        {"GEO00": new_phlan}, area="GEO00")
    mapper.poll()
    mapper.state.add_note(4, 4, Note("fortune teller", "person"))
    mapper.state.save_notes()

    again = Automapper(ReplayTarget([]), {"GEO00": new_phlan}, area="GEO00")
    kept = again.state.notes_at(4, 4)
    assert [(n.text, n.type) for n in kept] == [("fortune teller", "person")]
    assert (1, 1) in again.state.exploration


# --- settings ---------------------------------------------------------------

def test_settings_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from automap.config import Settings

    assert Settings().reveal is True           # fog on until turned off
    Settings(reveal=False, window_width=900).save()
    assert Settings.load().reveal is False     # and the choice sticks
    assert Settings.load().window_width == 900


def test_a_fresh_config_offers_three_areas_for_fast_travel(tmp_path,
                                                          monkeypatch):
    """New Phlan, The Slums and Sokol Keep -- `goldbox/areas.py` ids 0, 20 and 21.
    The setting is None until somebody ticks something, which is what tells a
    fresh config from a player who unticked everything."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from automap.config import DEFAULT_FAST_TRAVEL_TARGETS, Settings

    assert Settings().fast_travel_targets is None
    assert Settings().chosen_areas() == DEFAULT_FAST_TRAVEL_TARGETS == (
        0, 20, 21)
    # And a file written before the setting existed is a fresh config too.
    Settings(reveal=False).save()
    assert Settings.load().chosen_areas() == (0, 20, 21)


def test_the_chosen_areas_survive_a_reload_and_so_does_an_empty_choice(
        tmp_path, monkeypatch):
    """Unticking everything is an answer: it has to come back as an empty list
    and not as the defaults, or the setting would undo itself overnight."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from automap.config import Settings

    settings = Settings()
    settings.set_chosen_areas([13, 0, 13])
    settings.save()
    assert Settings.load().chosen_areas() == (0, 13)

    settings.set_chosen_areas([])
    settings.save()
    assert Settings.load().fast_travel_targets == {"pool-of-radiance": []}
    assert Settings.load().chosen_areas() == ()


def test_a_hand_edited_area_list_is_read_for_what_it_holds(tmp_path,
                                                           monkeypatch):
    """The settings file is documented as one you can edit, so a row that is
    not a number loses that row and nothing else."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from automap.config import Settings

    assert Settings(fast_travel_targets={
        "pool-of-radiance": ["0", 20, None, "twenty"]}).chosen_areas() == (
        0, 20)
    assert Settings(fast_travel_targets=7).chosen_areas() == (0, 20, 21)
    assert Settings(fast_travel_targets={
        "pool-of-radiance": 7}).chosen_areas() == (0, 20, 21)


def test_the_ticks_are_kept_per_title_and_one_title_does_not_disturb_another(
        tmp_path, monkeypatch):
    """An area id means nothing without a title, so the file is keyed by
    `goldbox.games.Game.key` -- `docs/138-multiple-games.md` §5.

    Only Pool of Radiance has a default, because only Pool of Radiance has an
    area table: a tick for a title with no table would be an id off another
    game's list."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from automap.config import Settings
    from goldbox import games

    fresh = Settings()
    assert fresh.chosen_areas(games.POOL_OF_RADIANCE) == (0, 20, 21)
    assert fresh.chosen_areas(games.CURSE_OF_THE_AZURE_BONDS) == ()
    assert fresh.chosen_areas(games.SECRET_OF_THE_SILVER_BLADES) == ()

    fresh.set_chosen_areas([13], games.CURSE_OF_THE_AZURE_BONDS)
    assert fresh.chosen_areas(games.CURSE_OF_THE_AZURE_BONDS) == (13,)
    # Pool of Radiance's list is untouched, and is still the default.
    assert fresh.chosen_areas(games.POOL_OF_RADIANCE) == (0, 20, 21)
    assert "pool-of-radiance" not in fresh.fast_travel_targets


def test_unreadable_settings_are_not_fatal(tmp_path, monkeypatch):
    """Losing a preference is not worth refusing to start."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from automap.config import FILE, Settings
    from automap.paths import config_dir

    config_dir().mkdir(parents=True, exist_ok=True)
    (config_dir() / FILE).write_text("{ not json")
    assert Settings.load().reveal is True      # falls back to defaults


def test_settings_ignore_keys_they_do_not_know(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    import json

    from automap.config import FILE, Settings
    from automap.paths import config_dir

    config_dir().mkdir(parents=True, exist_ok=True)
    (config_dir() / FILE).write_text(json.dumps({"reveal": True, "bogus": 1}))
    assert Settings.load().reveal is True


def test_paths_differ_by_platform(monkeypatch):
    """Windows must not be handed an XDG path, or a dotfile in the user's home."""

    import automap.paths as paths

    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\x\AppData\Roaming")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\x\AppData\Local")
    assert "Roaming" in str(paths.config_dir())
    assert "Local" in str(paths.data_dir())
    assert "vice.ini" in paths.vice_settings_hint()


# --- believing what the screen says ------------------------------------------

@game_disks
def test_a_garbled_read_does_not_move_the_marker(new_phlan, tmp_path,
                                                 monkeypatch):
    """The status line is read off a screen that may be half redrawn. A single
    impossible jump used to fling the marker across the map and back, and paint
    exploration where the party had never been."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    fixes = [Fix(3, 14, 0, "status"), Fix(3, 13, 0, "status"),
             Fix(15, 1, 0, "status"),          # nonsense, appears once
             Fix(3, 12, 0, "status")]
    mapper = Automapper(ReplayTarget(fixes), {"GEO00": new_phlan}, area="GEO00")
    for _ in fixes:
        mapper.poll()
    assert (mapper.state.x, mapper.state.y) == (3, 12)
    assert (15, 1) not in mapper.state.exploration


@game_disks
def test_a_jump_confirmed_twice_is_believed(new_phlan, tmp_path, monkeypatch):
    """A genuine long move inside one area costs one extra tick, not the move."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    fixes = [Fix(3, 14, 0, "status"), Fix(9, 9, 0, "status"),
             Fix(9, 9, 0, "status")]
    mapper = Automapper(ReplayTarget(fixes), {"GEO00": new_phlan}, area="GEO00")
    for _ in fixes:
        mapper.poll()
    assert (mapper.state.x, mapper.state.y) == (9, 9)


@game_disks
def test_the_first_fix_is_believed_wherever_it_is(new_phlan, tmp_path,
                                                  monkeypatch):
    """Opening the map mid-game must not need two ticks to show the party."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    mapper = Automapper(ReplayTarget([Fix(11, 6, 1, "status")]),
                        {"GEO00": new_phlan}, area="GEO00")
    mapper.poll()
    assert (mapper.state.x, mapper.state.y) == (11, 6)


# --- crossing a boundary ----------------------------------------------------


class CrossingTarget(ReplayTarget):
    """A target that crosses an area boundary partway through its fixes.

    That is all a crossing is from outside the game: the fixes start naming
    squares on another map, and the 1024 bytes at `$0400` -- where the loader
    leaves the `GEO` and never moves it -- become that other map.
    """

    def __init__(self, fixes, before, after, cross_at):
        super().__init__(fixes)
        self.before, self.after = before, after
        self.cross_at = cross_at

    def read(self, addr, length):
        geo = self.after if self._i > self.cross_at else self.before
        if (addr, length) == (RESIDENT_GEO, GEO_SIZE):
            return geo.to_bytes()
        return bytes(length)


def sealed_at(x: int, y: int) -> Geo:
    """An otherwise open map with one square that cannot be occupied.

    Wall art on all four edges with the barrier left `SOLID`, which is what
    `Geo.is_passable` reads. Generated, not copied: see `tests/gamedata.py`.
    """
    raw = bytearray(GEO_SIZE)
    at = y * GRID + x
    raw[WALLS_NORTH_EAST + at] = 0x11           # north, east
    raw[WALLS_SOUTH_WEST + at] = 0x11           # south, west
    return Geo(bytes(raw))


def test_a_crossing_does_not_record_the_new_areas_squares_on_the_old_map(
        tmp_path, monkeypatch):
    """Donald's bug, on Windows: squares seen in the Slums stayed revealed on
    New Phlan after walking back into town.

    The immediate area check on a jump was itself rate-limited, so nine
    crossings in ten fell through to the ordinary every-tenth-poll check and
    the party's *new* square was recorded against the *old* area for up to two
    seconds -- and `set_area` then wrote it into that area's file, where it
    came back on the next visit and never went away.

    Reproduced live before it was fixed (`docs/98-automap-notes.md`): the party
    fasttraveled from the Slums to New Phlan, stepped to New Phlan's (14,1), and five
    New Phlan squares were saved into the Slums' own `GEO14.json`.
    """
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    phlan, slums = Geo(bytes(GEO_SIZE)), Geo(synthetic_geo())
    fixes = [Fix(3, 14, 0, "status", 1000), Fix(3, 13, 0, "status", 1001)]
    crossing = len(fixes)
    fixes += [Fix(14, 1, 0, "status", 1002)] * 6        # the Slums' top right
    mapper = Automapper(CrossingTarget(fixes, phlan, slums, crossing),
                        {"GEO00": phlan, "GEO14": slums}, area="GEO00")
    for _ in fixes:
        mapper.poll()

    assert mapper.state.area == "GEO14"
    assert (14, 1) in mapper.state.exploration
    notes = state_data_dir() / title_dir("Pool of Radiance") / "GEO00.json"
    kept = json.loads(notes.read_text())["seen"]
    assert "14,1" not in kept
    # nor anything the sight lines drew around it, on the wrong map: New
    # Phlan's own squares here run from x=0 to the sight limit at x=7.
    assert not [s for s in kept if int(s.split(",")[0]) > 9]


def walled_south_of(x: int, y: int) -> Geo:
    """An otherwise open map with one edge that cannot be stepped through."""
    raw = bytearray(GEO_SIZE)
    raw[WALLS_SOUTH_WEST + y * GRID + x] = 0x10          # south art, no barrier
    return Geo(bytes(raw))


def test_a_step_through_a_wall_says_the_map_is_wrong(tmp_path, monkeypatch):
    """The other tell of a crossing that moved the party only one square: the
    step it implies crosses an edge this map calls solid."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    phlan, slums = walled_south_of(5, 4), Geo(synthetic_geo())
    fixes = [Fix(5, 4, 0, "status", 1000)]
    crossing = len(fixes)
    fixes += [Fix(5, 5, 0, "status", 1001)] * 2
    mapper = Automapper(CrossingTarget(fixes, phlan, slums, crossing),
                        {"GEO00": phlan, "GEO14": slums}, area="GEO00")
    mapper.poll()
    mapper.poll()
    assert mapper.state.area == "GEO14"


def test_a_crossing_that_lands_next_door_is_caught_too(tmp_path, monkeypatch):
    """A crossing need not move the party far, and then there is no jump to
    notice it by -- but a square the current map seals cannot be occupied, so
    the map named is not the map being run."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    phlan, slums = sealed_at(5, 5), Geo(synthetic_geo())
    fixes = [Fix(5, 4, 0, "status", 1000)]
    crossing = len(fixes)
    fixes += [Fix(5, 5, 0, "status", 1001)] * 2
    mapper = Automapper(CrossingTarget(fixes, phlan, slums, crossing),
                        {"GEO00": phlan, "GEO14": slums}, area="GEO00")
    mapper.poll()
    mapper.poll()
    assert mapper.state.area == "GEO14"
    assert (5, 5) in mapper.state.exploration    # on the Slums, where it is


# --- a machine with no game on it -------------------------------------------

def fresh_boot(position=(0, 0, 0)) -> MemoryTarget:
    """A C64 with no game loaded: the state VICE comes back in.

    Three registers say where the screen is and that it is text -- $D011 $1B,
    $D018 $15, $DD00 $17, which is a boot machine's screen at $0400 -- and
    every other byte reads as zero, because that is what a target answers for
    memory nobody has written. So there is no status line to find on row 14,
    and the engine's position triple reads $00 $00 $00, which is square (0,0).

    `position` is there for the other half of it: while a game loads, that
    triple passes through values that are plausible squares and hold still for
    several polls.
    """
    return MemoryTarget({0xD011: bytes([0x1B]), 0xD018: bytes([0x15]),
                         0xDD00: bytes([0x17]),
                         games.DEFAULT.live_position: bytes(position)})


def test_a_machine_with_no_game_on_it_records_nothing(tmp_path, monkeypatch):
    """Donald's lone square at (0,0): VICE was restarted, wish reattached on
    its own, and a booting machine's zeroed position triple was recorded as a
    square the party had never stood on."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    mapper = Automapper(fresh_boot(), {"GEO14": Geo(synthetic_geo())},
                        area="GEO14")
    for _ in range(6):
        assert mapper.poll() is False
    assert mapper.state.exploration.seen == set()
    assert mapper.state.exploration.trail == []


def test_garbage_that_never_changes_agrees_with_itself(tmp_path, monkeypatch):
    """And so the second-opinion guard cannot catch this on its own: it holds
    a fix until a second poll agrees with it, and nothing is running to change
    the bytes. This is the corridor that appeared in the middle of the map."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    mapper = Automapper(fresh_boot((6, 7, 1)), {"GEO14": Geo(synthetic_geo())},
                        area="GEO14")
    for _ in range(6):
        assert mapper.poll() is False
    assert (6, 7) not in mapper.state.exploration
    assert (mapper.state.x, mapper.state.y) == (0, 0)


def test_a_reconnection_proves_the_game_again_before_recording(tmp_path,
                                                               monkeypatch):
    """A new connection is a new machine. What the last one established --
    where the party was, that a game was running at all -- says nothing about
    the one that has just started answering."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    fixes = [Fix(3, 14, 0, "status", 1000), Fix(3, 13, 0, "status", 1001)]
    mapper = Automapper(ReplayTarget(fixes), {"GEO14": Geo(synthetic_geo())},
                        area="GEO14")
    for _ in fixes:
        mapper.poll()
    seen = set(mapper.state.exploration.seen)
    assert seen                              # the good session did record

    mapper.target = fresh_boot((6, 7, 1))    # VICE closed, and opened again
    for _ in range(6):
        assert mapper.poll() is False
    assert mapper.state.exploration.seen == seen
    assert (mapper.state.x, mapper.state.y) == (3, 13)


def test_the_game_coming_back_starts_recording_again(tmp_path, monkeypatch):
    """The gate is not a latch on the window: once the game is back, its own
    status line proves it and the map picks up where the party actually is."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    mapper = Automapper(fresh_boot(), {"GEO14": Geo(synthetic_geo())},
                        area="GEO14")
    for _ in range(3):
        mapper.poll()
    mapper.target = ReplayTarget([Fix(9, 9, 0, "status", 1000)])
    mapper.poll()
    assert (mapper.state.x, mapper.state.y) == (9, 9)
    assert (9, 9) in mapper.state.exploration


def test_a_map_the_player_holds_is_proof_enough_without_a_status_line(
        tmp_path, monkeypatch):
    """Camp and the menus have no status line, so the fix comes from memory --
    and the map the game has loaded at $0400 is what says the game is there."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    geo = Geo(synthetic_geo())
    machine = fresh_boot((6, 7, 1))
    machine.memory[RESIDENT_GEO] = geo.to_bytes()
    mapper = Automapper(machine, {"GEO14": geo}, area="GEO14")
    mapper.poll()
    assert (mapper.state.x, mapper.state.y) == (6, 7)


def test_the_sight_radius_survives_a_crossing(tmp_path, monkeypatch):
    """It is a setting, not a property of the area. Building a plain
    `Exploration` on every area change quietly put it back to `SIGHT`."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    mapper = Automapper(ReplayTarget([]), {"GEO00": Geo(bytes(GEO_SIZE))},
                        area="GEO00")
    mapper.state.exploration.sight = 1
    mapper.set_area("GEO14")
    assert mapper.state.exploration.sight == 1


# --- the live party ---------------------------------------------------------

from automap import live  # noqa: E402
from automap.state import migrate_flat_notes  # noqa: E402
from automap.target import party_fix  # noqa: E402
from goldbox.record import FieldNotStored  # noqa: E402

CURSE = games.CURSE_OF_THE_AZURE_BONDS
CHAMPIONS = games.CHAMPIONS_OF_KRYNN


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def captured() -> tuple[bytes, bytes]:
    """One real machine, recorded: BRUTUS alone in New Phlan.

    `SAVEDGAME0` is a verbatim image of $4900-$64FF and the roster is the first
    page of `SAVEDGAME1`, so these two fixtures are exactly the two reads the
    live view makes -- with the PRG load address stripped off each.
    """
    save0 = (FIXTURES / "savedgame0.bin").read_bytes()[2:]
    save1 = (FIXTURES / "savedgame1.bin").read_bytes()[2:]
    return save0, save1[:live.ROSTER_PAGE]


def live_machine(save0=None, save1=None) -> MemoryTarget:
    if save0 is None or save1 is None:
        save0, save1 = captured()
    return MemoryTarget({0x4900: save0, 0x8300: save1})


def test_a_snapshot_decodes_a_party_from_captured_bytes():
    snap = live.snapshot_from_bytes(*captured())
    assert [c.name for c in snap.characters] == ["BRUTUS"]
    brutus = snap.characters[0]
    assert (brutus.hp, brutus.hp_max) == (11, 11)
    assert (brutus.armour_class, brutus.thac0) == (9, 18)
    assert brutus.class_text == "F" and brutus.level_text == "L1"
    assert (snap.x, snap.y, snap.facing) == (0, 4, 3)
    assert snap.clock_text == "0:01" and snap.area_file == "GEO00"


@game_disks
def test_the_party_reads_the_same_live_as_it_does_off_the_disk():
    """The assertion the editor's roster test makes, by a different path: the
    same bytes, read as a running machine rather than as a file.

    PORSAVE11 holds MALCYON, LADY KATHERINE, ROLAND, SILAS, MAGNUS, BRUTUS in
    slots 0-5, and `snap.characters` lists the game's own marching order --
    the occupied slots, highest first (`#160`)."""
    from goldbox.d64 import D64
    disk = D64.open(f"{DISKS}/PORSAVE11.D64")
    snap = live.read_snapshot(live_machine(
        disk.read_file(b"SAVEDGAME0")[2:],
        disk.read_file(b"SAVEDGAME1")[2:2 + live.ROSTER_PAGE]))
    roland = next(c for c in snap.characters if c.name == "ROLAND")
    assert (roland.hp, roland.hp_max) == (5, 7) and roland.hurt
    assert [c.name for c in snap.characters] == [
        "BRUTUS", "MAGNUS", "SILAS", "ROLAND", "LADY KATHERINE", "MALCYON"]
    katherine = snap.characters[4]
    assert katherine.class_text == "MU/T"      # two bars, not one
    assert len(katherine.classes) == 2


def test_a_machine_full_of_zeros_is_not_a_party():
    """At the title screen, mid-load, or before a save is loaded. Not an error,
    and not six dead characters either."""
    assert live.read_snapshot(live_machine(bytes(0x1C00), bytes(0x100))) is None


def test_an_impossible_position_is_refused():
    """Validate before trust: an overlay swap can put anything in these bytes."""
    save0, save1 = captured()
    broken = bytearray(save0)
    broken[0x49C0 - 0x4900] = 99
    assert live.snapshot_from_bytes(bytes(broken), save1) is None


def test_a_roster_page_borrowed_by_a_picture_is_refused():
    """#82: on Silver Blades, a full-screen picture leaves the roster page
    reading as graphics data while the record slots are fine, so the position
    and the records both pass -- only `roster_page_plausible` catches this."""
    from goldbox.savegame import ROSTER_SLOT_INDEX
    save0, save1 = captured()
    graphics = bytearray(save1)
    graphics[ROSTER_SLOT_INDEX] = 9          # BRUTUS is slot 0; this is not
    assert live.snapshot_from_bytes(save0, bytes(graphics)) is None
    # dismissed: the same page restored, and it reads normally again
    assert live.snapshot_from_bytes(save0, save1) is not None


def test_hit_points_above_the_recorded_maximum_refuse_the_roster_too():
    """The second, independent check #82 names: BRUTUS's maximum is 11."""
    from goldbox.savegame import ROSTER_HP_CURRENT
    save0, save1 = captured()
    over = bytearray(save1)
    over[ROSTER_HP_CURRENT] = 255
    assert live.snapshot_from_bytes(save0, bytes(over)) is None


def test_the_whole_tab_costs_two_reads():
    """The cost of a poll is the round trip, not the bytes -- 14.3 ms either
    way under VICE -- so this number is the one that matters."""
    machine = live_machine()
    live.read_snapshot(machine)
    assert machine.reads == [(0x4900, 0x1C00), (0x8300, 0x100)]


# --- the same reader, on another title's addresses (#29) --------------------

def curse_machine() -> MemoryTarget:
    """The captured party, laid out the way Curse of the Azure Bonds lays a
    save out: one payload at `$4B00` with the roster as its last page.

    Curse's `$1D00` payload is Pool of Radiance's `$1C00` with the roster's
    `$100` folded on, which is exactly these two fixtures concatenated -- so a
    Curse-shaped machine can be built from a Pool of Radiance save with no new
    bytes and no game disk. Nothing here claims the *contents* are a Curse
    party; what is under test is which addresses get read.
    """
    save0, roster = captured()
    return MemoryTarget({CURSE.save_load_address: save0 + roster})


def test_a_curse_machine_is_read_at_4b00_and_not_4900():
    """The whole of #29 in one assertion. `$4900` is Pool of Radiance's, and
    reading it on Curse is not an error -- it is a party made of whatever the
    engine happens to keep there."""
    machine = curse_machine()
    snap = live.read_snapshot(machine, game=CURSE)
    assert machine.reads == [(0x4B00, 0x1D00)]
    assert snap is not None
    assert [c.name for c in snap.characters] == ["BRUTUS"]


def test_the_same_machine_read_at_pool_of_radiances_addresses_lies():
    """And what it cost before the fix, which is the part worth pinning:
    reading `$4900` on a Curse machine does **not** refuse. `$4900`-`$64FF`
    overlaps `$4B00`'s payload two pages in, so the whole tab decodes -- a
    party, a square, an area name -- and every one of them is wrong."""
    wrong = live.read_snapshot(curse_machine())
    right = live.read_snapshot(curse_machine(), game=CURSE)
    assert wrong is not None and right is not None
    assert (wrong.area_file, wrong.x, wrong.y) != (right.area_file,
                                                   right.x, right.y)
    assert [c.slot for c in wrong.characters] != [c.slot
                                                  for c in right.characters]


def test_curses_roster_comes_from_6700_inside_the_payload():
    """One read, not two: a title that folds the roster into the payload has
    the page in hand already, and asking for it again is a round trip for bytes
    we have. The slice has to be the right one, which is what this checks."""
    save0, roster = captured()
    machine = curse_machine()
    assert CURSE.roster_base == 0x6700
    payload, page = live.read_blocks(machine, CURSE)
    assert payload == save0 + roster
    assert page == roster
    assert machine.reads == [(0x4B00, 0x1D00)]


def test_the_effect_arrays_follow_the_save_image():
    """They are payload offsets, so they move with the base and need no table
    of their own -- `$4900`/`$4940`/`$4980`/`$4B80` in Pool of Radiance are the
    same four offsets off `$4B00` in Curse."""
    save0, roster = captured()
    raw = bytearray(save0)
    raw[live.EFFECT_ID_OFFSET] = 7
    raw[live.EFFECT_OWNER_OFFSET] = live.PARTY_WIDE
    machine = MemoryTarget({CURSE.save_load_address: bytes(raw) + roster})
    snap = live.read_snapshot(machine, game=CURSE)
    assert [e.id for e in snap.party_effects] == [7]


def test_the_memory_fallback_reads_the_engines_own_triple():
    """`$C04B`, measured on three titles and on no others. Pool of Radiance's
    `$49C0` is the save image's copy and lags a move, so it is not what the
    fallback reads on any title now."""
    for game in (games.POOL_OF_RADIANCE, CURSE,
                 games.SECRET_OF_THE_SILVER_BLADES):
        assert game.live_position == 0xC04B
        machine = MemoryTarget({0xD011: bytes([0x1B]), 0xD018: bytes([0x30]),
                                0xDD00: bytes([0x00]),
                                0xC04B: bytes([6, 11, 2]),
                                game.clock_base: bytes([4, 2, 9])})
        fix = party_fix(machine.read, game)
        assert (fix.x, fix.y, fix.facing, fix.source) == (6, 11, 2, "memory")
        assert fix.clock == 9 * 60 + 24


def test_a_title_whose_live_triple_is_unmeasured_gets_no_fallback():
    """Champions of Krynn has never been run under a monitor, so its
    `live_position` is None and the fallback refuses. `$C04B` is a measurement
    of three other games, not a family constant, and answering with it would
    give a square rather than an error."""
    assert CHAMPIONS.live_position is None
    machine = MemoryTarget({0xD011: bytes([0x1B]), 0xD018: bytes([0x30]),
                            0xDD00: bytes([0x00]),
                            0xC04B: bytes([6, 11, 2])})
    assert party_fix(machine.read, CHAMPIONS) is None
    assert 0xC04B not in [addr for addr, _ in machine.reads]


def test_the_combat_numbers_come_from_the_roster_not_the_record():
    """A save slot holds 256 bytes; AC, THAC0 and current hit points are past
    them. Reading them from the record gives AC 60 -- plausible and wrong."""
    from goldbox.savegame import SaveGame0
    save0, save1 = captured()
    record = SaveGame0.from_bytes(save0).characters[0].record
    with pytest.raises(FieldNotStored):
        record.get("armour_class")
    assert live.snapshot_from_bytes(save0, save1).characters[0].armour_class == 9


# --- effects ---------------------------------------------------------------

def with_effect(slot=0, id=1, owner=0, duration=0x43, magnitude=2):
    save0, save1 = captured()
    raw = bytearray(save0)
    for at, value in ((live.EFFECT_ID_OFFSET, id),
                      (live.EFFECT_OWNER_OFFSET, owner),
                      (live.EFFECT_DURATION_OFFSET, duration),
                      (live.EFFECT_MAGNITUDE_OFFSET, magnitude)):
        raw[at + slot] = value
    return bytes(raw), save1


def test_an_effect_that_has_expired_is_not_shown():
    """**Expiry clears only the id.** The other three arrays keep their values,
    so anything filtering on duration shows effects that ended hours ago."""
    expired = live.snapshot_from_bytes(*with_effect(id=0, duration=0x43))
    assert expired.effects == ()
    running = live.snapshot_from_bytes(*with_effect(id=27))
    assert [e.id for e in running.effects] == [27]


def test_an_effect_knows_whose_it_is():
    party = live.snapshot_from_bytes(*with_effect(owner=live.PARTY_WIDE))
    assert party.party_effects and not party.monster_effects
    monster = live.snapshot_from_bytes(*with_effect(owner=9))
    assert monster.monster_effects and not monster.party_effects
    mine = live.snapshot_from_bytes(*with_effect(owner=0))
    assert mine.characters[0].effects and not mine.party_effects


def test_an_effect_shows_its_number_because_nothing_names_it():
    """There is no id-to-name table in the project. A number is visibly
    unknown; a guessed name would not be."""
    effect = live.Effect(slot=0, id=27, owner=0, duration=0xC5, magnitude=3)
    assert effect.label == "effect 27"
    assert effect.remaining == 5 and effect.unit == 3
    assert "not decoded" in effect.detail


# --- the cards --------------------------------------------------------------

def test_a_wounded_character_is_coloured_and_a_whole_one_is_not():
    from automap.panel import DANGER, HURT, WELL, hp_colour
    assert hp_colour(1.0) == WELL
    assert hp_colour(5 / 7) == HURT            # docs/100-live-view.md's example
    assert hp_colour(1 / 7) == DANGER


def test_the_hit_point_bands_keep_their_boundaries():
    """Pinned because a `<=` turned back into a `<` is invisible in the panel
    and changes the colour of every bar sitting exactly on a boundary."""
    from automap.panel import DANGER, HURT, WELL, hp_colour
    assert hp_colour(0.7500001) == WELL
    assert hp_colour(0.75) == HURT             # the boundary is hurt, not well
    assert hp_colour(0.2500001) == HURT
    assert hp_colour(0.25) == DANGER           # and this one is danger, not hurt
    assert hp_colour(0.0) == DANGER
    assert [hp_colour(n / 8) for n in (8, 7, 6, 5, 4, 3, 2, 1, 0)] == [
        WELL, WELL, HURT, HURT, HURT, HURT, DANGER, DANGER, DANGER]


def test_the_hurt_colour_is_a_yellow_and_not_the_old_brown():
    """`#c07d18` read as brown against the card. The replacement has to stay
    light enough to carry the black numbers drawn across it."""
    from automap.panel import DANGER, HURT, INK, WELL

    def luminance(c):
        def channel(v):
            v /= 255
            return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
        r, g, b = (channel(v) for v in (c.red(), c.green(), c.blue()))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    def contrast(a, b):
        hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
        return (hi + 0.05) / (lo + 0.05)

    assert 45 <= HURT.hue() <= 62                  # yellow, not the amber's 36
    assert luminance(HURT) > 0.45                  # the amber's was 0.26
    assert contrast(HURT, INK) >= 4.5              # the numbers over the fill
    assert contrast(WELL, INK) >= 3
    assert contrast(DANGER, INK) >= 3


def test_a_card_at_a_class_ceiling_says_maximum(app):
    """`levels.progress` returns None at the ceiling -- a fighter stops at 8 --
    and an empty bar there would read as the opposite of what it means."""
    from automap.panel import CharacterCard
    ceiling = live.ClassProgress("fighter", 8, 130000, None, None)
    card = CharacterCard(make_root(), 0)
    card.show_character(live.Character(
        slot=0, name="MAGNUS", classes=(ceiling,), level=8, armour_class=2,
        thac0=13, hp=60, hp_max=60, experience=130000))
    assert card.xp[0].text == "fighter maximum"
    assert card.xp[0].fraction == 1.0


def test_the_strip_says_square_dash_until_the_party_has_been_located(app):
    """Before the first fix, `(0,0) facing N` is not where the party is -- it
    is `AutomapState`'s defaults -- so the strip says it does not know.

    **This test used to end in a bare call to `show_state` with a real
    snapshot and no assertion after it**, and that silence is what let
    `#142 (The party effects line is computed every poll and shown nowhere)`
    ship: had the line asserted anything about the effects widget it would
    have raised `AttributeError` on `None` the moment `strip_effects` was
    deleted from the form. The call has become the two assertions below.
    """
    from automap.panel import BottomStrip
    strip = BottomStrip(make_root())
    state = AutomapState()
    state.area = "GEO00"
    strip.show_state(state, None)
    assert strip.where.text() == "square --"     # no fix yet is not (0,0)
    assert strip.effects.names == ()             # and nothing is readable yet
    state.source, state.x, state.y = "status", 3, 14
    strip.show_state(state, None)
    assert strip.where.text() == "(3,14) facing N"
    strip.show_state(state, live.snapshot_from_bytes(*captured()))
    assert strip.where.text() == "(3,14) facing N"
    assert strip.effects.names == ()             # BRUTUS has no party spell up


# --- the party effects row (#142) -------------------------------------------
#
# **No save this project holds carries a party-wide effect.** Checked
# 2026-08-31: the only effect in any fixture is id 73 with owner `0x00`, which
# is a character and not the party. So every test below writes its own effect
# table over the captured machine rather than expecting a fixture to carry
# one, and the badge set it draws is graded from the spell table rather than
# from anything anybody has watched land.

def party_snapshot(*effects):
    """The captured machine with `(id, owner)` written into the effect table.

    Every slot is cleared first, so a test's table is exactly what it says and
    not what it says on top of whatever the fixture was already holding.
    """
    save0, save1 = captured()
    raw = bytearray(save0)
    for slot in range(live.EFFECT_SLOTS):
        raw[live.EFFECT_ID_OFFSET + slot] = 0
        raw[live.EFFECT_OWNER_OFFSET + slot] = 0
    for slot, (eid, owner) in enumerate(effects):
        raw[live.EFFECT_ID_OFFSET + slot] = eid
        raw[live.EFFECT_OWNER_OFFSET + slot] = owner
    return live.snapshot_from_bytes(bytes(raw), save1)


def shown(app, snap):
    """The strip after one poll: its icon names and its tooltip."""
    from automap.panel import BottomStrip
    strip = BottomStrip(make_root())
    state = AutomapState()
    state.area = "GEO00"
    strip.show_state(state, snap)
    return strip.effects.names, strip.effects.toolTip()


def test_a_spell_on_the_whole_party_puts_its_icon_on_the_strip(app):
    """What a player does: your cleric casts Bless before a fight, and one
    icon appears above the coordinates with `Bless` in its tooltip.

    Before this, nothing appeared at all -- the line was worked out five times
    a second and written into a widget that had been deleted from the form.
    """
    names, tip = shown(app, party_snapshot((1, live.PARTY_WIDE)))
    assert names == ("healing-shield",)
    assert tip == "Bless"


def test_prayer_and_bless_share_one_icon_and_the_tooltip_says_both(app):
    """Donald's ruling on `#142 (The party effects line is computed every poll
    and shown nowhere)`: Prayer joins *blessed* rather than taking a glyph of
    its own, because to a player the two are the same idea. Two spells, one
    picture, and the tooltip is what separates them."""
    names, tip = shown(app, party_snapshot((1, live.PARTY_WIDE),
                                           (49, live.PARTY_WIDE)))
    assert names == ("healing-shield",)
    assert tip.splitlines() == ["Bless", "Prayer"]


def test_the_two_new_glyphs_draw_silence_and_slowed(app):
    """`mute` and `snail`, Donald's choices, and the only two effects on the
    party line that did not already have a badge from
    `#4 (Condition badges on the roster card)`."""
    names, tip = shown(app, party_snapshot((21, live.PARTY_WIDE),
                                           (42, live.PARTY_WIDE)))
    assert names == ("mute", "snail")
    assert tip.splitlines() == ["Silence, 15' Radius", "Slowed"]


def test_a_party_with_nothing_running_draws_nothing_at_all(app):
    """The blank state is the one a player sees most, and the old shape's
    fault was that it took up room saying so. No icons, no tooltip, and no
    line reading `party effects: none`."""
    names, tip = shown(app, party_snapshot((1, 0), (39, 3)))
    assert names == () and tip == ""


def test_a_spell_on_one_character_stays_off_the_party_line(app):
    """The strip is the party's row. A spell on a single character is that
    character's card's business and must not appear twice."""
    names, _ = shown(app, party_snapshot((39, 0)))
    assert names == ()


def test_the_strip_draws_the_same_icon_as_the_card_for_the_same_spell(app):
    """*"The party line and a roster card use the same icon for the same
    spell"* -- the difference is only whether it landed on one character or on
    everybody, and Bless being one picture on a card and another on the strip
    would be a nonsense.

    Pinned structurally rather than by listing pairs: both go through
    `live.badges`, so a regrouping cannot move one without the other."""
    from automap.panel import CharacterCard
    spells = (1, 8, 21, 25, 38, 39, 42, 45, 49)
    card = CharacterCard(make_root(), 0)
    card.show_character(live.Character(
        slot=0, name="BRUTUS", classes=(), level=1, armour_class=9, thac0=18,
        hp=11, hp_max=11, experience=0,
        effects=tuple(live.Effect(slot=i, id=n, owner=0, duration=8,
                                  magnitude=0)
                      for i, n in enumerate(spells))))
    names, _ = shown(app, party_snapshot(*((n, live.PARTY_WIDE)
                                           for n in spells)))
    assert names == card.conditions.names
    assert len(names) == len(live.CONDITION_BADGES)


def test_effects_on_monsters_are_counted_in_the_tooltip_and_never_drawn(app):
    """They belong to whatever is being fought and the combat view is where
    they will mean something. Counting them at least says the effect table is
    not empty; drawing them on the party's own row would say something false.
    """
    names, tip = shown(app, party_snapshot((1, live.PARTY_WIDE),
                                           (39, 9), (42, 10)))
    assert names == ("healing-shield",)
    assert tip.splitlines() == ["Bless", "2 effects on monsters"]
    _, one = shown(app, party_snapshot((1, live.PARTY_WIDE), (39, 9)))
    assert one.splitlines()[-1] == "1 effect on monsters"


def test_a_party_effect_no_badge_covers_is_reported_rather_than_dropped(
        app, caplog):
    """The badge set is graded from the spell table and nothing has been
    watched landing on a party, so it can be a glyph short. An id that turns
    up with no badge is drawn nowhere -- there is no picture for it and
    inventing one is not ours to do -- so it goes to the debug log instead of
    vanishing, once per id rather than five times a second."""
    import logging

    from automap.panel import BottomStrip
    strip = BottomStrip(make_root())
    state = AutomapState()
    state.area, state.source = "GEO00", "status"
    snap = party_snapshot((64, live.PARTY_WIDE))
    with caplog.at_level(logging.WARNING, logger="wish.automap.panel"):
        for _poll in range(5):
            strip.show_state(state, snap)
    assert strip.effects.names == () and strip.effects.toolTip() == ""
    said = [r for r in caplog.records if "effect 64" in r.getMessage()]
    assert len(said) == 1, [r.getMessage() for r in said]


# --- a widget the code depends on and cannot find (#142) ---------------------

def test_every_panel_finds_every_widget_it_wires(app, caplog):
    """The one that would have caught `#142 (The party effects line is computed
    every poll and shown nowhere)` the day it was made.

    `BottomStrip` looked up a label called `strip_effects` that had been
    deleted from the form, got `None`, and carried on computing the party's
    effects five times a second and writing them behind a guard that was never
    true. Every panel in `automap/panel.py` is wired the same way, so this asks
    all of them at once and fails on the first name the form no longer has.
    """
    import logging

    from automap import panel

    class NoSettings:
        automap_columns = None

        def column_widths(self, _count):
            return None

    root = make_root()
    with caplog.at_level(logging.WARNING, logger="wish.automap.panel"):
        strip = panel.BottomStrip(root)
        splitter = panel.ColumnSplitter(root, NoSettings())
        panel.NotesPanel(root)
        panel.MessagesPanel(root)
        roster = panel.RosterPanel(root)
    assert caplog.text == "", caplog.text
    assert strip.effects is not None and strip.where is not None
    assert splitter.splitter is not None
    assert all(card.conditions is not None for card in roster.cards)


def test_a_widget_the_form_does_not_have_is_named_in_the_debug_log(app, caplog):
    """And the other direction, because a guard that cannot fail is not a
    guard. Built against an empty window, every lookup misses, and each one
    says which name it was looking for -- in the debug log and not in a dialog:
    a missing widget is a fault in the build, not something the player did."""
    import logging

    from PyQt6.QtWidgets import QMainWindow

    from automap.panel import BottomStrip
    with caplog.at_level(logging.WARNING, logger="wish.automap.panel"):
        strip = BottomStrip(QMainWindow())
    assert strip.effects is None
    assert "strip_effects" in caplog.text
    assert "strip_where" in caplog.text
    strip.show_state(AutomapState(), None)      # and does not raise


# --- attaching --------------------------------------------------------------

def test_a_socket_that_accepts_and_never_answers_is_busy_not_absent(monkeypatch):
    """The distinguishing signal, exactly: with nothing running the connect is
    refused; with another client holding the monitor it succeeds and is then
    never served. VICE serves one connection and ignores the second in
    silence, so without this the map says "waiting for a game" about a game
    that is running."""
    import socket

    from automap.target import MonitorBusy, NotConnected, ViceTarget

    monkeypatch.setattr(ViceTarget, "GREETING", 0.15)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        with pytest.raises(MonitorBusy) as busy:
            ViceTarget(host="127.0.0.1", port=port, timeout=0.5)
        assert "something else is attached" in str(busy.value)
        assert isinstance(busy.value, NotConnected)      # callers still retry
    finally:
        listener.close()

    # Nothing listening at all. Refused on Linux, and on Windows the SYN is
    # dropped so it times out instead -- neither is somebody else holding it.
    with pytest.raises(NotConnected) as gone:
        ViceTarget(host="127.0.0.1", port=port, timeout=0.5)
    assert not isinstance(gone.value, MonitorBusy)


def test_a_connect_that_times_out_is_absent_not_busy(monkeypatch):
    """The half of the distinction the platform gets a vote on.

    Reading *any* timeout as busy assumes that with nothing listening the
    connect is refused at once. That is true on Linux and false on Windows,
    where a filtered port is silently dropped and the connect times out -- so
    wish told a Windows user with no emulator running that something else was
    attached to it. Only the unanswered ping means busy.
    """
    from automap.target import MonitorBusy, NotConnected, ViceTarget
    from automap.vice import Monitor

    def never_answers(self):
        raise TimeoutError("timed out")

    monkeypatch.setattr(Monitor, "__enter__", never_answers)
    with pytest.raises(NotConnected) as gone:
        ViceTarget(host="127.0.0.1", port=6502, timeout=0.1)
    assert not isinstance(gone.value, MonitorBusy)


def test_the_busy_message_names_a_command_this_platform_has(monkeypatch):
    """`ss` is Linux-only, and it was in the message a Windows user is most
    likely to see."""
    import automap.target as target

    monkeypatch.setattr(target.sys, "platform", "win32")
    assert target.who_holds_hint() == "`netstat -ano | findstr 6502` names it"
    monkeypatch.setattr(target.sys, "platform", "linux")
    assert target.who_holds_hint() == "`ss -tnp | grep 6502` names it"


# --- the tab ----------------------------------------------------------------

def make_window(app, tmp_path, monkeypatch, target, maps=None, area=None):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from PyQt6.QtWidgets import QMainWindow

    from automap.window import AutomapBinding
    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    mapper = Automapper(target, maps or {}, area=area)
    return AutomapBinding(root, mapper, drive=False)


def test_the_party_is_read_once_every_five_ticks(app, tmp_path, monkeypatch):
    """Each read of a live machine costs the emulation ~14.3 ms of extra time,
    so the party is not read as often as the map fix."""
    save0, save1 = captured()
    machine = MemoryTarget({0x4900: save0, 0x8300: save1})
    window = make_window(app, tmp_path, monkeypatch, machine)
    for _ in range(10):
        window.tick()
    party_reads = [r for r in machine.reads if r[0] in (0x4900, 0x8300)]
    assert len(party_reads) == 2 * (10 // window.LIVE_EVERY)


def _test_the_tab_shows_the_party_beside_the_map(app, tmp_path, monkeypatch):
    save0, save1 = captured()
    window = make_window(app, tmp_path, monkeypatch,
                         MemoryTarget({0x4900: save0, 0x8300: save1}))
    for _ in range(window.LIVE_EVERY):
        window.tick()
    assert window.snapshot is not None
    assert window.roster.cards[0].name.text() == "BRUTUS"
    # Roster left, map centre, the reading panels right, the actions under the
    # map, the strip along the bottom. The map is the stack of two canvases --
    # the area map and the combat map.
    grid = window.centralWidget().layout()
    assert grid.getItemPosition(grid.indexOf(window.roster))[:2] == (0, 0)
    assert grid.getItemPosition(grid.indexOf(window.map_column))[:2] == (0, 1)
    assert grid.getItemPosition(grid.indexOf(window.side))[:2] == (0, 2)
    assert grid.getItemPosition(grid.indexOf(window.strip))[0] == 1
    # The actions are under the map, in its column, not in a row of their own.
    column = window.map_column.layout()
    assert column.indexOf(window.stack) < column.indexOf(window.actions_bar)
    # The panels' column is capped, and what the cap leaves over goes to the
    # map's column, which centres the map in it rather than leaving the slack
    # against one edge.
    assert window.side.maximumWidth() == window.SIDE_WIDTH
    assert grid.columnStretch(2) and grid.columnStretch(1)
    assert window.stack.currentWidget() is window.canvas


def test_a_machine_with_no_party_holds_the_last_good_snapshot(app, tmp_path,
                                                              monkeypatch):
    """A menu, a disk load or the title screen. Blanking the cards would make
    them flicker every time the game opened a menu."""
    save0, save1 = captured()
    machine = MemoryTarget({0x4900: save0, 0x8300: save1})
    window = make_window(app, tmp_path, monkeypatch, machine)
    for _ in range(window.LIVE_EVERY):
        window.tick()
    machine.memory[0x4900] = bytes(0x1C00)
    for _ in range(window.LIVE_EVERY):
        window.tick()
    assert window.snapshot is not None                  # still the last good one
    assert window.roster.cards[0].name.text() == "BRUTUS"
    assert "not readable" in window.roster.heading.text()


def test_the_session_does_not_attach_until_a_tab_wants_live_data(monkeypatch):
    """VICE serves one binary-monitor connection and ignores a second, so an
    idle window must not hold it. Opening the editor tab beside a running
    experiment used to steal the emulator from it."""
    from wish import session as session_mod

    attempts = []

    def never(*a, **kw):
        attempts.append(1)
        return True

    s = session_mod.Session()
    monkeypatch.setattr(s, "attach", never)
    s.reader = None
    s.poll()
    assert attempts == [], "attached with nothing asking for live data"

    s.reader = lambda target: None
    s.target = object()
    s.poll()
    assert attempts == [], "already attached; should not attach again"


# --- notes ------------------------------------------------------------------

from PyQt6.QtWidgets import QPushButton  # noqa: E402

from automap import notes as notemod  # noqa: E402
from ui import icons  # noqa: E402


def _area(tmp_path, monkeypatch, area="GEO14") -> AutomapState:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    state = AutomapState()
    state.area = area
    return state


# --- and one title's notes are not another's (#30) --------------------------

def test_a_note_on_one_titles_geo15_is_absent_from_anothers(tmp_path,
                                                            monkeypatch):
    """`GEO15` is Sokol Keep in Pool of Radiance and somewhere else entirely in
    Curse. Before the path carried the title, a note pinned in one turned up on
    the other's square, and the explored squares merged with it."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    pool = AutomapState(title="Pool of Radiance")
    pool.area = "GEO15"
    pool.add_note(4, 7, Note("dead elf", "person"))
    pool.exploration.visit(4, 7)
    pool.save_notes()

    curse = AutomapState(title="Curse of the Azure Bonds")
    curse.area = "GEO15"
    curse.load_notes()
    assert curse.notes_at(4, 7) == []
    assert (4, 7) not in curse.exploration
    assert curse.notes_path() != pool.notes_path()

    # and the one that was written is still there, under its own title
    again = AutomapState(title="Pool of Radiance")
    again.area = "GEO15"
    again.load_notes()
    assert [n.text for n in again.notes_at(4, 7)] == ["dead elf"]

    # every title we claim, not just the two above: three distinct paths for
    # one map id, so nothing any of them writes can reach the others.
    paths = set()
    for game in (games.POOL_OF_RADIANCE, CURSE,
                 games.SECRET_OF_THE_SILVER_BLADES):
        state = AutomapState(title=game.title)
        state.area = "GEO15"
        paths.add(state.notes_path())
    assert len(paths) == 3


def test_a_flat_notes_file_is_still_readable_after_the_split(tmp_path,
                                                             monkeypatch):
    """Everything written before the title was in the path is Pool of
    Radiance's -- it is the only title anyone has mapped -- so it is moved
    there rather than orphaned."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    flat = state_data_dir() / "GEO15.json"
    flat.parent.mkdir(parents=True, exist_ok=True)
    flat.write_text(json.dumps({"notes": {"4,7": [{"text": "dead elf",
                                                   "type": "person"}]},
                                "seen": ["4,7"]}), encoding="utf-8")

    state = AutomapState(title="Pool of Radiance")
    state.area = "GEO15"
    state.load_notes()
    assert [n.text for n in state.notes_at(4, 7)] == ["dead elf"]
    assert (4, 7) in state.exploration
    assert not flat.exists()
    assert state.notes_path().exists()


def test_a_notes_file_that_cannot_be_attributed_is_left_where_it_is(
        tmp_path, monkeypatch):
    """Losing somebody's notes is worse than the bug, so a flat file is moved
    only when its stem is one of the twenty-nine maps Pool of Radiance actually
    ships. `GEO08` is not one of them and neither is `unknown`."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    root = state_data_dir()
    root.mkdir(parents=True, exist_ok=True)
    for name in ("GEO08.json", "unknown.json"):
        (root / name).write_text('{"notes": {}, "seen": []}', encoding="utf-8")
    (root / "GEO15.json").write_text('{"notes": {}, "seen": []}',
                                     encoding="utf-8")

    moved = migrate_flat_notes()
    assert [path.name for path in moved] == ["GEO15.json"]
    assert (root / "GEO08.json").exists()
    assert (root / "unknown.json").exists()


def test_a_migration_never_overwrites_what_is_already_there(tmp_path,
                                                            monkeypatch):
    """A half-migrated directory must not lose the half that already moved."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    root = state_data_dir()
    already = root / title_dir("Pool of Radiance")
    already.mkdir(parents=True, exist_ok=True)
    (already / "GEO15.json").write_text('{"notes": {}, "seen": ["1,1"]}',
                                        encoding="utf-8")
    (root / "GEO15.json").write_text('{"notes": {}, "seen": ["9,9"]}',
                                     encoding="utf-8")

    assert migrate_flat_notes() == []
    assert json.loads((already / "GEO15.json").read_text())["seen"] == ["1,1"]
    assert (root / "GEO15.json").exists()


def test_an_old_format_note_loads_as_one_note_and_is_rewritten(tmp_path,
                                                               monkeypatch):
    """`"6,2": "some text"` was the whole format once. Nobody's notes get eaten
    by an upgrade."""
    state = _area(tmp_path, monkeypatch)
    path = state.notes_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"notes": {"6,2": "arena master"},
                                "seen": ["6,2"]}))
    state.load_notes()
    kept = state.notes_at(6, 2)
    assert [(n.text, n.type) for n in kept] == [("arena master", "note")]

    state.save_notes()
    payload = json.loads(path.read_text())
    assert payload["notes"]["6,2"] == [{"type": "note", "text": "arena master"}]


def test_a_square_holds_more_than_one_note(tmp_path, monkeypatch):
    """A fight and the treasure it guards are two notes, not one string."""
    state = _area(tmp_path, monkeypatch)
    state.add_note(6, 2, Note("dueling pairs", "encounter", "2026-08-20T12:00:00"))
    state.add_note(6, 2, Note("needs a thief", "treasure"))
    state.save_notes()

    again = _area(tmp_path, monkeypatch)
    again.load_notes()
    assert [(n.type, n.text) for n in again.notes_at(6, 2)] == [
        ("encounter", "dueling pairs"), ("treasure", "needs a thief")]
    assert again.notes_at(6, 2)[0].at == "2026-08-20T12:00:00"


def test_an_unknown_type_keeps_its_name_and_draws_the_neutral_marker():
    """A removed or renamed type must not quietly become a different one."""
    kind = notemod.type_for("wyvern")
    assert kind.name == "wyvern" and kind.icon == "position-marker"
    assert Note("here", "wyvern").icon == "position-marker"


def test_junk_in_a_notes_file_costs_only_the_junk(tmp_path, monkeypatch):
    """The file is hand-editable by design, so half of one beats none."""
    state = _area(tmp_path, monkeypatch)
    path = state.notes_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"notes": {"1,1": 42, "nowhere": ["x"],
                                          "2,2": [{"type": "locked"}]}}))
    state.load_notes()
    assert list(state.notes) == [(2, 2)]


def _test_forgetting_squares_keeps_the_notes(tmp_path, monkeypatch):
    """`--forget ALL` clears exploration and leaves every note untouched."""
    from wish.window import forget
    state = _area(tmp_path, monkeypatch)
    state.exploration.visit(3, 3)
    state.add_note(6, 2, Note("arena master", "person"))
    state.save_notes()

    forget("ALL")
    again = _area(tmp_path, monkeypatch)
    again.load_notes()
    assert len(again.exploration) == 0
    assert [n.text for n in again.notes_at(6, 2)] == ["arena master"]


# --- drawing them -----------------------------------------------------------

def test_every_icon_parses():
    """The icons are path data, not a font, so a typo fails here rather than as
    a blank square on somebody's map."""
    for name in icons.ICONS:
        assert icons.commands(name), name


def test_every_note_type_draws():
    """Every name the program asks for by string is a name one of the two
    tables has -- path data, or a character. The roster's class icons were
    removed: they carried little at 13px and are not missed."""
    for name in [t.icon for t in notemod.TYPES]:
        assert name in icons.NAMES, name
        if not icons.is_text(name):
            assert icons.commands(name), name


def test_every_note_kind_draws_its_own_picture_and_nobody_elses():
    """Twenty-five wordless buttons only work if no two are the same picture,
    and the picker shows no words at all -- two kinds sharing a glyph would be
    two buttons a person cannot tell apart, with only a hover between them.

    It also catches the copy-and-paste that adds a kind and forgets to change
    the icon, which is the way this would actually go wrong.
    """
    seen: dict[str, str] = {}
    for kind in notemod.TYPES:
        assert kind.icon in icons.NAMES, kind.name
        assert kind.icon not in seen, \
            f"{kind.name} draws {kind.icon}, which is already {seen[kind.icon]}"
        seen[kind.icon] = kind.name
    assert len(notemod.TYPES) == 25
    assert len(notemod.BY_NAME) == 25          # and no two share a file name


def test_every_note_kind_is_credited_to_the_artist_who_drew_it():
    """CC BY 3.0 asks for attribution and nothing else, so a kind drawing a
    glyph `ARTISTS` does not name is the whole of a licence breach.
    `tests/test_licenses.py` checks the generated file against `ARTISTS`; this
    checks `ARTISTS` against what the notes actually draw."""
    for kind in notemod.TYPES:
        assert icons.ARTISTS.get(kind.icon), kind.icon


def test_every_note_description_opens_with_a_capital():
    """Donald: *"Make sure all descriptions start with a capital letter. This
    is an problem across all AI text."* The tooltip reads
    `Locked - A door that beat you`, so a lower-case description is visible
    wherever a hover is."""
    for kind in notemod.TYPES:
        assert kind.hint[:1].isupper(), f"{kind.name}: {kind.hint!r}"
        assert kind.label[:1].isupper(), kind.label


def test_the_nine_kinds_that_existed_before_the_sixteen_still_mean_what_they_meant():
    """**The test that matters most here**: somebody's own map annotations.

    A notes file written by any earlier build stores `"type": "locked"` as a
    string, and after sixteen kinds joined the table that string still has to
    find the padlock -- not the kind that happens to sit where `locked` used
    to. The picker was reordered when the grid arrived, so this is not
    hypothetical: position moved and meaning must not have.
    """
    was = {"encounter": ("Encounter", "crossed-sabres"),
           "treasure": ("Treasure", "open-treasure-chest"),
           "person": ("Person", "person"),
           "exit": ("Exit", "exit-door"),
           "locked": ("Locked", "plain-padlock"),
           "stairs": ("Stairs", "stairs"),
           "danger": ("Danger", "hazard-sign"),
           "note": ("Note", "position-marker"),
           "done": ("Done", "check-mark")}
    for name, (label, icon) in was.items():
        kind = notemod.type_for(name)
        assert (kind.label, kind.icon) == (label, icon), name
    assert notemod.DEFAULT == "note"


def test_an_old_notes_file_still_loads_after_the_sixteen_arrived(tmp_path,
                                                                monkeypatch):
    """Both shapes an old file comes in -- the bare string that predates
    types, and a typed note -- read back as what they were. Adding kinds is
    supposed to cost a saved file nothing, and this is where that is checked
    rather than assumed."""
    state = _area(tmp_path, monkeypatch)
    state.notes_path().parent.mkdir(parents=True, exist_ok=True)
    state.notes_path().write_text(json.dumps(
        {"notes": {"6,2": "arena master",
                   "1,1": [{"type": "locked", "text": "the north door"}],
                   "3,3": [{"type": "wyvern", "text": "not a kind we know"}]},
         "seen": []}), encoding="utf-8")
    state.load_notes()
    assert [(n.type, n.text) for n in state.notes_at(6, 2)] == \
        [("note", "arena master")]
    kept = state.notes_at(1, 1)[0]
    assert (kept.type, kept.icon, kept.label) == \
        ("locked", "plain-padlock", "Locked - the north door")
    # A name no version knows keeps its own name and gets the neutral marker,
    # which is the whole reason `type` is a string.
    stranger = state.notes_at(3, 3)[0]
    assert (stranger.type, stranger.icon) == ("wyvern", "position-marker")


def test_a_note_of_a_new_kind_is_still_that_kind_when_it_is_opened_again(
        tmp_path, monkeypatch):
    """Every one of the sixteen, written out and read back. A kind that does
    not survive a save is a kind that quietly becomes another one, and the
    only way anybody would find out is by looking at their own map."""
    new = ("point-of-interest", "warrior", "smith", "silversmith", "jeweler",
           "magic-items", "inn", "tavern", "trap", "orcs", "goblins",
           "dragon", "undead", "cleric", "thief", "wizard")
    assert len(new) == 16
    state = _area(tmp_path, monkeypatch)
    for n, name in enumerate(new):
        state.add_note(n, 0, Note(f"note {n}", name))
    state.save_notes()

    again = _area(tmp_path, monkeypatch)
    again.load_notes()
    for n, name in enumerate(new):
        note = again.notes_at(n, 0)[0]
        assert note.type == name
        assert note.icon == notemod.BY_NAME[name].icon
        assert note.icon in icons.GAME_ICONS


def test_the_encounter_and_treasure_notes_are_paths_now():
    """`crossed-sabres` and `open-treasure-chest` replaced the Encounter
    note's U+2694 font character and Font Awesome's `gem`, so `TEXT_GLYPHS`
    is empty and both note kinds draw from `GAME_ICONS` like every other
    kind -- see `docs/109-icon-choices.md`."""
    assert icons.TEXT_GLYPHS == {}
    assert notemod.BY_NAME["encounter"].icon == "crossed-sabres"
    assert notemod.BY_NAME["treasure"].icon == "open-treasure-chest"
    assert not icons.is_text("crossed-sabres")
    assert "crossed-sabres" in icons.GAME_ICONS
    assert "open-treasure-chest" in icons.GAME_ICONS


def test_the_two_icons_that_were_ours_are_gone():
    """`chest` and `swords` were drawn here because Font Awesome Free has no
    sword and a filled rectangle reads as terrain. Both were replaced --
    `open-treasure-chest` and `crossed-sabres` -- and an unused drawing left
    in the table is a thing a later note will pick up by accident."""
    assert "chest" not in icons.ICONS
    assert "swords" not in icons.ICONS


def test_no_icon_leaves_its_own_box():
    """`render.py` places a note by its box, not by its ink: an icon that
    overhangs lands on a wall. See `test_a_note_never_lands_on_a_wall`. The two
    sets have different boxes -- 640 for Font Awesome, 512 for game-icons.net
    -- so the question is asked of each icon's own.

    **`brass-eye` and `crossed-sabres` are excluded, and both are measured
    exceptions, not a loosened bound.** `extent()` bounds every cubic's
    control points, which is a safe over-estimate of the curve -- not the
    curve itself. `brass-eye`'s iris has a control point at x=-13.6 and one
    at x=523.0 in the 512 box; rendered (`ui.iconpaint.draw_icon` at 512px,
    non-white pixels), the actual ink is 19..489 by 19..488, comfortably
    inside, and it is never drawn as a map note -- only the editor's Preview
    button. `crossed-sabres` overshoots the same way, to x=-17.9 and
    x=518.0, and its rendered ink is 19..492 by 19..496 -- also comfortably
    inside, though it *is* drawn as the Encounter note; the module-level
    test named above covers the real wall-overlap question for it against
    GEO14, the densest map, and passes."""
    for name in icons.ICONS:
        if name in ("brass-eye", "crossed-sabres"):
            continue
        x0, y0, x1, y1 = icons.extent(name)
        unit = icons.box(name)
        assert 0 <= x0 and 0 <= y0 and x1 <= unit and y1 <= unit, \
            f"{name} is {x0},{y0}..{x1},{y1} in a {unit} box"


def test_ours_and_font_awesome_do_not_share_a_name():
    """`ICONS` merges the two dicts, so a repeated name would silently replace
    what the map draws -- and the licence line differs between them."""
    assert not set(icons.OURS) & set(icons.FONT_AWESOME)




def test_the_sheet_only_names_icons_that_exist():
    """`tools/iconsheet.py` is how a drawing gets judged; a renamed icon must
    break the build rather than the sheet."""
    import importlib.util

    path = pathlib.Path(__file__).resolve().parent.parent / "tools" \
        / "iconsheet.py"
    spec = importlib.util.spec_from_file_location("iconsheet", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    named = [name for _, items in module.SHEET for name, _, _ in items]
    assert named, "the sheet lists nothing"
    for name in named:
        assert name in icons.NAMES, name


def test_the_marker_keeps_the_counter_that_stops_it_blobbing():
    """`position-marker` is a solid silhouette with one hole, and the hole is
    what stops it blobbing at small sizes. That needs two subpaths and
    winding fill -- odd-even would fill the hole in."""
    from PyQt6.QtCore import Qt as _Qt

    from ui.iconpaint import painter_path
    assert sum(1 for c in icons.commands("position-marker")
               if c[0] == "M") == 2
    assert painter_path("position-marker").fillRule() == \
        _Qt.FillRule.WindingFill


def test_a_square_with_several_notes_draws_the_first_and_nothing_else():
    """A square holds one note, so there is no count to draw. An old file that
    holds several still loads: the first is the marker, and the rest are
    reachable from the right-click menu."""
    prims = list(note_primitives({(2, 3): [Note("a", "encounter"),
                                           Note("b", "treasure"),
                                           Note("c")]}))
    glyphs = [p for p in prims if isinstance(p, Glyph)]
    assert [g.name for g in glyphs] == ["crossed-sabres"]   # the first only
    assert not [p for p in prims if isinstance(p, Label)]


def test_a_note_and_the_party_marker_share_one_square_marker_on_top():
    """At 13 the note sat in a corner and the two never met. At `NOTE_SIZE` the
    note is most of the square, so on the square the party is standing on one
    of them is underneath -- and it is the note. Where the party is is the one
    thing on this map that must not be in doubt."""
    from automap import window as windowmod

    source = inspect.getsource(windowmod.MapCanvas)
    notes = source.index("note_primitives(st.notes")
    party = source.index("party_marker(st.x")
    assert notes < party, "the note is drawn over the party marker"


@game_disks
def test_a_note_never_lands_on_a_wall():
    """Checked on GEO14, the densest map we have: a note that hides a wall has
    made the map worse, and the map's job is the walls.

    **Every kind, on every square.** It used to fill the map with `danger`
    and prove one glyph, which was enough while eight of the nine were the
    same Font Awesome silhouette. `#166` brought sixteen more pictures, drawn
    by five different people, and one of those overhanging its box is exactly
    the fault this test exists for -- so the map is filled once per kind.
    """
    slums = Geo.from_bytes(game_file("GEO14"))
    walls = [p for p in map_primitives(slums) if isinstance(p, Line)]
    every = [{(x, y): [Note("x", kind.name)]
              for y in range(GRID) for x in range(GRID)}
             for kind in notemod.TYPES]
    for glyph in [g for square in every for g in note_primitives(square)]:
        x0, y0, x1, y1 = icons.extent(glyph.name)
        # `icons.box(name)`, not `icons.BOX`: game-icons.net glyphs are drawn
        # on a 512 canvas and Font Awesome's on a wider one. Every note kind
        # is a game-icons name now, so `icons.BOX` would make `scale` a fifth
        # too small, the box would come out narrower than what is drawn, and
        # a real wall overlap would go unnoticed. Found in review of #4, when
        # the two sets still shared this loop.
        scale = glyph.size / icons.box(glyph.name)
        box = (glyph.x + x0 * scale, glyph.y + y0 * scale,
               glyph.x + x1 * scale, glyph.y + y1 * scale)
        for wall in walls:
            # Every wall is axis-aligned, and 3px wide, so half of it lies
            # inside the cell. Grow the segment by that half before testing.
            lo_x, hi_x = sorted((wall.x1, wall.x2))
            lo_y, hi_y = sorted((wall.y1, wall.y2))
            overlaps = (box[0] < hi_x + 1.5 and box[2] > lo_x - 1.5
                        and box[1] < hi_y + 1.5 and box[3] > lo_y - 1.5)
            assert not overlaps, f"{glyph} over {wall}"


def test_a_note_is_drawn_through_the_fog(new_phlan):
    """A note is something you know. Hiding it because the square is fogged
    would be perverse."""
    marked = {(9, 9): [Note("locked, come back", "locked")]}
    svg = to_svg(new_phlan, visible=lambda x, y: False, notes=marked)
    assert icons.path_data("plain-padlock") in svg


def test_the_svg_export_carries_the_notes(new_phlan):
    svg = to_svg(new_phlan, notes={(1, 1): [Note("a", "person"),
                                            Note("b", "done")]})
    assert icons.path_data("person") in svg
    # The first note's icon and nothing else: no count, because a square
    # holds one note and there is nothing to count.
    assert 'text-anchor="end"' not in svg and ">2<" not in svg


# --- the roster's new lines -------------------------------------------------

def _character(**kw):
    fields = dict(slot=0, name="BRUTUS", classes=(), level=1, armour_class=9,
                  thac0=18, hp=11, hp_max=11, experience=0)
    fields.update(kw)
    return live.Character(**fields)


def test_a_card_shows_what_is_readied_and_nothing_else(app):
    """On the card itself, not only in the tooltip. What is in hand is what a
    player glances at mid-crawl, and a tooltip is not a glance."""
    from automap.panel import CharacterCard
    card = CharacterCard(make_root(), 0)
    card.show_character(_character(readied=("BANDED MAIL", "SHIELD", "LONG SWORD")))
    assert card.readied_items == ("BANDED MAIL", "SHIELD", "LONG SWORD")
    assert card.readied.text() == "BANDED MAIL, SHIELD, LONG SWORD"
    assert "BANDED MAIL, SHIELD, LONG SWORD" in card.frame.toolTip()


def test_a_character_with_nothing_readied_gets_a_blank_line(app):
    """The absence is the information, and the word "none" is not. The line
    stays, so the cards below it do not shift when a sword is put away."""
    from automap.panel import CharacterCard
    card = CharacterCard(make_root(), 0)
    card.show_character(_character(readied=("LONG SWORD",)))
    tall = card.frame.sizeHint().height()
    card.show_character(_character())
    assert card.readied.text() == ""
    assert card.frame.sizeHint().height() == tall


def test_a_long_readied_list_is_shortened_to_the_card_and_kept_whole(app):
    """More in hand than the card is wide. The label keeps the whole string --
    so nothing about the card's width is measured from item names off the
    player's disk (#41) -- and draws as much of it as the room allows."""
    from automap.panel import CharacterCard
    card = CharacterCard(make_root(), 0)
    items = tuple(f"BANDED MAIL +{n}" for n in range(6))
    card.show_character(_character(readied=items))
    card.readied.resize(card.readied.sizeHint().width() // 3,
                        card.readied.sizeHint().height())
    drawn = card.readied.elided_text()
    assert drawn.endswith("…")
    assert drawn != card.readied.text()
    metrics = card.readied.fontMetrics()
    assert metrics.horizontalAdvance(drawn) <= card.readied.contentsRect().width()
    # And nothing is lost: the frame's tooltip is what the label answers with,
    # because the label sets none of its own.
    assert card.readied.toolTip() == ""
    for item in items:
        assert item in card.frame.toolTip()


def test_the_readied_line_does_not_grow_with_the_ui_font(app):
    """Eight cards in a column that does not scroll, so a line that got taller
    with the UI font would put eight of that growth under the window (#77).

    The line asks for the same height at every font because its point size is
    set in `wish/window.ui` and so does not inherit the application's, and it
    asks the layout for nothing at all -- `ReadiedLabel.SHORT` is 0, which is
    what keeps it out of the window's floor entirely.
    """
    from PyQt6.QtGui import QFont

    from automap.panel import CharacterCard
    base = app.font()
    fonts = (0, 3, 6, 10)
    try:
        natural, floor = [], []
        for extra in fonts:
            bigger = QFont(base)
            bigger.setPointSizeF(base.pointSizeF() + extra)
            app.setFont(bigger)
            card = CharacterCard(make_root(), 0)
            card.show_character(_character(readied=("LONG SWORD",)))
            natural.append(card.readied.sizeHint().height())
            floor.append(card.readied.minimumSizeHint().height())
    finally:
        app.setFont(base)
    assert natural == [natural[0]] * len(fonts), (
        f"the readied line got taller with the UI font: "
        f"{dict(zip(fonts, natural))}")
    assert floor == [0] * len(fonts), (
        f"the readied line is holding the window open: "
        f"{dict(zip(fonts, floor))}")


def _eight_card_floor(app, extra: float, *, line: bool) -> int:
    """The window form's minimum height with all eight cards showing.

    `line` is the control: with it False every readied label is hidden, which
    is the same window without this feature in it.

    **Two Qt traps, both of which make the measurement lie.** A card is
    `visible=false` in `wish/window.ui` and is shown by `RosterPanel`; on a
    window that has never been shown, `QWidget.show()` on a card does not post
    the layout request that would tell its ancestors their cached minimums are
    stale, so every layout above it goes on answering the eight-hidden-cards
    number. `updateGeometry()` up the chain is what clears the cached
    `QWidgetItem` sizes. And `QLayout.invalidate()` alone is not enough --
    the cache that matters belongs to the item, not to the layout.
    """
    from PyQt6.QtGui import QFont

    from automap.panel import RosterPanel
    was = app.font()
    bigger = QFont(was)
    bigger.setPointSizeF(was.pointSizeF() + extra)
    app.setFont(bigger)
    try:
        root = make_root()
        roster = RosterPanel(root)
        classes = tuple(live.ClassProgress(name, 8, 100_000, 0.5, 200_000)
                        for name in ("magic-user", "cleric", "thief"))
        for slot, card in enumerate(roster.cards):
            card.show_character(_character(
                slot=slot, name="W" * 15, classes=classes, armour_class=-3,
                readied=("BANDED MAIL +1", "SHIELD +2", "LONG SWORD +3")))
            card.frame.show()
            card.readied.setVisible(line)
        widget = roster.cards[0].frame
        while widget is not None:
            widget.updateGeometry()
            widget = widget.parentWidget()
        return root.minimumSizeHint().height()
    finally:
        app.setFont(was)


def test_eight_readied_lines_cost_the_window_less_than_one_line(app):
    """The one a user would feel, and the reason `ReadiedLabel.SHORT` is 0.

    The roster column does not scroll, so with a full party of eight it is
    already the tallest thing on the automapper page and its height is the
    height the window cannot be made smaller than. Eight cards each insisting
    on a line of their own would be eight lines added to that floor.

    **What is asserted is that the eight lines cost less than one line**, not
    a pixel count: the numbers here are this machine's and the same assertion
    has to hold where the base font is smaller. What is left is the one pixel
    of layout spacing each card spends on the row, which is a constant in
    `wish/window.ui` rather than anything measured from a font -- so the cost
    is also the same at every UI font, which is the second assertion.

    Measured here, a party of eight three-class characters: the form's floor
    is 917 without the line and 925 with it -- a cost of 8 -- at every one of
    +0, +3, +6 and +10. Take the `SHORT` cap off and the floor is 1045 and the
    cost 128, which is eight whole lines and sixteen times what the cap leaves.
    """
    fonts = (0, 3, 6, 10)
    costs = [_eight_card_floor(app, extra, line=True)
             - _eight_card_floor(app, extra, line=False) for extra in fonts]
    seen = dict(zip(fonts, costs))
    from automap.panel import CharacterCard
    card = CharacterCard(make_root(), 0)
    card.show_character(_character(readied=("LONG SWORD",)))
    one_line = card.readied.sizeHint().height()
    assert max(costs) < one_line, (
        f"eight readied lines added more than one line's height to the "
        f"window's floor: {seen}, against a line of {one_line}")
    assert costs == [costs[0]] * len(fonts), (
        f"what the readied lines cost the window's floor moved with the UI "
        f"font: {seen}")


def test_readied_items_are_read_from_the_item_block():
    """The editor's inventory table shows exactly this; the card shows the
    readied half of it."""
    from goldbox.savegame import SaveGame0
    save = SaveGame0.from_prg((FIXTURES / "party6_after_combat.bin").read_bytes())
    names = live.item_names()
    if names is None:
        pytest.skip("needs the game disks")
    payload = save.to_bytes()
    assert live.readied(payload, 5, names) == ("BANDED MAIL", "SHIELD",
                                               "LONG SWORD")
    # MAGNUS carries a bow and arrows that are not in hand, and they are not
    # on the card.
    assert live.readied(payload, 4, names) == ("BANDED MAIL", "SHIELD",
                                               "LONG SWORD")


def test_without_a_game_disk_the_readied_line_is_blank_not_numbered():
    """Item names come off the disk. Word indices on a card would be worse
    than nothing."""
    from goldbox.savegame import SaveGame0
    save = SaveGame0.from_prg((FIXTURES / "party6_after_combat.bin").read_bytes())
    assert live.readied(save.to_bytes(), 5, None) == ()


def test_the_class_is_written_out_and_not_left_to_an_icon(app):
    """The roster's class icons were removed -- they carried little at 13px --
    so the text is the whole statement, and it is what a screen reader gets."""
    from automap.panel import CharacterCard
    card = CharacterCard(make_root(), 0)
    two = (live.ClassProgress("magic-user", 1, 0, 0.0, 2500),
           live.ClassProgress("thief", 1, 0, 0.0, 1250))
    card.show_character(_character(classes=two))
    assert card.klass.text().startswith("MU/T")
    assert not hasattr(card, "class_icons")


# --- the notes panel and the popover ----------------------------------------

def test_the_notes_panel_lists_every_note_and_points_at_the_square(app):
    from automap.panel import NotesPanel
    panel = NotesPanel(make_root())
    panel.show_notes({(6, 2): [Note("arena master", "person"),
                               Note("dueling pairs", "encounter")],
                      (1, 1): [Note("exit to Kuto's Well", "exit")]})
    rows = [panel.list.item(i).text() for i in range(panel.list.count())]
    assert rows[0].startswith("(1,1)") and "exit to Kuto's Well" in rows[0]
    assert len(rows) == 3 and "(3)" in panel.heading.text()

    seen = []
    panel.chosen.connect(lambda x, y: seen.append((x, y)))
    panel.list.itemClicked.emit(panel.list.item(2))
    assert seen == [(6, 2)]


def test_a_note_made_in_the_popover_is_saved_and_drawn(app, tmp_path,
                                                       monkeypatch):
    window = make_window(app, tmp_path, monkeypatch, None, area="GEO14")
    window.edit_note(6, 2)
    pop = window._popover
    pop.choose("encounter")
    pop.field.setText("dueling pairs")
    pop.accept()

    assert [n.type for n in window.state.notes_at(6, 2)] == ["encounter"]
    assert window.state.notes_at(6, 2)[0].at            # stamped when made
    payload = json.loads(window.state.notes_path().read_text())
    assert payload["notes"]["6,2"][0]["text"] == "dueling pairs"
    rows = [window.notes_panel.list.item(i).text()
            for i in range(window.notes_panel.list.count())]
    assert rows == ["(6,2)  Encounter - dueling pairs"]


def test_an_empty_untyped_popover_adds_nothing(app, tmp_path, monkeypatch):
    """A note with no type and no words would draw a marker that says
    nothing."""
    window = make_window(app, tmp_path, monkeypatch, None, area="GEO14")
    window.edit_note(6, 2)
    window._popover.accept()
    assert window.state.notes == {}


def test_hovering_a_note_shows_every_note_on_the_square(app, tmp_path,
                                                        monkeypatch):
    window = make_window(app, tmp_path, monkeypatch, None, area="GEO14")
    window.state.add_note(3, 4, Note("dueling pairs", "encounter"))
    window.state.add_note(3, 4, Note("", "locked"))
    # A window nobody showed has never laid its canvas out, and the canvas
    # answers for the size it actually has. Full size is what `CELL` measures.
    window.canvas.resize(window.canvas.sizeHint())
    px = MARGIN + 3 * CELL + 2
    py = MARGIN + 4 * CELL + 2
    assert window.canvas.tooltip_at(px, py) == (
        "Encounter - dueling pairs\nLocked")
    assert window.canvas.tooltip_at(MARGIN + 8 * CELL, py) is None


def test_a_click_hides_the_tooltip_before_the_popover_opens(app, tmp_path,
                                                            monkeypatch):
    """Only a square with a note has a tooltip, and only a square with a note
    failed to open its popover on Windows -- it appeared and vanished, where a
    blank square was fine. A tooltip is a window, and one closing behind a
    `Qt::Popup` deactivates it. So the click hides it first, and no tooltip is
    offered at all while a popover is open."""
    from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
    from PyQt6.QtGui import QHelpEvent, QMouseEvent
    from PyQt6.QtWidgets import QToolTip

    window = make_window(app, tmp_path, monkeypatch, None, area="GEO14")
    window.state.add_note(3, 4, Note("dueling pairs", "encounter"))
    window.canvas.resize(window.canvas.sizeHint())
    at = QPointF(MARGIN + 3 * CELL + 2, MARGIN + 4 * CELL + 2)

    hidden = []
    monkeypatch.setattr(QToolTip, "hideText",
                        staticmethod(lambda: hidden.append(True)))

    def press(kind):
        window.canvas.__getattribute__(
            "mousePressEvent" if kind == "down" else "mouseReleaseEvent")(
            QMouseEvent(
                QMouseEvent.Type.MouseButtonPress if kind == "down"
                else QMouseEvent.Type.MouseButtonRelease, at, at,
                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier))

    press("down")
    assert hidden, "the tooltip is hidden as soon as the button goes down"
    assert window._popover is None, "and nothing opens until it comes up"
    press("up")
    # Queued behind the tooltip's own deletion, so it opens a turn later.
    app.processEvents()
    assert window._popover is not None

    # And with one open, the square offers no tooltip to reopen.
    shown = []
    monkeypatch.setattr(QToolTip, "showText",
                        staticmethod(lambda *a, **k: shown.append(a)))
    spot = QPoint(int(at.x()), int(at.y()))
    window.canvas.event(QHelpEvent(QEvent.Type.ToolTip, spot, spot))
    assert not shown
    window._popover.close()


def test_a_drag_across_squares_opens_nothing(app, tmp_path, monkeypatch):
    """The popover opens on the release, so the release has to land on the
    square the press did. Otherwise dragging across the map would open a note
    on whichever square the mouse happened to stop over."""
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent

    window = make_window(app, tmp_path, monkeypatch, None, area="GEO14")
    window.canvas.resize(window.canvas.sizeHint())

    def at(x, y):
        return QPointF(MARGIN + x * CELL + 2, MARGIN + y * CELL + 2)

    def send(kind, point):
        which = ("mousePressEvent" if kind == "down" else "mouseReleaseEvent")
        getattr(window.canvas, which)(QMouseEvent(
            QMouseEvent.Type.MouseButtonPress if kind == "down"
            else QMouseEvent.Type.MouseButtonRelease, point, point,
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier))

    send("down", at(3, 4))
    send("up", at(7, 9))                       # let go somewhere else
    app.processEvents()
    assert window._popover is None
    send("down", at(3, 4))
    send("up", at(3, 4))                       # and again, properly
    app.processEvents()
    assert window._popover is not None
    window._popover.close()


def test_nothing_is_made_visible_before_it_has_a_parent(app, tmp_path,
                                                        monkeypatch):
    """A parentless widget made visible **is a top-level window.**

    Qt creates it, Windows activates it and takes focus off the main window,
    and reparenting it a line later destroys it again. The note popover was
    built inside that storm -- `Delete` had its visibility set before
    `addWidget` -- and only on a square that already had a note, because only
    then was it made visible. Qt dismissed the popup on the way out, and the
    user saw a small empty window half-paint and vanish.

    Found from the raw Windows message stream: a whole `WM_NCACTIVATE` /
    `WM_ACTIVATE` / `WM_KILLFOCUS` / `WM_SETFOCUS` round trip through a
    stranger's hwnd, between "building" and "built", on noted squares and
    never on blank ones.
    """
    from PyQt6.QtCore import Qt as _Qt
    from PyQt6.QtWidgets import QWidget

    window = make_window(app, tmp_path, monkeypatch, None, area="GEO14")
    window.state.add_note(3, 4, Note("dueling pairs", "encounter"))

    stray = []
    real = QWidget.setVisible

    def watched(widget, visible):
        # `isWindow()` is no use as a filter: a parentless button answers
        # True, which *is* the fault. What separates an accident from a
        # deliberate top-level is the window type -- a popover asks for
        # `Popup`, a stray button gets plain `Window` by default.
        accidental = (visible and widget.parent() is None
                      and widget.windowType() == _Qt.WindowType.Window)
        if accidental:
            stray.append(type(widget).__name__)
        return real(widget, visible)

    monkeypatch.setattr(QWidget, "setVisible", watched)
    window.edit_note(3, 4)                       # the square that used to fail
    app.processEvents()
    assert not stray, f"made visible with no parent: {stray}"
    window._popover.close()


def test_the_popover_is_on_record_before_it_is_shown(app, tmp_path,
                                                     monkeypatch):
    """`_popover` is set before `show()`, not after.

    Showing a popup pumps the platform's message queue, so anything asking
    "is a popover open?" during the show is answered then. The canvas's
    tooltip guard asks exactly that, and only a square that *has* a note has a
    tooltip to offer -- which is why a noted square's popover died on Windows
    and a blank square's did not, and why suppressing the tooltip alone did
    not fix it. `show()` here stands for that moment.
    """
    window = make_window(app, tmp_path, monkeypatch, None, area="GEO14")
    window.state.add_note(3, 4, Note("dueling pairs", "encounter"))

    seen = []
    from automap import noteeditor
    real = noteeditor.NotePopover.show
    monkeypatch.setattr(noteeditor.NotePopover, "show",
                        lambda s: (seen.append(window._popover), real(s)))
    window.edit_note(3, 4)
    assert seen and seen[0] is window._popover, \
        "the window knew about the popover before it was shown"
    window._popover.close()


def test_right_clicking_a_square_offers_edit_and_delete(app, tmp_path,
                                                        monkeypatch):
    window = make_window(app, tmp_path, monkeypatch, None, area="GEO14")
    window.state.add_note(3, 4, Note("locked, come back", "locked"))
    window.state.add_note(3, 4, Note("cleared", "done"))
    entries = window.note_menu_entries(3, 4)
    # No "add another": a square holds one note. Both are still listed,
    # because a file from a build that allowed two has to stay deletable.
    assert [text for text, _ in entries] == [
        "Edit  Locked - locked, come back",
        "Delete  Locked - locked, come back",
        "Edit  Done - cleared",
        "Delete  Done - cleared"]
    entries[1][1]()                                   # delete the first
    assert [n.type for n in window.state.notes_at(3, 4)] == ["done"]


def test_n_puts_a_note_on_the_partys_own_square(app, tmp_path, monkeypatch):
    """The common case while playing, with the game in the other window."""
    window = make_window(app, tmp_path, monkeypatch, None, area="GEO14")
    window.state.source, window.state.x, window.state.y = "status", 7, 11
    assert window._note_action.shortcut().toString() == "N"
    window._note_action.trigger()
    assert window._popover.square == (7, 11)


def test_a_notes_row_flashes_its_square(app, tmp_path, monkeypatch):
    window = make_window(app, tmp_path, monkeypatch, None, area="GEO14")
    window.point_at(9, 3)
    assert window.canvas.flash == (9, 3)


# --- the quest log panel, wired -------------------------------------------

def test_the_tab_shows_the_quest_log(app, tmp_path, monkeypatch):
    save0, save1 = captured()
    window = make_window(app, tmp_path, monkeypatch,
                         MemoryTarget({0x4900: save0, 0x8300: save1}))
    for _ in range(window.LIVE_EVERY):
        window.tick()
    assert window.questlog.completed.text().startswith(
        "Quests completed:")
    assert window.questlog.heading.text() == "Quest Log"


def test_a_poll_that_reads_nothing_leaves_the_quest_log_alone(app, tmp_path,
                                                                monkeypatch):
    """Plot flags do not change while the game is in a menu, and a blanked
    quest log every time somebody opens one would be a flicker."""
    save0, save1 = captured()
    machine = MemoryTarget({0x4900: save0, 0x8300: save1})
    window = make_window(app, tmp_path, monkeypatch, machine)
    for _ in range(window.LIVE_EVERY):
        window.tick()
    before = window.questlog.completed.text()
    machine.memory[0x4900] = bytes(0x1C00)
    for _ in range(window.LIVE_EVERY):
        window.tick()
    assert window.questlog.completed.text() == before


# --- the action buttons -----------------------------------------------------

def test_with_nothing_attached_the_buttons_are_disabled_not_inert(app):
    from automap.actionbar import ActionBar
    bar = ActionBar(make_root())
    bar.attach(None)
    assert not any(b.isEnabled() for b in bar.buttons.values())
    assert bar.buttons["heal"].toolTip() == "no emulator attached"


def _test_the_buttons_are_laid_out_in_the_two_rows_donald_asked_for(app):
    """Donald's order, and the labels in the American spelling he asked for
    three times. `actions()` is the reading order and `COLUMNS` breaks it into
    rows, so this pins both at once."""
    from automap.actionbar import COLUMNS, ActionBar
    bar = ActionBar(make_root())
    grid = bar.layout()
    rows: dict[int, list[str]] = {}
    for name, button in bar.buttons.items():
        i = grid.indexOf(button)
        row, column, _, _ = grid.getItemPosition(i)
        rows.setdefault(row, []).append((column, button.text()))
    laid = [[text for _, text in sorted(rows[r])] for r in sorted(rows)]
    assert laid == [
        ["Heal the party", "Store memorized spells", "Restore memorized "
         "spells"],
        ["Identify all items", "Quickfight off"],
    ]
    assert COLUMNS == 3
    # The label moved to the American spelling; the internal names and the
    # record field `spells_memorised` did not.
    assert set(bar.buttons) == {"heal", "store-spells", "restore-spells",
                                "identify", "clear-quickfight"}
    assert "memorised" not in " ".join(b.text() for b in bar.buttons.values())
    # Levelling is on the roster card, not here.
    assert "level-up" not in bar.buttons


def test_a_fight_disables_what_a_fight_forbids(app):
    from automap.actionbar import ActionBar
    bar = ActionBar(make_root())
    bar.attach(MemoryTarget({0x6E11: b"\x02"}))
    # Heal used to be legal mid-fight and no longer is: healing during a
    # fight writes the roster byte the engine is itself using (#146).
    assert not bar.buttons["heal"].isEnabled()
    assert "$6E11 is 2" in bar.buttons["heal"].toolTip()
    assert not bar.buttons["identify"].isEnabled()
    assert "$6E11 is 2" in bar.buttons["identify"].toolTip()


def test_the_whole_row_costs_one_read_of_the_mode_flag(app):
    """Six actions asking `legality` is six round trips otherwise, and each
    hands the emulation ~14.3 ms of extra emulated time."""
    from automap.actionbar import ActionBar
    machine = MemoryTarget({0x6E11: b"\x00"})
    bar = ActionBar(make_root())
    bar.attach(machine)
    assert [r for r in machine.reads if r[0] == 0x6E11] == [(0x6E11, 1)]


def test_an_action_that_carries_a_confirm_asks_first(app):
    from automap.actionbar import ActionBar
    machine = MemoryTarget({0x6E11: b"\x00"})
    said = []
    bar = ActionBar(make_root(), say=lambda text, detail="", alarm=False: said.append(text))
    asked = []
    bar.ask = lambda question: asked.append(question) or False
    bar.attach(machine)
    identify = next(a for a in bar.actions if a.name == "identify")
    identify.confirm = "no way to undo"
    assert bar.run(identify) is None
    assert asked and "no way to undo" in asked[0]
    assert said == []                       # refused before anything was read

    bar.ask = lambda question: True
    outcome = bar.run(identify)
    # The result is a line in the messages panel, not a pop-up to dismiss.
    assert outcome is not None
    # A Messages panel line opens with a capital -- `CLAUDE.md`, "Help text
    # in the GUI". The whole composed line is still what is pinned.
    assert said == [f"Identify: {outcome.message}"]


def test_the_quickfight_watcher_is_off_until_it_is_asked_for(app):
    """It writes to a running machine on an edge nobody asked for, so it has
    to be turned on deliberately."""
    from automap.actionbar import ActionBar
    save0, save1 = captured()
    machine = MemoryTarget({0x4900: save0, 0x8300: save1, 0x6E11: b"\x02"})
    bar = ActionBar(make_root())
    assert not bar.watcher.enabled
    assert bar.watch(machine) is None                  # in a fight
    assert bar.watch(machine) is None                  # still in the fight
    machine.memory[0x6E11] = b"\x00"
    bar.watcher.enabled = True
    outcome = bar.watch(machine)                       # the 2-to-not-2 edge
    assert outcome is not None and outcome.ok
    assert outcome.message == "No party member had quickfight enabled."
    machine.memory[0x6E11] = b"\x00"
    assert bar.watch(machine) is None                  # edge only, not level


def test_the_tab_polls_the_buttons_with_the_party(app, tmp_path, monkeypatch):
    save0, save1 = captured()
    window = make_window(app, tmp_path, monkeypatch,
                         MemoryTarget({0x4900: save0, 0x8300: save1}))
    assert not window.actions_bar.buttons["heal"].isEnabled()
    for _ in range(window.LIVE_EVERY):
        window.tick()
    assert window.actions_bar.target is window.mapper.target
    assert window.actions_bar.buttons["heal"].isEnabled()


def test_the_font_awesome_attribution_is_gone_with_the_icons():
    """CC BY 4.0's one obligation stops applying once nothing renders the
    material it covers. `person` replacing `user` on `#167` was the last
    Font Awesome glyph anything in the program drew, so the credit and its
    licence file came out in the same change -- see
    `tests/test_licenses.py` for the fuller version of this check."""
    from wish.about import TEXT
    root = pathlib.Path(__file__).resolve().parent.parent
    assert "Font Awesome" not in TEXT
    # `encoding=` is not optional: the default is the locale codec, which is
    # cp1252 on the Windows runners, and the README has an em dash in it.
    assert "Font Awesome" not in (root / "README.md").read_text(encoding="utf-8")
    assert not (root / "fontawesome-LICENSE.txt").exists()
    assert icons.FONT_AWESOME == {}


# --- what Donald found while playing ----------------------------------------

def test_clicking_a_note_opens_it_with_its_words_in_the_field(app, tmp_path,
                                                              monkeypatch):
    """It opened blank, which made an existing note look lost."""
    window = make_window(app, tmp_path, monkeypatch, None, area="GEO14")
    window.state.add_note(6, 2, Note("locked, come back", "locked"))
    window.edit_note(6, 2)
    pop = window._popover
    assert pop.index == 0
    assert pop.field.text() == "locked, come back"
    assert pop.chosen == "locked" and pop.buttons["locked"].isChecked()
    assert not pop.remove.isHidden()          # and it can be got rid of


def test_the_picker_offers_every_kind_in_the_rows_the_table_groups_them_in(
        app, tmp_path, monkeypatch):
    """Twenty-five buttons, no words on any of them, laid out five to a row --
    and the rows are `notes.TYPES`' own order, which is a grouping: marks,
    what the square holds, a fight, a person, a place you come back to.

    Asserted against the table rather than against a picture of the grid, so
    adding a kind in the middle of a row moves the rest and this still holds.
    """
    from automap.noteeditor import COLUMNS

    window = make_window(app, tmp_path, monkeypatch, None, area="GEO14")
    window.edit_note(6, 2)
    pop = window._popover
    picker = pop.ui.picker

    assert set(pop.buttons) == {k.name for k in notemod.TYPES}
    assert picker.count() == len(notemod.TYPES) == 25
    assert COLUMNS == notemod.PICKER_COLUMNS == 5
    for n, kind in enumerate(notemod.TYPES):
        row, column = divmod(n, COLUMNS)
        at = picker.itemAtPosition(row, column)
        assert at is not None and at.widget() is pop.buttons[kind.name], \
            f"{kind.name} is not at row {row}, column {column}"
        # No words: the picture is the whole of what the button says, and the
        # description is a hover away.
        assert at.widget().text() == ""
        assert at.widget().toolTip() == f"{kind.label} - {kind.hint}"
    assert picker.rowCount() == 5 and picker.columnCount() == 5
    window.root.close()


def test_the_picker_is_still_a_popover_at_the_square_and_not_a_dialog(
        app, tmp_path, monkeypatch):
    """The one thing twenty-five kinds must not have cost. Notes get made
    mid-game with a fight waiting in the other window, so the editor is a
    `Popup` that goes away by itself -- never a modal dialog somebody has to
    dismiss before they can look at the map again."""
    from PyQt6.QtCore import Qt as _Qt
    from PyQt6.QtWidgets import QDialog

    window = make_window(app, tmp_path, monkeypatch, None, area="GEO14")
    window.edit_note(6, 2)
    pop = window._popover
    assert not isinstance(pop, QDialog)
    assert pop.windowType() == _Qt.WindowType.Popup
    assert not pop.isModal()
    window.root.close()


def test_the_picker_fits_a_720_high_screen_with_room_for_the_map(
        app, tmp_path, monkeypatch):
    """Donald said the picker could get bigger; it still has to open on his
    screen, and it opens *over* the map rather than beside it.

    **The bound is computed, not measured.** A pixel count taken here is a
    measurement of this machine -- CI's Linux and Windows draw the buttons'
    frames and the field's font differently -- so what is asserted is that
    the popover asks for no more than its own five rows of buttons plus the
    rest of the form, and that the total is a fraction of a 720-high screen.
    """
    from automap.noteeditor import BUTTON, COLUMNS

    window = make_window(app, tmp_path, monkeypatch, None, area="GEO14")
    window.edit_note(6, 2)
    pop = window._popover
    wanted = pop.sizeHint()
    rows = -(-len(notemod.TYPES) // COLUMNS)

    # The grid is the biggest thing in it, and it is bounded by its own rows.
    grid = pop.ui.picker
    assert grid.sizeHint().height() >= rows * BUTTON
    assert grid.sizeHint().height() <= rows * BUTTON + \
        (rows - 1) * grid.verticalSpacing() + 2 * BUTTON

    # A quarter of a 720-high screen, so the square being annotated is still
    # visible under it. Generous on purpose: what would fail is a picker that
    # grew a row per kind, not one that is a few pixels taller on Windows.
    assert wanted.height() <= 720 // 2, wanted
    assert wanted.width() <= 1280 // 2, wanted
    window.root.close()


def test_a_new_note_has_nothing_to_delete(app, tmp_path, monkeypatch):
    window = make_window(app, tmp_path, monkeypatch, None, area="GEO14")
    window.edit_note(6, 2)
    assert window._popover.index is None
    assert window._popover.remove.isHidden()


def test_the_delete_button_removes_the_note(app, tmp_path, monkeypatch):
    """The bug that mattered: a note could be made and not unmade."""
    window = make_window(app, tmp_path, monkeypatch, None, area="GEO14")
    window.state.add_note(6, 2, Note("kobold ambush", "danger"))
    window.notes_changed()
    window.edit_note(6, 2)
    window._popover.remove.click()
    assert window.state.notes_at(6, 2) == []
    assert json.loads(window.state.notes_path().read_text())["notes"] == {}
    assert window.notes_panel.list.count() == 0


def test_the_popover_opens_the_note_and_offers_no_way_to_make_a_second(
        app, tmp_path, monkeypatch):
    """A square holds one note. An old file holding two still opens on the
    first, and the popover says nothing about the second -- the right-click
    menu is where the extras are reached and deleted."""
    window = make_window(app, tmp_path, monkeypatch, None, area="GEO14")
    window.state.add_note(6, 2, Note("dueling pairs", "encounter"))
    window.state.add_note(6, 2, Note("needs a thief", "treasure"))
    window.edit_note(6, 2)
    pop = window._popover
    assert pop.field.text() == "dueling pairs"          # the first is open
    assert [b.text() for b in pop.findChildren(QPushButton)] == ["Delete",
                                                                 "Keep"]
    window.delete_note(6, 2, 1)                         # still removable
    assert [n.type for n in window.state.notes_at(6, 2)] == ["encounter"]


def test_an_action_reports_into_the_messages_panel_not_a_pop_up(app, tmp_path,
                                                                monkeypatch):
    save0, save1 = captured()
    window = make_window(app, tmp_path, monkeypatch,
                         MemoryTarget({0x4900: save0, 0x8300: save1}))
    for _ in range(window.LIVE_EVERY):
        window.tick()
    heal = next(a for a in window.actions_bar.actions if a.name == "heal")
    outcome = window.actions_bar.run(heal)
    assert outcome is not None
    assert window.messages.lines()[-1].endswith(outcome.message)


def test_the_messages_panel_drops_repeats_and_keeps_the_alarm(app, tmp_path,
                                                              monkeypatch):
    """The connection says the same thing on every tick while it waits."""
    window = make_window(app, tmp_path, monkeypatch, None)
    window.waiting("something else is attached to the emulator", alarm=True)
    window.waiting("something else is attached to the emulator", alarm=True)
    lines = [ln for ln in window.messages.lines() if "attached" in ln]
    assert len(lines) == 1
    row = window.messages.list.item(window.messages.list.count() - 1)
    from automap.panel import DANGER
    assert row.foreground().color().name() == DANGER.name()


def test_a_character_at_zero_and_a_drained_one_are_marked(app):
    """The two conditions the *record* tells us, as opposed to the five the
    save's effect arrays do -- those are `tests/test_conditionbadges.py`."""
    from automap.panel import CharacterCard
    card = CharacterCard(make_root(), 0)
    card.show_character(_character(hp=0))
    assert card.conditions.names == ("death-skull",)
    card.show_character(_character(hp=4, levels_drained=2))
    assert card.conditions.names == ("oppression",)
    assert "Drained 2 levels" in card.conditions.toolTip()
    card.show_character(_character())
    assert card.conditions.names == ()


def _multi_class_character(**kw):
    """LADY KATHERINE at magic-user 1 / thief 1 with 5,002 points: both
    classes ready, and the two thresholds that decide the order."""
    return _character(
        slot=3, name="LADY KATHERINE", level=1,
        classes=(live.ClassProgress("magic-user", 1, 5002, 1.0, 2501),
                 live.ClassProgress("thief", 1, 5002, 1.0, 1251)), **kw)


def test_the_level_up_button_opens_no_menu_for_a_multi_class_character(app):
    """The player is not asked which class. The button acts, and the signal
    carries the slot and nothing else -- a menu would also have blocked in
    `exec` here, so reaching the assertions is half the proof."""
    from PyQt6.QtWidgets import QMenu

    from automap.panel import CharacterCard
    card = CharacterCard(make_root(), 0)
    seen = []
    card.level_up_requested.connect(seen.append)
    card.show_character(_multi_class_character())
    assert card.level_up.isVisibleTo(card.frame)
    card.level_up.click()
    assert seen == [3]
    assert card.findChildren(QMenu) == []


def test_the_button_says_which_class_it_will_raise(app):
    """The magic-user, because its threshold after the level -- 5,001 -- is
    larger than the thief's 2,501, and that is the number the trainer's clamp
    reads. Thief first would strand her at 2,500."""
    from automap.panel import CharacterCard
    card = CharacterCard(make_root(), 0)
    card.show_character(_multi_class_character())
    assert card.chosen_class(_multi_class_character()) == "magic-user"
    assert card.level_up.toolTip() == "level up as magic-user"


def test_the_quickfight_badge_appears_only_when_the_bit_is_set(app):
    """Roster block `+0x0C` bit 7, CONFIRMED. Its own row under the readied
    line and right-aligned -- not the conditions row, which is what has
    happened *to* a character rather than what their player chose."""
    from automap.panel import CharacterCard
    card = CharacterCard(make_root(), 0)
    card.show_character(_character(quickfight=True))
    assert card.quickfight.names == ("sparkling-sabre",)
    assert card.quickfight.toolTip() == "Quickfight"
    # Not in with the conditions, and not shifting the card when it goes.
    assert card.conditions.names == ()
    tall = card.frame.sizeHint().height()
    card.show_character(_character())
    assert card.quickfight.names == ()
    assert card.frame.sizeHint().height() == tall


def test_the_quickfight_bit_reaches_the_snapshot_from_the_roster_page(app):
    """The panel does not read the roster itself: `live.characters` carries the
    bit, and `actions.QUICKFIGHT` writes the same byte and the same mask."""
    from automap import actions
    save0, save1 = captured()
    roster = bytearray(save1)
    plain = live.snapshot_from_bytes(save0, bytes(roster))
    assert plain is not None and not any(c.quickfight for c in plain.characters)

    slot = plain.characters[0].slot
    roster[slot * live.ROSTER_STRIDE
           + live.ROSTER_QUICKFIGHT] |= live.QUICKFIGHT_BIT
    snap = live.snapshot_from_bytes(save0, bytes(roster))
    assert [c.slot for c in snap.characters if c.quickfight] == [slot]

    assert actions.QUICKFIGHT.address(slot) == 0x8300 + slot * 0x20 + 0x0C
    assert actions.QUICKFIGHT.mask == live.QUICKFIGHT_BIT


def test_the_quickfight_sabre_is_the_artists_own_drawing(app):
    """Lorc's `sparkling-sabre`, verbatim from game-icons.net and drawn in its
    own 512 box. It replaced `person-running` because Donald gave the running
    figure to hasted, and two runners on one card at 13px cannot be told apart
    -- `#4 (Condition badges on the roster card)`.

    Pinned as ink rather than as a shape: the point is that a Qt or a parser
    change that turned the glyph into nothing or into a blob fails here rather
    than on somebody's card. 52 pixels at 13px, measured on this machine with
    Qt 6."""
    from PyQt6.QtGui import QColor, QImage, QPainter

    from ui.iconpaint import draw_icon
    assert "sparkling-sabre" in icons.GAME_ICONS
    assert icons.ARTISTS["sparkling-sabre"] == "Lorc"
    assert icons.box("sparkling-sabre") == 512

    size = 13
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("white"))
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw_icon(p, "sparkling-sabre", 0, 0, size, QColor("black"))
    p.end()
    ink = sum(1 for y in range(size) for x in range(size)
              if QColor(image.pixel(x, y)).lightness() < 190)
    assert 40 <= ink <= 90, ink


def test_an_effect_with_no_badge_is_still_only_a_number():
    """The two lists share one namespace -- `LIBRARY $4028` reads the arrays
    and falls back to the character's own slots -- so `goldbox/traits.py` can
    name an effect, and since `#142 (The party effects line is computed every
    poll and shown nowhere)` the strip does name them: an icon per spell with
    the name in its tooltip, which is what Donald settled.

    **That is a name behind a picture somebody chose**, and it is the choosing
    that makes it safe to show. An effect with no badge has had nobody look at
    it, so it stays a number -- `effect 64` in the debug log, never a name in
    front of a player -- and 64 shows why: `goldbox/traits.py` calls it a melee
    poison, which is a monster's attack and not a spell running on a party.
    `docs/133-active-effects.md` is where the rest of the naming is designed."""
    effect = live.Effect(slot=0, id=64, owner=0, duration=3, magnitude=0)
    assert effect.label == "effect 64"
    from goldbox import traits
    assert traits.describe(64).startswith("melee poison")   # a trait, not this
    covered = {i for _, ids in live.CONDITION_BADGES for i in ids}
    assert 64 not in covered


def book_flags() -> bytes:
    """The flag block from the shipped unplayed save, as bytes."""
    from goldbox import commissions as book
    save0 = (FIXTURES / "savedgame0.bin").read_bytes()[2:]
    return book.flags(save0).to_bytes()


def test_typing_a_note_is_not_eaten_by_the_shortcut_that_opened_it(
        app, tmp_path, monkeypatch):
    """`N` opens a note, so it could take the `n` out of the words being
    typed. It does not: the popover holds the keyboard while the field has
    focus.

    **The per-kind letters are gone, and this test used to cover them too.**
    `NoteType.key` gave each of the nine a letter -- `E T P X L S D N C` --
    and `keyPressEvent` picked that kind when the letter was pressed outside
    the field. Nothing in the window ever said so, and Donald did not know
    they existed: *"I didn't even know we had keyboard shortcuts... That isn't
    necessary at all"* (`#166`). So the assertion that `e` picked nothing has
    become the assertion below, that there is no letter left to press.
    """
    from PyQt6.QtTest import QTest
    window = make_window(app, tmp_path, monkeypatch, None, area="GEO14")
    window.root.show()
    window.edit_note(3, 3)
    pop = window._popover
    pop.field.setFocus()
    QTest.keyClicks(pop.field, "north gate")
    assert pop.field.text() == "north gate"
    assert window._popover is pop            # no second popover opened
    assert pop.chosen == "note"              # and no kind was picked by "n"
    window.root.close()


def test_no_note_kind_carries_a_keyboard_letter(app, tmp_path, monkeypatch):
    """The removal, pinned from both ends: nothing on a kind says a letter,
    and pressing one outside the text field picks nothing.

    Twenty-five kinds could not each have had one anyway, but that is not why
    they went -- an undocumented shortcut the program's author did not know
    about is not a feature anybody was using."""
    from PyQt6.QtCore import Qt as _Qt
    from PyQt6.QtTest import QTest

    assert not hasattr(notemod.NoteType, "key")
    assert "key" not in notemod.NoteType.__dataclass_fields__

    window = make_window(app, tmp_path, monkeypatch, None, area="GEO14")
    window.root.show()
    window.edit_note(3, 3)
    pop = window._popover
    pop.setFocus()                              # not the field: the popover
    for letter in ("E", "T", "P", "X", "L", "S", "D", "C"):
        QTest.keyClick(pop, getattr(_Qt.Key, f"Key_{letter}"))
        assert pop.chosen == "note", letter
    window.root.close()


def test_the_action_bar_rebuilds_its_buttons_when_the_title_changes(app):
    """The window resolves the title off the disks and tells the row; the row
    is what carries the descriptor into every address the buttons write."""
    from automap.actionbar import ActionBar

    bar = ActionBar(make_root())
    assert all(a.game is games.POOL_OF_RADIANCE for a in bar.actions)
    bar.set_game(CURSE)
    assert all(a.game is CURSE for a in bar.actions)
    assert bar.watcher.game is CURSE
    # And the gate it reads is Curse's own `LINKER` byte, not $6E11 (#29).
    machine = curse_machine()
    machine.memory[CURSE.mode_flag] = b"\x01"
    bar.attach(machine)
    assert [r for r in machine.reads if r[0] == 0x7F11] == [(0x7F11, 1)]
    assert all(b.isEnabled() for b in bar.buttons.values())


def test_a_title_whose_loader_has_never_been_read_refuses_every_button(app):
    """Champions of Krynn has no measured mode flag, so there is no way to tell
    a fight from the map and no button may write. The reason is in the tooltip
    rather than the button being silently inert."""
    from automap import actions
    from automap.actionbar import ActionBar

    krynn = games.CHAMPIONS_OF_KRYNN
    assert krynn.mode_flag is None
    bar = ActionBar(make_root())
    bar.set_game(krynn)
    save0, roster = captured()
    bar.attach(MemoryTarget({krynn.save_load_address: save0 + roster}))
    for name, button in bar.buttons.items():
        assert not button.isEnabled(), name
        assert button.toolTip() == actions.UNSUPPORTED.format(
            title=krynn.title), name


# --- giving up on a connection, and hanging up while doing it ---------------


class HangUpMonitor:
    """A `Monitor` that answers the greeting and then fails every read.

    Stands in for the one thing a stub socket cannot reproduce: an emulator
    that stops answering part-way through a session, which is what
    Donald's log of 2026-08-31 caught -- one poll of 5004 ms against a 5.0 s
    socket timeout, then the session giving up.
    """

    def __init__(self, failure):
        self.failure = failure
        self.sock = None
        self.exits = 0
        self.resumes = 0

    # what `ViceTarget.__init__` uses
    def __enter__(self):
        import socket as _socket
        self.sock = _socket.socket()      # never connected; only its timeout
        return self

    def __exit__(self, *exc):
        self.exits += 1
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def ping(self):
        pass

    def resume(self):
        self.resumes += 1

    def read(self, addr, length):
        raise self.failure

    def write(self, addr, data):
        raise self.failure


def _vice_target_over(monkeypatch, failure):
    from automap import target as target_mod
    monkeypatch.setattr(target_mod, "Monitor",
                        lambda **kw: HangUpMonitor(failure))
    return target_mod.ViceTarget()


def test_a_connection_it_has_given_up_on_is_actually_closed(monkeypatch):
    """The socket is hung up at the moment the read fails, not left for a
    caller to remember.

    `close()` used to be `if self._open:` and every give-up cleared that flag
    first, so the `EXIT` was never sent and the socket was never closed. VICE
    serves exactly one binary-monitor connection, so what wish reattached
    against after that was its own abandoned socket, and the reattach was
    answered and then never served -- which is the same thing on the wire as
    somebody else holding the monitor.
    """
    from automap.target import NotConnected

    t = _vice_target_over(monkeypatch, TimeoutError("timed out"))
    with pytest.raises(NotConnected):
        t.fix()
    assert t._mon.exits == 1, "the give-up left the socket open"
    t.close()                                    # and calling it again is safe
    assert t._mon.exits == 2 or t._mon.sock is None


def test_a_protocol_failure_is_a_lost_connection_and_not_mere_trouble(monkeypatch):
    """A short read is not an `OSError`, and used to escape as a plain
    exception with the connection kept.

    `Monitor._recv_exactly` throws away the part of a message it had collected
    when a read times out, so every command after one is reading the tail of
    the last one as a header. Keeping that connection means the window says
    "trouble reading the machine" once and then never reads anything again.
    """
    from automap.target import NotConnected
    from automap.vice import MonitorError

    assert not issubclass(MonitorError, OSError)       # why it used to escape
    failure = MonitorError("asked 40 bytes at $0400, got 0")
    for call in ("fix", "read", "read_blocks", "write"):
        t = _vice_target_over(monkeypatch, failure)
        args = {"fix": (), "read": (0x0400, 40), "write": (0x0400, b"x"),
                "read_blocks": ([(0x0400, 40)],)}[call]
        with pytest.raises(NotConnected) as gone:
            getattr(t, call)(*args)
        assert "asked 40 bytes" in str(gone.value), call
        assert t._mon.exits == 1, call


def test_a_greeting_that_fails_oddly_still_hangs_up(monkeypatch):
    """`__init__` shut the connection for `TimeoutError` and `OSError` and for
    nothing else, so a `MonitorError` out of the ping leaked a connected
    socket -- and a leaked socket is what the next attach loses to."""
    from automap import target as target_mod
    from automap.vice import MonitorError

    mon = HangUpMonitor(MonitorError("bad response magic 0x00"))
    mon.ping = lambda: (_ for _ in ()).throw(mon.failure)
    monkeypatch.setattr(target_mod, "Monitor", lambda **kw: mon)
    with pytest.raises(MonitorError):
        target_mod.ViceTarget()
    assert mon.exits == 1, "a half-made connection was left open"


class NullSocketMonitor(HangUpMonitor):
    """A `Monitor` that fails after hanging up the way the real one does.

    `Monitor.__exit__` sets `sock = None` (`automap/vice.py:124`) and
    `Monitor.read` opens with `self.sock.sendall(...)` (line 141), so a read
    through a target that has already given up raises `AttributeError` -- not
    an `OSError` and not a `MonitorError`, so none of `ViceTarget`'s handlers
    catch it. `HangUpMonitor` cannot show this because it raises its failure
    whatever state it is in.
    """

    def _wire(self):
        if self.sock is None:
            raise AttributeError(
                "'NoneType' object has no attribute 'sendall'")

    def read(self, addr, length):
        self._wire()
        raise self.failure

    def write(self, addr, data):
        self._wire()
        raise self.failure


def test_a_target_that_gave_up_refuses_a_later_call_rather_than_crashing(
        monkeypatch):
    """A user clicks Fast Travel a moment after the emulator stalls.

    The button's enabled state is one poll interval stale, so it is still
    drawn enabled when the connection has already gone -- and `Automapper`,
    `ActionBar` and `FastTravelBar` each keep their own reference to the
    target, none of which the give-up clears. Every one of those calls has to
    answer `NotConnected`, which the action bar already handles, rather than
    an `AttributeError` out of a Qt button slot (#151).
    """
    from automap import target as target_mod
    from automap.target import NotConnected
    from automap.vice import MonitorError

    mon = NullSocketMonitor(MonitorError("bad response magic 0x00"))
    monkeypatch.setattr(target_mod, "Monitor", lambda **kw: mon)
    t = target_mod.ViceTarget()

    with pytest.raises(NotConnected):
        t.read(0x0400, 16)                  # the poll that loses the machine
    assert mon.sock is None, "giving up did not hang up"

    for what, call in (("read", lambda: t.read(0x0400, 16)),
                       ("write", lambda: t.write(0x0400, b"\x00")),
                       ("fix", lambda: t.fix()),
                       ("read_blocks", lambda: t.read_blocks([(0x0400, 16)])),
                       ("screen", lambda: t.screen())):
        with pytest.raises(NotConnected):
            call()
