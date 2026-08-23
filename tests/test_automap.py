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
    COUNT_SIZE,
    MARGIN,
    NOTE_SIZE,
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
from automap.state import Automapper, AutomapState, Exploration
from automap.state import data_dir as state_data_dir
from automap.target import Fix, ReplayTarget
from por.geo import (
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
    """New Phlan, The Slums and Sokol Keep -- `por/areas.py` ids 0, 20 and 21.
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
    assert Settings.load().fast_travel_targets == []
    assert Settings.load().chosen_areas() == ()


def test_a_hand_edited_area_list_is_read_for_what_it_holds(tmp_path,
                                                           monkeypatch):
    """The settings file is documented as one you can edit, so a row that is
    not a number loses that row and nothing else."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from automap.config import Settings

    assert Settings(
        fast_travel_targets=["0", 20, None, "twenty"]).chosen_areas() == (
        0, 20)
    assert Settings(fast_travel_targets=7).chosen_areas() == (0, 20, 21)


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
    warped from the Slums to New Phlan, stepped to New Phlan's (14,1), and five
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
    kept = json.loads((state_data_dir() / "GEO00.json").read_text())["seen"]
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
from automap.target import MemoryTarget  # noqa: E402
from por.record import FieldNotStored  # noqa: E402


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
    assert brutus.class_text == "fighter" and brutus.level_text == "L1"
    assert (snap.x, snap.y, snap.facing) == (0, 4, 3)
    assert snap.clock_text == "0:01" and snap.area_file == "GEO00"


@game_disks
def test_the_party_reads_the_same_live_as_it_does_off_the_disk():
    """The assertion the editor's roster test makes, by a different path: the
    same bytes, read as a running machine rather than as a file."""
    from por.d64 import D64
    disk = D64.open(f"{DISKS}/PORSAVE11.D64")
    snap = live.read_snapshot(live_machine(
        disk.read_file(b"SAVEDGAME0")[2:],
        disk.read_file(b"SAVEDGAME1")[2:2 + live.ROSTER_PAGE]))
    roland = next(c for c in snap.characters if c.name == "ROLAND")
    assert (roland.hp, roland.hp_max) == (5, 7) and roland.hurt
    assert [c.name for c in snap.characters] == [
        "MALCYON", "LADY KATHERINE", "ROLAND", "SILAS", "MAGNUS", "BRUTUS"]
    katherine = snap.characters[1]
    assert katherine.class_text == "magic-user/thief"      # two bars, not one
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


def test_the_whole_tab_costs_two_reads():
    """The cost of a poll is the round trip, not the bytes -- 14.3 ms either
    way under VICE -- so this number is the one that matters."""
    machine = live_machine()
    live.read_snapshot(machine)
    assert machine.reads == [(0x4900, 0x1C00), (0x8300, 0x100)]


def test_the_combat_numbers_come_from_the_roster_not_the_record():
    """A save slot holds 256 bytes; AC, THAC0 and current hit points are past
    them. Reading them from the record gives AC 60 -- plausible and wrong."""
    from por.savegame import SaveGame0
    save0, save1 = captured()
    record = SaveGame0.from_bytes(save0).characters[0].record
    with pytest.raises(FieldNotStored):
        record.get("armour_class")
    assert live.snapshot_from_bytes(save0, save1).characters[0].armour_class == 9


# --- effects ---------------------------------------------------------------

def with_effect(slot=0, id=1, owner=0, duration=0x43, magnitude=2):
    save0, save1 = captured()
    raw = bytearray(save0)
    for base, value in ((live.EFFECT_ID, id), (live.EFFECT_OWNER, owner),
                        (live.EFFECT_DURATION, duration),
                        (live.EFFECT_MAGNITUDE, magnitude)):
        raw[base - 0x4900 + slot] = value
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
    card = CharacterCard()
    card.show_character(live.Character(
        slot=0, name="MAGNUS", classes=(ceiling,), level=8, armour_class=2,
        thac0=13, hp=60, hp_max=60, experience=130000))
    assert card.xp[0].text == "fighter maximum"
    assert card.xp[0].fraction == 1.0


def test_a_card_with_no_effects_keeps_its_strip(app):
    """An effects strip that appears and disappears shifts every card below it
    each time a spell expires."""
    from automap.panel import CharacterCard
    save0, save1 = captured()
    plain = live.snapshot_from_bytes(save0, save1).characters[0]
    blessed = live.snapshot_from_bytes(*with_effect(owner=0)).characters[0]
    card = CharacterCard()
    card.show_character(blessed)
    tall = card.sizeHint().height()
    card.show_character(plain)
    assert card.effects.text() == ""
    assert card.sizeHint().height() == tall


def test_the_strip_says_when_the_party_is_not_readable(app):
    from automap.panel import BottomStrip
    strip = BottomStrip()
    state = AutomapState()
    state.area = "GEO00"
    strip.show_state(state, None)
    assert "not readable" in strip.effects.text()
    assert strip.where.text() == "square --"     # no fix yet is not (0,0)
    state.source, state.x, state.y = "status", 3, 14
    strip.show_state(state, None)
    assert strip.where.text() == "(3,14) facing N"
    strip.show_state(state, live.snapshot_from_bytes(*captured()))
    assert strip.clock.text() == "0:01"
    assert "none" in strip.effects.text()


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
    from automap.window import AutomapWindow
    mapper = Automapper(target, maps or {}, area=area)
    return AutomapWindow(mapper, drive=False)


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


def test_the_tab_shows_the_party_beside_the_map(app, tmp_path, monkeypatch):
    save0, save1 = captured()
    window = make_window(app, tmp_path, monkeypatch,
                         MemoryTarget({0x4900: save0, 0x8300: save1}))
    for _ in range(window.LIVE_EVERY):
        window.tick()
    assert window.snapshot is not None
    assert window.roster.cards[0].name.text() == "BRUTUS"
    assert window.strip.clock.text() == "0:01"
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
    assert kind.name == "wyvern" and kind.icon == "location-dot"
    assert Note("here", "wyvern").icon == "location-dot"


def test_junk_in_a_notes_file_costs_only_the_junk(tmp_path, monkeypatch):
    """The file is hand-editable by design, so half of one beats none."""
    state = _area(tmp_path, monkeypatch)
    path = state.notes_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"notes": {"1,1": 42, "nowhere": ["x"],
                                          "2,2": [{"type": "locked"}]}}))
    state.load_notes()
    assert list(state.notes) == [(2, 2)]


