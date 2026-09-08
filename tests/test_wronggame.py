from __future__ import annotations

"""The window checks the machine is running the game it thinks it is (#21).

The title used to be a chain of guesses -- the open save, then the Game
directory setting, then `games.DEFAULT` -- and nothing ever contradicted it. So
attaching to a Curse of the Azure Bonds session with the setting pointing at
Pool of Radiance left the window believing Pool of Radiance, and the two
per-title safeguards built on that belief both failed open: Level up would have
written Pool of Radiance's hit dice and thresholds into a Curse character, and
Fast Travel would have offered Pool of Radiance's thirty areas and written its
disk numbers into a Curse machine.

**Validation, not identification.** The window never asks "which of the six
titles is this?" -- that needs every title's disks, and fails *open* on a title
whose disks are nowhere, which is most of them for most players. It asks "is
this ours?", which needs only the disks it already has, and fails *closed*:
anything it cannot recognise as one of its own maps, but which is unmistakably
a Gold Box map, takes the controls off.

Three answers, and only the middle one disables anything:

* `OURS` -- the block at `$0400` is one of the maps we hold;
* `NOT_OURS` -- it is a Gold Box map and it is none of them;
* `UNKNOWN` -- it is not a map at all, which is the ordinary state at the title
  screen, mid-load and in combat, where `SQRPACI` holds the same page.

Nothing here needs an emulator or the game disks: `MemoryTarget` is a machine
and the maps are generated from the format we documented. The two tests that
measure the thresholds against real game data read the player's own disks and
skip without them.
"""


import os
import pathlib

import pytest
from gamedata import curse_dir, disk_dir, game_file, synthetic_geo

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from automap import area
from automap.area import (
    NEAR_ENOUGH,
    NOT_OURS,
    OURS,
    RESIDENT_GEO,
    UNKNOWN,
    ResidentGeo,
    looks_like_a_map,
)
from automap.state import Automapper
from automap.target import MemoryTarget
from automap.window import WRONG_GAME
from goldbox import games
from goldbox.geo import (
    ATTRIBUTES,
    BARRIERS,
    GEO_SIZE,
    GRID,
    SOLID,
    WALLS_NORTH_EAST,
    WALLS_SOUTH_WEST,
    Geo,
)

POOL = games.POOL_OF_RADIANCE.title
CURSE = games.CURSE_OF_THE_AZURE_BONDS.title
SILVER = games.SECRET_OF_THE_SILVER_BLADES.title

#: The fourth Realms title, which `goldbox/games.py` has no descriptor for because
#: **the C64 never got it** (`docs/138` §0). It can only ever reach the window
#: as a title somebody typed, so what matters is that a title with no
#: descriptor behind it is guarded exactly like one that has.
DARKNESS = "Pools of Darkness"


def walled_geo(art: int = 1, rooms: int = 4) -> Geo:
    """A generated map whose walls are drawn from both sides, as real ones are.

    `gamedata.synthetic_geo` exercises the *decoder* and deliberately carries
    one-sided art; what is wanted here is a map that reads like the ones the
    game ships, so the wall on the shared edge of two squares is written into
    both squares. `art` and `rooms` are what make one of these a different map
    from another.
    """
    planes = bytearray(synthetic_geo())
    for y in range(GRID):
        for x in range(GRID):
            at = y * GRID + x
            if x % rooms == 0 and x:
                planes[WALLS_SOUTH_WEST + at] |= art          # west of (x,y)
                planes[WALLS_NORTH_EAST + at - 1] |= art      # east of (x-1,y)
                planes[BARRIERS + at] |= SOLID << 6
            if y % rooms == 0 and y:
                planes[WALLS_NORTH_EAST + at] |= art << 4     # north of (x,y)
                planes[WALLS_SOUTH_WEST + at - GRID] |= art << 4
    return Geo(bytes(planes))


def a_few_bytes_different(geo: Geo, how_many: int) -> Geo:
    """The same map with `how_many` bytes rewritten, as a running game may.

    The attributes plane, because that is the one a running game plausibly
    writes -- script flags, an encounter cleared -- and because rewriting the
    barrier plane instead would destroy the reciprocity that makes the block a
    map at all, which is a different question from how far it has drifted.
    """
    raw = bytearray(geo.to_bytes())
    for i in range(how_many):
        raw[ATTRIBUTES + i] ^= 0x1F
    return Geo(bytes(raw))


