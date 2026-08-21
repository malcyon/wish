"""Tests for the live automapper's model, geometry and party panel.

Nothing here needs an emulator or a display: `ReplayTarget` and `MemoryTarget`
stand in for VICE, `render.py` emits primitives rather than painting them, and
the widgets run offscreen. A save file *is* a captured snapshot of the two
ranges the live view reads, so the fixtures under `tests/fixtures` serve as
recorded machines.
"""

import os
import pathlib

import pytest
from gamedata import game_file

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from automap.area import Fingerprint
from automap.render import (
    CELL,
    Line,
    Poly,
    Rect,
    edge_primitives,
    map_primitives,
    merged_edge,
    party_marker,
    to_svg,
)
from automap.state import Automapper, AutomapState, Exploration
from automap.target import Fix, ReplayTarget
from por.geo import (
    EAST,
    GRID,
    LOCKED,
    NORTH,
    PASSABLE,
    SOLID,
    SOUTH,
    WEST,
    WIZARD_LOCKED,
    Geo,
    load_geo_files,
)

DISKS = "/home/donald/c64/Pool of Radiance Disks"
FIXTURES = pathlib.Path(__file__).parent / "fixtures"
game_disks = pytest.mark.skipif(not pathlib.Path(f"{DISKS}/POOL3.D64").exists(),
                                reason="needs the game disks")


@pytest.fixture
def geo():
    return Geo.from_bytes(game_file("GEO04"))


@pytest.fixture
def new_phlan():
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
    mapper.state.notes[(4, 4)] = "fortune teller"
    mapper.state.save_notes()

    again = Automapper(ReplayTarget([]), {"GEO00": new_phlan}, area="GEO00")
    assert again.state.notes[(4, 4)] == "fortune teller"
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


def test_the_loaded_files_start_collapsed(app):
    from automap.panel import BottomStrip
    strip = BottomStrip()
    strip.show_state(AutomapState(), live.snapshot_from_bytes(*captured()))
    # isHidden, not isVisible: nothing here is shown on screen, so isVisible is
    # False for the whole strip either way and would prove nothing.
    assert strip.loaded.isHidden()
    strip.toggle.setChecked(True)
    assert not strip.loaded.isHidden()
    assert "loaded files:" in strip.loaded.text()


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

    # Nothing listening at all: refused, and that is the ordinary case.
    with pytest.raises(NotConnected) as gone:
        ViceTarget(host="127.0.0.1", port=port, timeout=0.5)
    assert not isinstance(gone.value, MonitorBusy)


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
    # Left of the map, and the map no longer centred in the frame. The map is
    # the stack of two canvases now -- the area map and the combat map.
    grid = window.centralWidget().layout()
    assert grid.indexOf(window.roster) < grid.indexOf(window.stack)
    assert grid.getItemPosition(grid.indexOf(window.roster))[:2] == (0, 0)
    assert grid.getItemPosition(grid.indexOf(window.stack))[:2] == (0, 1)
    assert grid.getItemPosition(grid.indexOf(window.strip))[0] == 1
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