def test_forgetting_squares_keeps_the_notes(tmp_path, monkeypatch):
    """`--forget ALL` clears exploration and leaves every note untouched."""
    from automap.__main__ import forget
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


def test_the_encounter_note_is_the_one_glyph_we_do_not_draw():
    """U+2694 is Donald's choice and it is a **font** character, so what it
    looks like is the platform's. Here it resolves monochrome; on Windows and
    macOS the same code point is commonly the colour emoji. Pinned so that a
    later "tidy-up" into a path is a deliberate decision rather than a
    silent one -- see `docs/109-icon-choices.md`."""
    assert icons.TEXT_GLYPHS == {"crossed-swords": "\u2694"}
    assert notemod.BY_NAME["encounter"].icon == "crossed-swords"
    assert icons.is_text("crossed-swords")
    assert "crossed-swords" not in icons.ICONS


def test_the_two_icons_that_were_ours_are_gone():
    """`chest` and `swords` were drawn here because Font Awesome Free has no
    sword and a filled rectangle reads as terrain. Both were replaced --
    `gem` regular and U+2694 -- and an unused drawing left in the table is a
    thing a later note will pick up by accident."""
    assert "chest" not in icons.ICONS
    assert "swords" not in icons.ICONS


def test_the_gem_survives_a_map_cell(app):
    """The Treasure note, in Font Awesome's **regular** weight: an outline,
    which is the whole reason Donald picked it over the solid. An outline is
    the shape most at risk of coming apart, so it is measured rather than
    eyeballed -- one connected silhouette, and the table facet still paper.
    `docs/109-icon-choices.md` carries the counts at 13 and 26."""
    from PyQt6.QtGui import QColor, QImage, QPainter

    from ui.iconpaint import draw_icon

    size = NOTE_SIZE
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("white"))
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw_icon(p, "gem", 0, 0, size, QColor("black"))
    p.end()

    ink = [[QColor(image.pixel(x, y)).lightness() < 128 for x in range(size)]
           for y in range(size)]
    seen = [[False] * size for _ in range(size)]
    pieces = []
    for y in range(size):
        for x in range(size):
            if ink[y][x] and not seen[y][x]:
                stack, count = [(x, y)], 0
                seen[y][x] = True
                while stack:
                    cx, cy = stack.pop()
                    count += 1
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            nx, ny = cx + dx, cy + dy
                            if (0 <= nx < size and 0 <= ny < size
                                    and ink[ny][nx] and not seen[ny][nx]):
                                seen[ny][nx] = True
                                stack.append((nx, ny))
                pieces.append(count)
    assert len(pieces) == 1, f"the gem came apart into {sorted(pieces)}"
    # The table -- the big facet under the crown -- is the hole that carries
    # the reading. Dead centre of the box is inside it.
    middle = QColor(image.pixel(size // 2, int(size * 0.62))).lightness()
    assert middle > 200, f"the gem filled in: lightness {middle}"


def test_no_icon_leaves_the_640_box():
    """`render.py` places a note by its box, not by its ink: an icon that
    overhangs lands on a wall. See `test_a_note_never_lands_on_a_wall`."""
    for name in icons.ICONS:
        x0, y0, x1, y1 = icons.extent(name)
        assert 0 <= x0 and 0 <= y0 and x1 <= icons.BOX and y1 <= icons.BOX, \
            f"{name} is {x0},{y0}..{x1},{y1}"


def test_ours_and_font_awesome_do_not_share_a_name():
    """`ICONS` merges the two dicts, so a repeated name would silently replace
    what the map draws -- and the licence line differs between them."""
    assert not set(icons.OURS) & set(icons.FONT_AWESOME)


def test_the_hood_keeps_its_face(app):
    """The thief's hood is `location-dot`'s argument applied deliberately: one
    solid silhouette, one hole. Drawn at 13px the face must still be paper --
    odd-even fill, or a subpath wound the same way as the cowl, fills it in and
    leaves a bell. See `docs/109-icon-choices.md`."""
    from PyQt6.QtGui import QColor, QImage, QPainter

    from ui.iconpaint import draw_icon

    image = QImage(13, 13, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("white"))
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw_icon(p, "hood", 0, 0, 13, QColor("black"))
    p.end()

    # The face sits a little above the middle; the shoulders below it are ink.
    face = QColor(image.pixel(6, 5)).lightness()
    shoulder = QColor(image.pixel(6, 10)).lightness()
    assert face > 200, f"the face filled in: lightness {face}"
    assert shoulder < 80, f"the shoulders are not ink: lightness {shoulder}"


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
    """`location-dot` was chosen over `location-pin` because it is a solid
    silhouette with one hole, and the hole is what survives 12px. That needs
    two subpaths and winding fill -- odd-even would fill the hole in."""
    from PyQt6.QtCore import Qt as _Qt

    from ui.iconpaint import painter_path
    assert sum(1 for c in icons.commands("location-dot") if c[0] == "M") == 2
    assert painter_path("location-dot").fillRule() == _Qt.FillRule.WindingFill


def test_a_square_with_three_notes_draws_one_icon_and_a_count():
    prims = list(note_primitives({(2, 3): [Note("a", "encounter"),
                                           Note("b", "treasure"),
                                           Note("c")]}))
    glyphs = [p for p in prims if isinstance(p, Glyph)]
    labels = [p for p in prims if isinstance(p, Label)]
    assert [g.name for g in glyphs] == ["crossed-swords"]   # the first only
    assert [(lab.text, lab.kind) for lab in labels] == [("3", "note-count")]


def test_the_note_count_stays_inside_its_own_cell():
    """It used to hang off the bottom-right of the icon, which put it outside
    the square as soon as the icon grew from 13 to `NOTE_SIZE`. It is placed
    against the cell now, and `NOTE_INSET` keeps it off the 3px wall stroke."""
    from automap.render import NOTE_INSET

    (label,) = [p for p in note_primitives({(2, 3): [Note("a"), Note("b")]})
                if isinstance(p, Label)]
    left, top = MARGIN + 2 * CELL, MARGIN + 3 * CELL
    # `(x, y)` is the text's bottom right corner.
    assert label.x == left + CELL - NOTE_INSET
    assert label.y == top + CELL - NOTE_INSET
    assert left < label.x - COUNT_SIZE and label.y - COUNT_SIZE > top


def test_a_note_and_the_party_marker_share_one_square_marker_on_top():
    """At 13 the note sat in a corner and the two never met. At `NOTE_SIZE` the
    note is most of the square, so on the square the party is standing on one
    of them is underneath -- and it is the note. Where the party is is the one
    thing on this map that must not be in doubt."""
    from automap import window as windowmod

    source = inspect.getsource(windowmod.MapCanvas)
    notes = source.index("note_primitives(st.notes)")
    party = source.index("party_marker(st.x")
    assert notes < party, "the note is drawn over the party marker"


@game_disks
def test_a_note_never_lands_on_a_wall():
    """Checked on GEO14, the densest map we have: a note that hides a wall has
    made the map worse, and the map's job is the walls."""
    slums = Geo.from_bytes(game_file("GEO14"))
    walls = [p for p in map_primitives(slums) if isinstance(p, Line)]
    every = {(x, y): [Note("x", "danger")]
             for y in range(GRID) for x in range(GRID)}
    for glyph in note_primitives(every):
        x0, y0, x1, y1 = icons.extent(glyph.name)
        scale = glyph.size / icons.BOX
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
    assert icons.path_data("lock") in svg


def test_the_svg_export_carries_the_notes(new_phlan):
    svg = to_svg(new_phlan, notes={(1, 1): [Note("a", "person"),
                                            Note("b", "done")]})
    assert icons.path_data("user") in svg
    assert 'text-anchor="end"' in svg and ">2<" in svg


# --- the roster's new lines -------------------------------------------------

def _character(**kw):
    fields = dict(slot=0, name="BRUTUS", classes=(), level=1, armour_class=9,
                  thac0=18, hp=11, hp_max=11, experience=0)
    fields.update(kw)
    return live.Character(**fields)


def test_a_card_shows_what_is_readied_and_nothing_else(app):
    from automap.panel import CharacterCard
    card = CharacterCard()
    card.show_character(_character(readied=("BANDED MAIL", "SHIELD",
                                            "LONG SWORD")))
    assert card.readied_items == ("BANDED MAIL", "SHIELD", "LONG SWORD")
    assert "BANDED MAIL" in card.readied.text()
    assert card.readied.toolTip().splitlines()[-1] == "LONG SWORD"


def test_a_character_with_nothing_readied_gets_a_blank_line(app):
    """The absence is the information, and the word "none" is not. The line
    stays, so the cards below it do not shift when a sword is put away."""
    from automap.panel import CharacterCard
    card = CharacterCard()
    card.show_character(_character(readied=("LONG SWORD",)))
    tall = card.sizeHint().height()
    card.show_character(_character())
    assert card.readied.text() == ""
    assert card.sizeHint().height() == tall


def test_a_long_readied_list_is_elided_and_kept_whole_in_the_tooltip(app):
    from automap.panel import CARD_WIDTH, CharacterCard
    card = CharacterCard()
    items = tuple(f"BANDED MAIL +{n}" for n in range(6))
    card.show_character(_character(readied=items))
    assert card.readied.text().endswith("…")
    assert len(card.readied.toolTip().splitlines()) == 6
    from PyQt6.QtGui import QFontMetrics
    assert QFontMetrics(card.readied.font()).horizontalAdvance(
        card.readied.text()) <= CARD_WIDTH


@game_disks
def test_readied_items_are_read_from_the_item_block():
    """The editor's inventory table shows exactly this; the card shows the
    readied half of it."""
    from por.savegame import SaveGame0
    save = SaveGame0.from_prg((FIXTURES / "party6_after_combat.bin").read_bytes())
    names = live.item_names()
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
    from por.savegame import SaveGame0
    save = SaveGame0.from_prg((FIXTURES / "party6_after_combat.bin").read_bytes())
    assert live.readied(save.to_bytes(), 5, None) == ()


def test_the_class_is_written_out_and_not_left_to_an_icon(app):
    """The roster's class icons were removed -- they carried little at 13px --
    so the text is the whole statement, and it is what a screen reader gets."""
    from automap.panel import CharacterCard
    card = CharacterCard()
    two = (live.ClassProgress("magic-user", 1, 0, 0.0, 2500),
           live.ClassProgress("thief", 1, 0, 0.0, 1250))
    card.show_character(_character(classes=two))
    assert card.klass.text().startswith("magic-user/thief")
    assert not hasattr(card, "class_icons")


# --- the notes panel and the popover ----------------------------------------

def test_the_notes_panel_lists_every_note_and_points_at_the_square(app):
    from automap.panel import NotesPanel
    panel = NotesPanel()
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
    px = MARGIN + 3 * CELL + 2
    py = MARGIN + 4 * CELL + 2
    assert window.canvas.tooltip_at(px, py) == (
        "Encounter - dueling pairs\nLocked")
    assert window.canvas.tooltip_at(MARGIN + 8 * CELL, py) is None


def test_right_clicking_a_square_offers_edit_and_delete(app, tmp_path,
                                                        monkeypatch):
    window = make_window(app, tmp_path, monkeypatch, None, area="GEO14")
    window.state.add_note(3, 4, Note("locked, come back", "locked"))
    window.state.add_note(3, 4, Note("cleared", "done"))
    entries = window.note_menu_entries(3, 4)
    assert [text for text, _ in entries] == [
        "Edit  Locked - locked, come back",
        "Delete  Locked - locked, come back",
        "Edit  Done - cleared",
        "Delete  Done - cleared",
        "Add another note"]
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


# --- the commissions panel, wired -------------------------------------------

def test_the_tab_shows_the_commissions(app, tmp_path, monkeypatch):
    save0, save1 = captured()
    window = make_window(app, tmp_path, monkeypatch,
                         MemoryTarget({0x4900: save0, 0x8300: save1}))
    for _ in range(window.LIVE_EVERY):
        window.tick()
    assert window.commissions.completed.text().startswith(
        "Commissions completed:")
    assert window.commissions.heading.text() == "Commissions"


def test_a_poll_that_reads_nothing_leaves_the_commissions_alone(app, tmp_path,
                                                                monkeypatch):
    """Plot flags do not change while the game is in a menu, and a blanked
    quest log every time somebody opens one would be a flicker."""
    save0, save1 = captured()
    machine = MemoryTarget({0x4900: save0, 0x8300: save1})
    window = make_window(app, tmp_path, monkeypatch, machine)
    for _ in range(window.LIVE_EVERY):
        window.tick()
    before = window.commissions.completed.text()
    machine.memory[0x4900] = bytes(0x1C00)
    for _ in range(window.LIVE_EVERY):
        window.tick()
    assert window.commissions.completed.text() == before


# --- the action buttons -----------------------------------------------------

def test_with_nothing_attached_the_buttons_are_disabled_not_inert(app):
    from automap.actionbar import ActionBar
    bar = ActionBar()
    bar.attach(None)
    assert not any(b.isEnabled() for b in bar.buttons.values())
    assert bar.buttons["heal"].toolTip() == "no emulator attached"


def test_the_buttons_are_laid_out_in_the_two_rows_donald_asked_for(app):
    """Donald's order, and the labels in the American spelling he asked for
    three times. `actions()` is the reading order and `COLUMNS` breaks it into
    rows, so this pins both at once."""
    from automap.actionbar import COLUMNS, ActionBar
    bar = ActionBar()
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
        ["Identify all items", "Turn quickfight off"],
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
    bar = ActionBar()
    bar.attach(MemoryTarget({0x6E11: b"\x02"}))
    assert bar.buttons["heal"].isEnabled()            # legal mid-fight
    assert not bar.buttons["identify"].isEnabled()
    assert "$6E11 is 2" in bar.buttons["identify"].toolTip()


def test_the_whole_row_costs_one_read_of_the_mode_flag(app):
    """Six actions asking `legality` is six round trips otherwise, and each
    hands the emulation ~14.3 ms of extra emulated time."""
    from automap.actionbar import ActionBar
    machine = MemoryTarget({0x6E11: b"\x00"})
    bar = ActionBar()
    bar.attach(machine)
    assert [r for r in machine.reads if r[0] == 0x6E11] == [(0x6E11, 1)]


def test_an_action_that_carries_a_confirm_asks_first(app):
    from automap.actionbar import ActionBar
    machine = MemoryTarget({0x6E11: b"\x00"})
    said = []
    bar = ActionBar(say=lambda text, detail="", alarm=False: said.append(text))
    asked = []
    bar.ask = lambda question: asked.append(question) or False
    bar.attach(machine)
    identify = next(a for a in bar.actions if a.name == "identify")
    assert bar.run(identify) is None
    assert asked and "no way to undo" in asked[0]
    assert said == []                       # refused before anything was read

    bar.ask = lambda question: True
    outcome = bar.run(identify)
    # The result is a line in the messages panel, not a pop-up to dismiss.
    assert outcome is not None
    assert said == [f"identify all items: {outcome.message}"]
    assert "identify all items:" in bar.note.text()


def test_the_quickfight_watcher_is_off_until_it_is_asked_for(app):
    """It writes to a running machine on an edge nobody asked for, so it has
    to be turned on deliberately."""
    from automap.actionbar import ActionBar
    save0, save1 = captured()
    machine = MemoryTarget({0x4900: save0, 0x8300: save1, 0x6E11: b"\x02"})
    bar = ActionBar()
    assert not bar.watch_box.isChecked() and not bar.watcher.enabled
    assert bar.watch(machine) is None                  # in a fight

    bar.watch_box.setChecked(True)
    assert bar.watcher.enabled
    assert bar.watch(machine) is None                  # still in the fight
    machine.memory[0x6E11] = b"\x00"
    outcome = bar.watch(machine)                       # the 2-to-not-2 edge
    assert outcome is not None and outcome.ok
    assert "quickfight" in bar.note.text()
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


def test_the_font_awesome_attribution_travels_with_the_icons():
    """CC BY 4.0's one obligation. The paths are lifted from `svgs-full`, so
    the notice has to be carried by us -- copying a path out of the `.svg`
    leaves its inline comment behind."""
    from wish.about import TEXT
    root = pathlib.Path(__file__).resolve().parent.parent
    assert "Font Awesome" in TEXT and "CC BY 4.0" in TEXT
    # `encoding=` is not optional: the default is the locale codec, which is
    # cp1252 on the Windows runners, and the README has an em dash in it.
    assert "Font Awesome" in (root / "README.md").read_text(encoding="utf-8")
    assert (root / "docs/licences/fontawesome-LICENSE.txt").exists()
    assert "Font Awesome" in icons.__doc__


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


def test_a_second_note_on_the_square_is_listed_with_its_own_delete(
        app, tmp_path, monkeypatch):
    window = make_window(app, tmp_path, monkeypatch, None, area="GEO14")
    window.state.add_note(6, 2, Note("dueling pairs", "encounter"))
    window.state.add_note(6, 2, Note("needs a thief", "treasure"))
    window.edit_note(6, 2)
    pop = window._popover
    assert pop.field.text() == "dueling pairs"          # the first is open
    others = [b.text() for b in pop.findChildren(QPushButton)]
    assert "Treasure - needs a thief" in others         # the second is listed
    pop.delete(1)
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
    assert window.messages.lines()[-1].endswith(
        f"heal the party: {outcome.message}")


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
    """The two conditions the record actually tells us, and no others: the
    effect ids at $4900 are a code space nothing in the project names."""
    from automap.panel import CharacterCard
    card = CharacterCard()
    card.show_character(_character(hp=0))
    assert card.conditions.names == ("skull",)
    assert "dead or dying" in card.conditions.toolTip()
    card.show_character(_character(hp=4, levels_drained=2))
    assert card.conditions.names == ("arrow-down-long",)
    assert "drained 2 levels" in card.conditions.toolTip()
    card.show_character(_character())
    assert card.conditions.names == ()


def test_the_quickfight_badge_appears_only_when_the_bit_is_set(app):
    """Roster block `+0x0C` bit 7, CONFIRMED. Its own row under the readied
    line and right-aligned -- not the conditions row, which is what has
    happened *to* a character rather than what their player chose."""
    from automap.panel import CharacterCard
    card = CharacterCard()
    card.show_character(_character(quickfight=True))
    assert card.quickfight.names == ("person-running",)
    assert card.quickfight.toolTip() == "Quickfight"
    # Not in with the conditions, and not shifting the card when it goes.
    assert card.conditions.names == ()
    tall = card.sizeHint().height()
    card.show_character(_character())
    assert card.quickfight.names == ()
    assert card.sizeHint().height() == tall


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


def test_the_running_figure_is_font_awesome_verbatim_and_reads_at_13px(app):
    """Lifted from `svgs-full/solid/person-running.svg`, not redrawn: three
    subpaths -- head, body, trailing arm -- which is what a runner looks like
    and is why it passes the 13px rule despite not being one silhouette."""
    from PyQt6.QtGui import QColor, QImage, QPainter

    from ui.iconpaint import draw_icon
    assert "person-running" in icons.FONT_AWESOME
    assert sum(1 for c in icons.commands("person-running") if c[0] == "M") == 3

    size = 13
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("white"))
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw_icon(p, "person-running", 0, 0, size, QColor("black"))
    p.end()
    ink = sum(1 for y in range(size) for x in range(size)
              if QColor(image.pixel(x, y)).lightness() < 190)
    # 34 pixels of ink at 13px, measured. A glyph that has come apart into
    # nothing or filled into a blob fails here rather than on somebody's card.
    assert 24 <= ink <= 60, ink


def test_the_effect_table_is_still_shown_by_number():
    """The two lists share one namespace -- `LIBRARY $4028` reads the arrays
    and falls back to the character's own slots -- so `por/traits.py` could
    name an effect. It does not here: the strip beside the map is a row of
    running spells and a PROBABLE name in it reads as a fact.
    `docs/133-active-effects.md` is where the naming is being designed."""
    effect = live.Effect(slot=0, id=64, owner=0, duration=3, magnitude=0)
    assert effect.label == "effect 64"
    from por import traits
    assert traits.describe(64).startswith("melee poison")   # a trait, not this


def book_flags() -> bytes:
    """The flag block from the shipped unplayed save, as bytes."""
    from por import commissions as book
    save0 = (FIXTURES / "savedgame0.bin").read_bytes()[2:]
    return book.flags(save0).to_bytes()


def test_typing_a_note_is_not_eaten_by_the_shortcuts(app, tmp_path,
                                                     monkeypatch):
    """`N` opens a note and `E`, `T`, `P`... pick its type, so both could take
    a letter out of the words being typed. Neither does: the popover holds the
    keyboard, and the type letters are ignored while the field has focus."""
    from PyQt6.QtTest import QTest
    window = make_window(app, tmp_path, monkeypatch, None, area="GEO14")
    window.show()
    window.edit_note(3, 3)
    pop = window._popover
    pop.field.setFocus()
    QTest.keyClicks(pop.field, "north gate")
    assert pop.field.text() == "north gate"
    assert window._popover is pop            # no second popover opened
    assert pop.chosen == "note"              # and no type was picked by "e"
    window.close()