def playing(resident: Geo, status: str = "E 16:48  5,2") -> MemoryTarget:
    """A machine drawing the game's own status line, screen at `$CC00`.

    The path a real session takes: `party_fix` never reaches the memory
    fallback, and so `_running` never reaches the resident block on its own.
    """
    from automap.screen import SCREEN_COLS
    codes = bytes((ord(c) - 64) & 0x7F if c.isalpha() else ord(c)
                  for c in status.ljust(SCREEN_COLS).upper())
    return MemoryTarget({
        0xD011: bytes([0x1B]), 0xD018: bytes([0x30]), 0xDD00: bytes([0x00]),
        0xCC00 + 14 * SCREEN_COLS: codes,
        RESIDENT_GEO: resident.to_bytes(),
    })


def machine(resident: Geo | bytes | None = None,
            position=(4, 5, 0)) -> MemoryTarget:
    """A C64 with a block at `$0400` and no status line.

    The screen registers are a booted machine's, so `automap.screen` finds no
    game status line on row 14 and the fix falls back to the engine's own
    position triple. The block at `$0400` is the whole of the evidence.
    """
    blocks = {0xD011: bytes([0x1B]), 0xD018: bytes([0x15]), 0xDD00: bytes([0x17]),
              games.DEFAULT.live_position: bytes(position)}
    if resident is not None:
        blocks[RESIDENT_GEO] = (resident if isinstance(resident, bytes)
                                else resident.to_bytes())
    return MemoryTarget(blocks)


@pytest.fixture
def notes_elsewhere(tmp_path, monkeypatch):
    """Notes and explored squares under a temporary directory, never the user's."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))


@pytest.fixture
def ours() -> dict[str, Geo]:
    return {"GEO00": walled_geo(art=1), "GEO01": walled_geo(art=2)}


@pytest.fixture
def theirs() -> Geo:
    """A well-formed map that is nobody's in `ours`."""
    return walled_geo(art=5, rooms=3)


def polled(mapper, times: int = 24):
    for _ in range(times):
        mapper.poll()
    return mapper


# --- what a block at $0400 is worth ------------------------------------------

def test_our_own_map_is_ours(ours):
    target = machine(ours["GEO01"])
    assert ResidentGeo(target).verdict(ours) == (OURS, "GEO01")


def test_somebody_elses_map_is_not_ours(ours, theirs):
    assert ResidentGeo(machine(theirs)).verdict(ours) == (NOT_OURS, None)


def test_a_booting_machine_says_nothing(ours):
    """1024 zeroes reciprocate perfectly -- every square agrees with its
    neighbour that there is nothing there -- so reciprocity alone would read a
    cold machine as a map, and a sparse map is within any byte tolerance of
    it."""
    assert ResidentGeo(machine(bytes(GEO_SIZE))).verdict(ours) == (UNKNOWN, None)
    assert looks_like_a_map(Geo(bytes(GEO_SIZE))) is False


def test_a_page_that_is_not_a_map_says_nothing(ours):
    """In combat the page holds `SQRPACI` -- a tile remap, the combat parameter
    block and code -- which scores 0.285 read as a map."""
    junk = bytes((i * 37 + (i >> 3)) & 0xFF for i in range(GEO_SIZE))
    assert ResidentGeo(machine(junk)).verdict(ours) == (UNKNOWN, None)


def test_the_game_writing_into_the_block_is_still_our_map(ours):
    """The exact match is the fast path, not the only one. If the running game
    writes into the map it is drawing, an exact test would read a legitimate
    session as somebody else's game and take the controls off a player who has
    done nothing wrong."""
    scribbled = a_few_bytes_different(ours["GEO00"], NEAR_ENOUGH - 1)
    assert ResidentGeo(machine(scribbled)).verdict(ours) == (OURS, "GEO00")


def test_a_block_that_has_drifted_too_far_is_not_ours(ours):
    far = a_few_bytes_different(ours["GEO00"], NEAR_ENOUGH + 40)
    assert ResidentGeo(machine(far)).verdict(ours) == (NOT_OURS, None)


def test_with_no_maps_at_all_there_is_no_signature(theirs):
    """No disks means nothing to check against, so nothing may be concluded --
    least of all that the game is wrong."""
    assert ResidentGeo(machine(theirs)).verdict({}) == (UNKNOWN, None)


# --- the mapper --------------------------------------------------------------

@pytest.mark.parametrize("title", [POOL, CURSE, SILVER, DARKNESS])
def test_the_machine_contradicts_the_title_whatever_it_is(title, ours, theirs,
                                                          notes_elsewhere):
    """One check per believed title, not one per ordered pair of titles: the
    question is only ever whether this machine is running *this* game."""
    mapper = polled(Automapper(machine(theirs), ours, title=title))
    assert mapper.title_check is NOT_OURS


@pytest.mark.parametrize("title", [POOL, CURSE, SILVER, DARKNESS])
def test_a_machine_running_our_own_game_is_left_alone(title, ours,
                                                      notes_elsewhere):
    mapper = polled(Automapper(machine(ours["GEO00"]), ours, title=title))
    assert mapper.title_check is OURS
    assert mapper.state.area == "GEO00"


def test_one_odd_reading_does_not_take_the_controls_off(ours, theirs,
                                                        notes_elsewhere):
    """A control taken away by a single bad read would be a worse bug than the
    one this is for."""
    mapper = Automapper(machine(theirs), ours, title=POOL)
    mapper._contradicted()
    assert Automapper.CONTRADICTIONS_BEFORE_REFUSING > 1
    assert mapper.title_check is not NOT_OURS


def test_nothing_is_recorded_once_the_game_is_the_wrong_one(ours, theirs,
                                                            notes_elsewhere):
    """Their party on their map would otherwise go into our title's explored
    squares and our title's notes file."""
    mapper = polled(Automapper(machine(theirs), ours, title=POOL, area="GEO00"))
    before = set(mapper.state.exploration.seen)
    for _ in range(10):
        assert mapper.poll() is False
    assert mapper.state.exploration.seen == before


def test_a_session_drawing_its_status_line_is_checked_too(ours, theirs,
                                                          notes_elsewhere):
    """The real path. A status-line fix proves a Gold Box game is running all
    by itself, so nothing else ever reads the map block -- and if the check
    hung off that proof it would never run in an actual session."""
    mapper = polled(Automapper(playing(theirs), ours, title=POOL))
    assert mapper.title_check is NOT_OURS


def test_the_refusal_lifts_on_a_status_line_session_as_well(ours, theirs,
                                                            notes_elsewhere):
    target = playing(theirs)
    mapper = polled(Automapper(target, ours, title=POOL))
    assert mapper.title_check is NOT_OURS
    target.memory[RESIDENT_GEO] = ours["GEO00"].to_bytes()
    polled(mapper)
    assert mapper.title_check is OURS


def test_only_our_own_map_lifts_the_refusal(ours, theirs, notes_elsewhere):
    """Loading the right game into the emulator that is already open fixes the
    problem, and a positive identification is the only thing that says so.
    "Cannot tell" -- a menu, a fight, the title screen -- never lifts it, which
    is the whole point of the third state."""
    target = machine(theirs)
    mapper = polled(Automapper(target, ours, title=POOL))
    assert mapper.title_check is NOT_OURS

    target.memory[RESIDENT_GEO] = bytes(GEO_SIZE)       # a machine mid-load
    polled(mapper)
    assert mapper.title_check is NOT_OURS

    target.memory[RESIDENT_GEO] = ours["GEO00"].to_bytes()
    polled(mapper)
    assert mapper.title_check is OURS


def test_pointing_the_setting_at_the_other_disks_clears_it(ours, theirs,
                                                           notes_elsewhere):
    """Changing the Game directory is how a player fixes this, so it must not
    stay latched afterwards."""
    mapper = polled(Automapper(machine(theirs), ours, title=POOL))
    mapper.use_maps({"GEO33": theirs}, title=CURSE)
    assert mapper.title_check is UNKNOWN
    polled(mapper)
    assert mapper.title_check is OURS
    assert mapper.state.area == "GEO33"


def test_a_new_connection_starts_with_no_opinion(ours, theirs, notes_elsewhere):
    mapper = polled(Automapper(machine(theirs), ours, title=POOL))
    mapper.target = machine(bytes(GEO_SIZE))
    mapper.poll()
    assert mapper.title_check is UNKNOWN


# --- the window, which is where the safeguards are ---------------------------

@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def window_on(target, maps, title):
    from PyQt6.QtWidgets import QMainWindow

    from automap.window import AutomapBinding
    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    return AutomapBinding(root, Automapper(target, maps, title=title))


def ticked(window, times: int = 24):
    for _ in range(times):
        window.tick()
    return window


def test_both_refusals_fire_when_the_game_is_the_wrong_one(app, ours, theirs,
                                                           notes_elsewhere):
    """The acceptance test for #21: the setting says Pool of Radiance, the
    machine is running something else, and Level up and Fast Travel are the two
    things that must not believe the setting."""
    window = window_on(machine(theirs), ours, POOL)
    assert window.roster.levelling is True          # what the setting bought

    ticked(window)

    assert window.mapper.title_check is NOT_OURS
    assert window.roster.levelling is False
    assert window.fasttravel_bar.target is None
    assert window.fasttravel_bar.button.isEnabled() is False
    assert window.fasttravel_bar.back_button.isEnabled() is False


def test_every_write_button_goes_with_them(app, ours, theirs, notes_elsewhere):
    """Level up and Fast Travel are the two that refuse *by title*, but heal,
    store spells and identify write Pool of Radiance's addresses on every
    title (`docs/139` C16-C19), so a machine running another game is the worst
    place to leave them enabled."""
    window = ticked(window_on(machine(theirs), ours, POOL))
    assert not any(button.isEnabled()
                   for button in window.actions_bar.buttons.values())


def test_the_refusal_is_said_out_loud_in_donalds_words(app, ours, theirs,
                                                       notes_elsewhere):
    window = ticked(window_on(machine(theirs), ours, POOL))
    said = [line.split("  ", 1)[-1] for line in window.messages.lines()]
    assert WRONG_GAME in said
    assert said.count(WRONG_GAME) == 1              # not once per tick
    # It names neither game, so the detail has to be in the debug log.
    assert POOL not in WRONG_GAME


def test_the_controls_come_back_when_the_right_game_appears(app, ours, theirs,
                                                           notes_elsewhere):
    """Loading the right game into the emulator that is already open is the
    ordinary fix, and it must not need a restart of wish."""
    target = machine(theirs)
    window = ticked(window_on(target, ours, POOL))
    assert window.roster.levelling is False

    target.memory[RESIDENT_GEO] = ours["GEO00"].to_bytes()
    ticked(window)

    assert window.mapper.title_check is OURS
    assert window.roster.levelling is True
    assert window.fasttravel_bar.target is target


def test_the_window_says_nothing_when_the_disks_were_right(app, ours,
                                                           notes_elsewhere):
    window = ticked(window_on(machine(ours["GEO00"]), ours, POOL))
    assert WRONG_GAME not in [line.split("  ", 1)[-1]
                              for line in window.messages.lines()]
    assert window.roster.levelling is True
    assert window.mapper.title_check is OURS


def test_the_debug_log_carries_what_the_message_does_not(ours, theirs, caplog,
                                                         notes_elsewhere):
    """The message names neither the believed title nor what was seen, so the
    log has to name both and say where the observation came from."""
    import logging
    with caplog.at_level(logging.INFO, logger="wish.automap.state"):
        polled(Automapper(machine(theirs), ours, title=POOL))
    written = "\n".join(caplog.messages)
    assert POOL in written
    assert "$0400" in written
    assert str(len(ours)) in written


# --- the thresholds, against real game data ----------------------------------

def _maps_on(where, patterns) -> dict[str, bytes]:
    from goldbox.d64 import D64
    out: dict[str, bytes] = {}
    for pattern in patterns:
        for path in sorted(pathlib.Path(where).glob(pattern)):
            try:
                disk = D64.open(str(path))
            except Exception:
                continue
            for entry in disk.directory():
                name = bytes(entry.name).decode("latin1")
                if not name.startswith("GEO"):
                    continue
                try:
                    payload = disk.read_file(entry)
                except Exception:
                    continue
                if len(payload) in (GEO_SIZE, GEO_SIZE + 2):
                    out.setdefault(name, Geo.from_bytes(payload).to_bytes())
    return out


def _pages_on(where, patterns):
    """Every aligned 1024-byte page of every file that is not a map."""
    from goldbox.d64 import D64
    for pattern in patterns:
        for path in sorted(pathlib.Path(where).glob(pattern)):
            try:
                disk = D64.open(str(path))
            except Exception:
                continue
            for entry in disk.directory():
                name = bytes(entry.name).decode("latin1")
                if name.startswith("GEO"):
                    continue
                try:
                    body = disk.read_file(entry)[2:]
                except Exception:
                    continue
                for at in range(0, len(body) - GEO_SIZE + 1, GEO_SIZE):
                    yield name, at, body[at:at + GEO_SIZE]


def silver_dir():
    """Where Silver Blades' disks are, found the way `gamedata.disk_dir` finds
    Pool of Radiance's -- `tools.gamedisks` is the suite's own registry."""
    from tools import gamedisks
    return gamedisks.find("secret-of-the-silver-blades")


def _amiga_comspr(at: int = 5824) -> bytes | None:
    """One 1024-byte window of `COMSPR.TLB` off whichever Amiga disk has it.

    Both `CurseOfTheAzureBonds_A.adf` and `SecretOfTheSilverBlades_A.adf` carry
    a byte-identical copy; either will do.
    """
    from goldbox.amiga_adf import AmigaDisk
    from tools import gamedisks
    for root in gamedisks.candidates("amiga"):
        if not root.is_dir():
            continue
        for image in sorted(root.rglob("*.adf")):
            for where in ("/DISKA/COMSPR.TLB", "/DISK1/COMSPR.TLB"):
                try:
                    body = AmigaDisk.open(image).read_file(where)
                except Exception:
                    continue
                if len(body) >= at + GEO_SIZE:
                    return body[at:at + GEO_SIZE]
    return None


@pytest.mark.skipif(disk_dir() is None, reason="needs the game disks")
def test_no_page_of_the_players_own_disks_reads_as_a_map():
    """`NOT_OURS` is only ever said of a block that `looks_like_a_map`, so what
    that predicate lets through is the whole false-alarm risk. Measured against
    every 1024-byte page of every non-`GEO` file the three C64 titles ship --
    code, graphics, tables, saves.

    The suite takes one page per 1024 bytes and the disks it has; the whole
    sweep is 65383 windows at 64-byte steps across both platforms and belongs
    in `tools/geoplausible.py`, which takes minutes.
    """
    corpora = [(disk_dir(), ("POOL*.[dD]64",))]
    if curse_dir() is not None:
        corpora.append((curse_dir(), ("CURSE*.[dD]64",)))
    if silver_dir() is not None:
        corpora.append((silver_dir(), ("SILVER*.[dD]64",)))
    wrong = [f"{name}+{at}" for where, patterns in corpora
             for name, at, page in _pages_on(where, patterns)
             if looks_like_a_map(Geo(page))]
    assert wrong == [], f"{len(corpora)} title(s) swept"


@pytest.mark.skipif(not _amiga_comspr(), reason="needs the Amiga disks")
def test_the_amiga_block_that_sets_the_threshold_is_still_turned_away():
    """`COMSPR.TLB+5824` is the closest anything on any of these disks comes to
    passing, and it is what `MAP_WALL_ART_AGREEMENT` is set against.

    The whole sweep is the tool's job, but this one block is the margin: it
    agrees about its wall art 0.535 of the time against a threshold of 0.57,
    and it reuses its wall pairs 4.09 times against a threshold of 4.0 -- so
    the art clause is the only thing turning it away, and a change that
    loosened that clause by 7% would let it in.
    """
    block = _amiga_comspr()
    evidence = area.map_evidence(Geo(block))
    assert evidence.art_agreement == pytest.approx(0.535, abs=0.002)
    assert evidence.pair_reuse == pytest.approx(4.09, abs=0.01)
    assert evidence.pair_reuse > area.MAP_WALL_PAIR_REUSE
    assert looks_like_a_map(Geo(block)) is False


@pytest.mark.skipif(disk_dir() is None, reason="needs the game disks")
def test_every_map_the_automapper_loads_reads_as_a_map():
    """The other direction, and it used to be allowed to be imperfect.

    `looks_like_a_map` threw out `GEO02`, `GEO11`, `GEO12`, `GEO15` and
    `GEO20` -- five of the twenty-nine maps `automap.maps.load_maps` hands the
    window -- because it asked the two sides of a walled edge to agree about
    which wall-art number it is, and the format does not promise that: a wall
    may be a different picture from each side. `GEO20` agreed on 33 of 156
    (#436).

    This reads the maps through `load_maps`, which is the call the window
    itself makes, off whichever disks `tests/gamedata.disk_dir` finds.
    """
    from automap.maps import load_maps
    maps = load_maps(str(disk_dir()))
    assert len(maps) == 29, sorted(maps)
    rejected = sorted(name for name, geo in maps.items()
                      if not looks_like_a_map(geo))
    assert rejected == [], f"{len(rejected)} of {len(maps)} rejected: {rejected}"


@pytest.mark.skipif(curse_dir() is None, reason="needs the Curse disks")
def test_every_curse_map_reads_as_a_map():
    """Curse's `GEO33` was the sixth map the old threshold turned away."""
    maps = _maps_on(curse_dir(), ("CURSE*.[dD]64",))
    assert len(maps) == 16, sorted(maps)
    rejected = sorted(n for n, raw in maps.items()
                      if not looks_like_a_map(Geo(raw)))
    assert rejected == [], f"{len(rejected)} of {len(maps)} rejected: {rejected}"


@pytest.mark.skipif(silver_dir() is None, reason="needs the Silver Blades disks")
def test_every_silver_blades_map_reads_as_a_map():
    """Silver Blades is the title that showed `MAP_RECIPROCITY = 0.93` was
    fitted to a corpus that did not contain it: `GEO40` reciprocates 0.9229 and
    was turned away before the wall-art clause ever ran."""
    maps = _maps_on(silver_dir(), ("SILVER*.[dD]64",))
    assert len(maps) == 17, sorted(maps)
    rejected = sorted(n for n, raw in maps.items()
                      if not looks_like_a_map(Geo(raw)))
    assert rejected == [], f"{len(rejected)} of {len(maps)} rejected: {rejected}"


@pytest.mark.skipif(disk_dir() is None, reason="needs the game disks")
def test_the_combat_block_the_game_puts_at_0400_is_not_a_map():
    """`SQRPACI01` is what occupies `$0400` in a fight -- a tile remap, the
    combat parameter block and code -- and it is 1026 bytes, a load address and
    exactly one page. It must never read as a map, or a player in a fight loses
    the controls.

    Named rather than synthesised because the synthetic junk below is ours and
    proves nothing about the game. The other seven `SQR*` and `COMBAT*` files
    on these disks are different lengths and different load addresses;
    `SQRPACI01` is the one `docs/50-experiments.md` measured at 137/480.
    """
    block = game_file("SQRPACI01")
    # `game_file` hands back the payload past the two-byte PRG load address,
    # and `SQRPACI01` is 1026 bytes on the disk -- exactly one page after it.
    assert len(block) == GEO_SIZE, len(block)
    geo = Geo(block)
    assert geo.reciprocity() == (137, 480)
    assert looks_like_a_map(geo) is False


def test_the_check_can_still_fail_and_the_thresholds_are_what_makes_it():
    """A check that cannot reject anything is not a check.

    The two blocks that must always be turned away are turned away by named
    thresholds and by nothing structural, and the way to know that is to weaken
    each threshold and watch them walk through. Every assertion here fails if
    somebody lowers a constant without measuring first.
    """
    zeroes = Geo(bytes(GEO_SIZE))
    junk = Geo(bytes((i * 37 + (i >> 3)) & 0xFF for i in range(GEO_SIZE)))
    assert looks_like_a_map(zeroes) is False
    assert looks_like_a_map(junk) is False

    # What each of them is rejected *by*. A page of zeroes reciprocates 1.000
    # and agrees with itself perfectly about the wall art it has not got, so
    # only the two clauses about drawn walls turn it away.
    empty = area.map_evidence(zeroes)
    assert (empty.reciprocity, empty.art_agreement) == (1.0, 1.0)
    assert empty.walled_edges == 0 and empty.pair_reuse == 0.0

    scribble = area.map_evidence(junk)
    assert scribble.reciprocity < area.MAP_RECIPROCITY
    assert scribble.art_agreement < area.MAP_WALL_ART_AGREEMENT

    # And now weaken them. `MapEvidence.plausible` reads the module constants
    # when it is called, so this is the same code the window runs.
    for block, loosened in ((zeroes, {"MAP_WALLED_EDGES": 0,
                                      "MAP_WALL_PAIR_REUSE": 0.0}),
                            (junk, {"MAP_RECIPROCITY": 0.0,
                                    "MAP_WALL_ART_AGREEMENT": 0.0,
                                    "MAP_WALL_PAIR_REUSE": 0.0})):
        saved = {name: getattr(area, name) for name in loosened}
        try:
            for name, value in loosened.items():
                setattr(area, name, value)
            assert looks_like_a_map(block) is True, (
                "weakening the thresholds did not let this block in, so the "
                "test above was not measuring the thresholds")
        finally:
            for name, value in saved.items():
                setattr(area, name, value)

    assert looks_like_a_map(zeroes) is False
    assert looks_like_a_map(junk) is False
