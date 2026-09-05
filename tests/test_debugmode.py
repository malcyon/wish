from __future__ import annotations


def make_root():
    from PyQt6.QtWidgets import QMainWindow

    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    return root

"""Debug mode, the FastTravel row, and choosing a backend.

Nothing here needs an emulator and nothing here opens a dialog. A fasttravel is
exercised against `MemoryTarget` with a program counter bolted on, which is
what makes the assertions worth making: the addresses written, and their
order, are the part that has to be right.

**What these tests cannot show.** That entering `NEWECL`'s handler at `$2034`
from `DUNGEON`'s key-wait loop does what the game does when it reaches that
address itself. P15 did it in the game and the party walked afterwards; where a
fasttravel *lands* is the half still being measured (`docs/118-debug-mode.md`, P20).
These tests pin the sequence so that a live correction is one edit in one
function.
"""


import pytest

from automap import actionbar, actions
from automap.target import MemoryTarget
from goldbox import games
from wish import debugmode

WORLD, COMBAT = 1, 2                    # $6E11: DUNGEON, COMBAT
IN_THE_LOOP = 0x10C2                    # a PC the fasttravel will accept


class Machine(MemoryTarget):
    """A `MemoryTarget` that also has a CPU, which is all a fasttravel adds.

    `Target` is `read` and `write` and deliberately nothing else, so the
    program counter is reached through the same optional hook a real backend
    would offer.
    """

    def __init__(self, memory=None, pc: int = IN_THE_LOOP):
        super().__init__(memory)
        self._pc = pc
        self.jumps: list[int] = []

    def pc(self) -> int:
        return self._pc

    def set_pc(self, address: int) -> None:
        self._pc = address
        self.jumps.append(address)


def machine(mode: int = WORLD, area: int = 0, disk: int = 3,
            pc: int = IN_THE_LOOP, indoors: int = 1) -> Machine:
    """A machine standing in an area, ready to be fasttraveled out of."""
    return Machine({games.MODE_FLAG_POOL: bytes([mode]),
                    actions.FASTTRAVEL_SLOT: bytes([area]),
                    actions.FASTTRAVEL_DISK: bytes([disk]),
                    actions.FASTTRAVEL_INDOORS: bytes([indoors]),
                    actions.FASTTRAVEL_X: bytes([5, 6, 1])}, pc=pc)


def area(id: int = 20):
    row = actions.area_by_id(id)
    if row is None:                     # pragma: no cover - the table is there
        pytest.skip("goldbox/areas.py has no such area")
    return row


# --- the flag ----------------------------------------------------------------

def test_debug_mode_is_off_unless_the_environment_says_otherwise(monkeypatch):
    monkeypatch.delenv(debugmode.ENV, raising=False)
    assert not debugmode.enabled()
    for off in ("", "0", "no", "off", "maybe"):
        monkeypatch.setenv(debugmode.ENV, off)
        assert not debugmode.enabled(), off
    for on in ("1", "true", "YES", " on "):
        monkeypatch.setenv(debugmode.ENV, on)
        assert debugmode.enabled(), on


def test_turning_it_on_sets_the_variable_itself(monkeypatch):
    """So that a debug session which spawns a subprocess passes the mode on --
    and so that nothing else in the application reads `os.environ` for it."""
    monkeypatch.delenv(debugmode.ENV, raising=False)
    debugmode.enable()
    import os
    assert os.environ[debugmode.ENV] == "1"
    debugmode.disable()
    assert not debugmode.enabled()


def test_the_flag_is_an_alias_and_is_taken_off_the_command_line(monkeypatch):
    """`argparse` never sees it: three entry points parse their own arguments
    and none of them has heard of `--debug`."""
    monkeypatch.delenv(debugmode.ENV, raising=False)
    argv = ["wish", "--debug", "SAVE.D64"]
    assert debugmode.enable_from_argv(argv)
    assert argv == ["wish", "SAVE.D64"]
    argv = ["wish", "--no-debug"]
    assert not debugmode.enable_from_argv(argv)
    assert argv == ["wish"]


def test_the_debug_log_is_the_switch_a_user_gets(monkeypatch, tmp_path):
    """Retired: `test_debug_mode_is_not_a_setting`, which asserted the mode was
    unreachable from `Settings`. It is reachable now, through the log, and the
    one thing worth pinning is that the two move together --
    `docs/118-debug-mode.md` §1."""
    monkeypatch.delenv(debugmode.ENV, raising=False)
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(var, str(tmp_path))
    from wish import debuglog
    debuglog.stop()
    assert not debugmode.enabled()
    debuglog.start()
    assert debugmode.enabled()
    debuglog.stop()
    assert not debugmode.enabled()


# --- the write sequence ------------------------------------------------------

def test_the_writes_are_newecls_own_in_newecls_order():
    """`DUNGEON $2011`-`$2032`, with the operand fetch removed. The first two
    writes are not `NEWECL`'s own -- the WALLS slot release is New Phlan's
    departing script, skipped the same way (`#156`), and the wall-pin clear
    is `ECL06`/`ECL07`/`ECL0A`'s departing clean-up, skipped the same way
    (`#179`) -- and both come first because they happen before `NEWECL` is
    even entered on a genuine exit."""
    writes = actions.newecl_writes(0, 20, disk=2, arrival=(1, 14, 1))
    assert writes == (
        (0x6E1C, b"\xff"),                     # release the WALLS slot, #156
        (0x49E7, bytes(3)),                    # unpin the three wall pieces, #179
        (0x6E12, bytes([2])),                  # which POOL disk to ask for
        (0xC04B, bytes([1, 14, 1])),           # x, y, facing
        (0x49F2, bytes([0])),                  # where we came from
        (0x6E1B, bytes([20 | 0x80])),          # the ECL slot, flagged reload
        (0x4A00, bytes(32)),                   # the scratch/persistent split
    )


def test_the_outgoing_id_loses_the_reload_bit():
    """`$2011`-`$2016` is `$49F2 = $6E1B & $7F`: where we came from, without
    the cache's reload flag."""
    writes = dict(actions.newecl_writes(0xFF, 1))
    assert writes[actions.FASTTRAVEL_FROM] == bytes([0x7F])
    assert writes[actions.FASTTRAVEL_SLOT] == bytes([1 | 0x80])


def test_a_square_is_only_written_when_there_is_one():
    """Six areas are placed by the arriving script's own entry 4, and area 7
    has a square but no facing."""
    plain = dict(actions.newecl_writes(0, 1))
    assert actions.FASTTRAVEL_X not in plain
    partial = dict(actions.newecl_writes(0, 7, arrival=(5, 7)))
    assert partial[actions.FASTTRAVEL_X] == bytes([5, 7])


def test_an_outdoor_target_writes_the_travel_square_and_not_the_geo_one():
    """Areas 25-27's position is `$49C3`/`$49C4`, not `$C04B`
    (`#178 (Fast Travel to the wilderness leaves the party on whatever
    overland square it last stood on)`). The write sits where `$C04B`'s
    would: after `$6E12` (the disk) and before `$49F2` (where we came
    from)."""
    writes = actions.newecl_writes(0, 26, disk=7, overland=(7, 29))
    assert (actions.FASTTRAVEL_TRAVEL_X, bytes([7, 29])) in writes
    assert actions.FASTTRAVEL_X not in dict(writes)
    addrs = [addr for addr, _ in writes]
    assert (addrs.index(actions.FASTTRAVEL_DISK)
            < addrs.index(actions.FASTTRAVEL_TRAVEL_X)
            < addrs.index(actions.FASTTRAVEL_FROM))


def test_newecl_writes_refuses_arrival_and_overland_together():
    """An area is indoors or outdoors, never both, so a caller supplying
    both squares is a bug and not a choice between writes."""
    with pytest.raises(ValueError):
        actions.newecl_writes(0, 26, arrival=(1, 2, 3), overland=(7, 29))


def test_a_fasttravel_writes_then_jumps_into_the_tail_of_newecl():
    target = machine(area=0)
    fasttravel = actions.FastTravel()
    outcome = fasttravel.apply(target, area=area(13))     # the kobold caves
    assert outcome.ok
    assert [addr for addr, _ in outcome.writes] == [
        actions.FASTTRAVEL_WALLS_SLOT, actions.WALL_SLOT_PINNED,
        actions.FASTTRAVEL_DISK,
        actions.FASTTRAVEL_X, actions.FASTTRAVEL_FROM,
        actions.FASTTRAVEL_SLOT, actions.FASTTRAVEL_SCRATCH]
    assert target.jumps == [0x2034]
    assert target.memory[actions.FASTTRAVEL_SLOT] == bytes([13 | 0x80])
    assert target.memory[actions.FASTTRAVEL_WALLS_SLOT] == b"\xff"


def test_a_fasttravel_to_a_window_puts_the_party_on_the_windows_square():
    """`#178 (Fast Travel to the wilderness leaves the party on whatever
    overland square it last stood on)`: area 26's own `Area.overland` goes
    to `$49C3`/`$49C4`, and `$C04B` -- meaningless outdoors -- is left
    exactly as it was."""
    target = machine(area=0)                       # New Phlan, indoors
    outcome = actions.FastTravel().apply(target, area=area(26))  # Middle Window
    assert outcome.ok
    assert target.memory[actions.FASTTRAVEL_TRAVEL_X] == bytes([7, 29])
    assert target.memory[actions.FASTTRAVEL_X] == bytes([5, 6, 1]), (
        "$C04B is not GDRIVE00's square outdoors and must be left alone")


def test_a_window_with_no_overland_square_says_so():
    """A stand-in area with no `overland` -- none of the three real windows
    are in this state any more, so this is the shape rather than a live
    case."""
    class _NoOverlandWindow:
        id = 63
        ecl = "ECL3F"
        name = "Nowhere Window"
        outdoors = True
        overland = None
        disk = None
        fasttravelable = True

    target = machine(area=0)
    outcome = actions.FastTravel().apply(target, area=_NoOverlandWindow())
    assert outcome.ok
    assert actions.FASTTRAVEL_TRAVEL_X not in dict(outcome.writes)
    assert actions.FASTTRAVEL_X not in dict(outcome.writes)
    # #263: the note used to name `$49C3` as the square that held. It says
    # what the player sees instead, and the address moved to a comment beside
    # `FastTravel.warnings`.
    assert any("Nowhere Window" in note and "last held" in note
               for note in outcome.notes), outcome.notes


def test_fasttravel_warnings_carry_no_memory_address():
    """`#263 (Fast Travel's Messages tooltip shows the player a memory
    address)`: `$49F2`, `$49C3`/`$49C4` and the rest used to sit in front of a
    player who only hovered a Messages line to learn why a trip was risky.

    Indoors is matched to each target's own `outdoors` here so the one branch
    `#263` left open -- the indoors/outdoors mismatch note, still `$49E6 is
    {n}, so LOADFILES will ask for a SQRDATA` -- does not fire and mask a
    regression in the other three.
    """
    import re

    address = re.compile(r"\$[0-9A-F]{4}\b")

    class _Indoors:
        outdoors = False
        has_map = True

    class _Outdoors:
        outdoors = True
        has_map = True
        overland = None
        name = "Nowhere Window"

    ft = actions.FastTravel()
    target_in = machine(area=0, indoors=1)      # outdoors_now is False
    target_out = machine(area=0, indoors=0)     # outdoors_now is True

    # no arrival square known, indoors target
    for note in ft.warnings(target_in, _Indoors(), None):
        assert not address.search(note), f"a memory address reaches a player: {note!r}"

    # overland square known, outdoors target
    for note in ft.warnings(target_out, _Outdoors(), None, overland=(7, 29)):
        assert not address.search(note), f"a memory address reaches a player: {note!r}"

    # no overland square known, outdoors target
    for note in ft.warnings(target_out, _Outdoors(), None):
        assert not address.search(note), f"a memory address reaches a player: {note!r}"


def test_the_fasttravel_tooltip_capitalises_every_note(app):
    """`#263`: every note opened lowercase, because `FastTravelBar._report`
    joined `outcome.notes` straight into the tooltip. `_report` already
    capitalises the message line the same way; this is the same fix for the
    notes below it."""
    said = []
    row = bar(app, say=lambda text, detail="", alarm=False:
              said.append((text, detail)))
    row._report("fast travel", actions.Outcome(
        True, "Traveling to Kuto's Well.",
        notes=("the arriving script assumes quest flags the party never "
               "set", "no arrival square is known for this area")))
    detail = said[-1][1]
    assert detail.splitlines() == [
        "The arriving script assumes quest flags the party never set",
        "No arrival square is known for this area"]


def test_the_quest_flags_are_said_out_loud():
    outcome = actions.FastTravel().apply(machine(), area=area(20))
    assert any("quest flags" in note for note in outcome.notes)


def test_fasttraveling_out_of_new_phlan_releases_the_walls_slot():
    """`#156`: a genuine exit from New Phlan runs `ECL00 $9955`/`$9BDC`,
    `LOADFILES 255, 255, 127`, which empties slot 9 of the loaded-files cache
    -- the resident `WALLS` file -- before `NEWECL` runs. `FastTravel` enters
    `NEWECL` at its tail and skips that statement, so left unfixed the slot
    keeps saying `WALLS00` after a fast travel out, the next area's
    `LOADPIECES` unpacks its own wall definitions over the same `$ED50`, and
    the next arrival in New Phlan finds slot 9 still `00` and declines to
    reload the file it has just lost.

    Simulated here as the loaded-files cache would actually read after a
    warp into New Phlan followed by a warp back out: slot 9 claimed (`$00`)
    rather than the `$FF` a genuine exit leaves."""
    target = machine(area=0)                    # standing in New Phlan
    target.memory[actions.FASTTRAVEL_WALLS_SLOT] = bytes([0x00])   # claimed
    outcome = actions.FastTravel().apply(target, area=area(20))    # the Slums
    assert outcome.ok
    assert target.memory[actions.FASTTRAVEL_WALLS_SLOT] == b"\xff"


def test_the_walls_slot_is_released_leaving_anywhere_not_just_new_phlan():
    """The release is unconditional, and that is a decision rather than an
    accident -- so it is pinned here rather than only argued in a docstring.

    Narrowing it to `if from_area == 0:` would still fix `#156`, because the
    corruption is introduced on the way *out* of New Phlan, and every other
    test in this file departs from New Phlan -- so that narrowing would pass
    all of them. What it would cost is the three areas measured on `#156`
    that already leave the same illegal cache state and are invisible only
    because nothing there reads `$ED50`: warping into the Slums, Podol Plaza
    and Sokol Keep. Releasing everywhere costs at most one reload of
    `WALLS00` in the one area that wants it.
    """
    writes = actions.newecl_writes(from_area=20, to_area=18)   # Slums to Podol
    assert writes[0] == (actions.FASTTRAVEL_WALLS_SLOT, b"\xff"), (
        "the walls slot is released on every fast travel, not only the ones "
        "leaving New Phlan")


def test_the_wall_pins_are_cleared_on_every_fast_travel():
    """`ECL06` (Valjevo Castle south-west), `ECL07` (the Inner Tower) and
    `ECL0A` (Valhingen Graveyard) pin one flag apiece at `$49E7`-`$49E9` so
    `DUNGEON $14CB` skips relocating that wall piece, and each clears its own
    pin only on the way out -- the part `FastTravel` skips by entering
    `NEWECL` at its tail (`#179`). Cleared unconditionally, the same shape as
    `FASTTRAVEL_WALLS_SLOT` (`#156`): a piece nobody pinned is already zero,
    so the write costs nothing there."""
    writes = actions.newecl_writes(from_area=10, to_area=18)   # Graveyard to Podol
    assert (actions.WALL_SLOT_PINNED,
            bytes(actions.WALL_SLOT_PINNED_LEN)) in writes, (
        "$49E7-$49E9 must be zeroed on every fast travel, or a piece pinned "
        "by the area left behind keeps its old wall art")


# --- what it refuses ---------------------------------------------------------

def test_a_fasttravel_is_refused_when_dungeon_is_not_resident():
    """`$2034` is some other overlay's code, and jumping there is a crash."""
    verdict = actions.FastTravel().legality(machine(mode=COMBAT), area(20))
    assert not verdict and "$6E11" in verdict.reason


def test_a_fasttravel_is_refused_from_anywhere_but_the_key_wait_loop():
    """Mid-script or mid-load, the stack reload at `$203A` throws away work in
    flight. It is also the check that `PC_REGISTER` is the register we think."""
    target = machine(pc=0x2011)
    verdict = actions.FastTravel().legality(target, area(20))
    assert not verdict and "key-wait" in verdict.reason
    assert target.jumps == []


def test_a_fasttravel_to_the_area_we_are_in_is_refused():
    """`NEWECL` skips a same-area transition, so `$4A00` would not be cleared
    and nothing would happen -- silently, which is the objection."""
    verdict = actions.FastTravel().legality(machine(area=20), area(20))
    assert not verdict and "already in that area" in verdict.reason


def test_a_backend_with_no_cpu_cannot_fasttravel():
    plain = MemoryTarget({games.MODE_FLAG_POOL: bytes([WORLD])})
    verdict = actions.FastTravel().legality(plain, area(20))
    assert not verdict and "program counter" in verdict.reason


def test_nothing_is_written_by_a_refused_fasttravel():
    target = machine(mode=COMBAT)
    before = dict(target.memory)
    outcome = actions.FastTravel().apply(target, area=area(20))
    assert not outcome.ok and outcome.writes == ()
    assert target.memory == before and target.jumps == []


# --- going back --------------------------------------------------------------

def test_fasttravel_back_is_refused_until_a_fasttravel_has_been_made():
    fasttravel = actions.FastTravel()
    verdict = fasttravel.back_verdict(machine())
    assert not verdict and "nothing to go back to" in verdict.reason


def test_fasttravel_back_returns_to_the_square_the_fasttravel_started_on():
    """The waypoint is read before the writes: the first two of them are the
    disk and the square, so one taken afterwards would record the destination."""
    target = machine(area=0, disk=3)
    fasttravel = actions.FastTravel()
    assert fasttravel.apply(target, area=area(20)).ok
    assert fasttravel.back == actions.Waypoint(0, 3, (5, 6, 1))
    target.memory[actions.FASTTRAVEL_SLOT] = bytes([20])       # the game arrived
    target._pc = IN_THE_LOOP
    outcome = fasttravel.apply_back(target)
    assert outcome.ok
    assert dict(outcome.writes)[actions.FASTTRAVEL_X] == bytes([5, 6, 1])
    assert dict(outcome.writes)[actions.FASTTRAVEL_SLOT] == bytes([0x80])
    assert fasttravel.back is None                              # and no further back


def test_fasttravel_back_from_a_window_returns_to_the_travel_square():
    """`Waypoint.square` is `$C04B`, which is not `GDRIVE00`'s square
    outdoors -- Back from window 27 to window 26 must restore
    `$49C3`/`$49C4` instead
    (`#178 (Fast Travel to the wilderness leaves the party on whatever
    overland square it last stood on)`)."""
    target = machine(area=26, disk=7, indoors=0)
    target.memory[actions.FASTTRAVEL_TRAVEL_X] = bytes([4, 20])
    fasttravel = actions.FastTravel()
    assert fasttravel.apply(target, area=area(27)).ok  # East Window
    assert fasttravel.back.overland == (4, 20)
    target.memory[actions.FASTTRAVEL_SLOT] = bytes([27])   # the game arrived
    target._pc = IN_THE_LOOP
    outcome = fasttravel.apply_back(target)
    assert outcome.ok
    writes = dict(outcome.writes)
    assert writes[actions.FASTTRAVEL_TRAVEL_X] == bytes([4, 20])
    assert actions.FASTTRAVEL_X not in writes


def test_fast_travel_asks_nothing_and_names_no_disk():
    """Retired: `test_the_confirmation_names_the_disk_the_area_is_on`. Donald
    tested the feature and the game asks for the disk it wants itself, so the
    confirmation and the disk warning both went; what travelling does not
    guarantee is `HELP`, under the row's help icon."""
    fasttravel = actions.FastTravel()
    assert fasttravel.confirm == ""                      # nothing to ask
    assert not hasattr(fasttravel, "question")
    assert not hasattr(fasttravel, "disk_note")
    assert "copy of your save disk" in fasttravel.HELP
    assert "POOL" not in fasttravel.HELP


# --- the area table ----------------------------------------------------------

def test_the_areas_come_from_por_areas_and_are_not_copied_here():
    """One table. `automap/actions.py` reads `goldbox/areas.py` and holds no copy
    of its own; the row objects are that module's."""
    from goldbox import areas as table
    assert actions.area_rows() == tuple(table.AREAS)


def test_an_arrival_square_is_taken_from_the_table():
    assert actions.FastTravel.arrival_of(area(0)) == (15, 1, 3)     # New Phlan
    assert actions.FastTravel.arrival_of(area(7)) == (5, 7)         # no facing known
    assert actions.FastTravel.arrival_of(area(9)) is None           # none harvested


def test_a_square_is_chosen_off_the_map_when_the_table_has_none():
    """The fallback for the fourteen areas nobody has harvested: never the
    party's current square, which is a wall in the next area along.

    `goldbox.areas.landing_square` picks it -- P20 measured what the old rule came
    to and it was `(0, 0)` on every map (`work/reports/p20-arrivals.md`)."""
    from goldbox.geo import Geo
    from tests.gamedata import synthetic_geo
    geo = Geo(synthetic_geo())
    square = actions.landing_square(geo)
    assert square is not None
    x, y, facing = square
    assert geo.is_passable(x, y, facing)
    assert actions.landing_square(None) is None


# --- the row under the map ---------------------------------------------------

@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def bar(app, target=None, **kw):
    from automap.actionbar import FastTravelBar
    row = FastTravelBar(make_root(), **kw)
    if target is not None:
        row.attach(target)
    return row


def _window(app):
    from PyQt6.QtWidgets import QMainWindow

    from automap.state import Automapper
    from automap.window import AutomapBinding
    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    return AutomapBinding(root, Automapper(MemoryTarget({}), {}), drive=False)


def test_the_fast_travel_row_is_in_the_window_whatever_the_debug_flag_says(
        app, monkeypatch):
    """It was debug-mode-only while nobody knew where a trip landed. P20
    measured that (`work/reports/p20-arrivals.md`) and the gate came off, so
    the flag no longer decides whether the row is built."""
    from PyQt6.QtWidgets import QAbstractButton


    for flag in (False, True):
        if flag:
            monkeypatch.setenv(debugmode.ENV, "1")
        else:
            monkeypatch.delenv(debugmode.ENV, raising=False)
        win = _window(app)
        assert win.fasttravel_bar is not None
        assert sorted(b.text() for b in win.root.findChildren(QAbstractButton)
                      if "Travel" in b.text()) == ["Fast Travel"]


def test_the_row_lists_every_fasttravelable_area_by_name(app):
    """Every area but 30, which is the attract-mode demo and is not a place a
    party can be put -- `work/reports/p20-arrivals.md`.

    A row built with no settings is a row nobody has chosen for, and offers
    the lot; the window always passes the window's settings."""
    row = bar(app)
    fasttravelable = [r for r in actions.area_rows() if r.fasttravelable]
    assert row.combo.count() == len(fasttravelable) == len(actions.area_rows()) - 1
    assert 30 not in [r.id for r in row.rows]
    names = [r.name for r in row.rows]
    assert all(n is not None for n in names)
    assert row.combo.itemText(0) == names[0]
    # The maps and the disk are a tooltip, not list text.
    assert ", POOL" not in row.combo.itemText(0)
    from PyQt6.QtCore import Qt
    detail = row.combo.itemData(0, Qt.ItemDataRole.ToolTipRole)
    assert names[0] in detail and ", POOL" in detail


def test_the_dropdown_offers_the_areas_the_player_ticked(app):
    """The visited-areas filter is gone -- Donald: *"I don't think we can trust
    our visited-areas record. The player might visit areas while the
    automapper isn't open."* What is offered is now an explicit setting, and a
    fresh config has New Phlan, The Slums and Sokol Keep ticked."""
    from automap.config import Settings

    row = bar(app, settings=Settings())
    assert [r.name for r in row.rows] == ["New Phlan", "Sokol Keep",
                                          "The Slums"]
    assert row.combo.count() == 3

    row.settings.set_chosen_areas([0, 13])
    row.reload_areas()
    assert [r.name for r in row.rows] == ["New Phlan", "The Kobold Caves"]


def test_unticking_an_area_takes_it_out_of_the_dropdown(app):
    from automap.config import Settings

    settings = Settings()
    row = bar(app, settings=settings)
    assert "Sokol Keep" in [r.name for r in row.rows]
    settings.set_chosen_areas([i for i in settings.chosen_areas() if i != 21])
    row.reload_areas()
    assert "Sokol Keep" not in [r.name for r in row.rows]


def test_area_30_is_never_offered_however_the_setting_is_written(app):
    """`ECL1E` is the attract-mode demo: fasttraveling there ends the session, so it
    is not in the table to be ticked and a hand-edited config naming it still
    does not get it (`work/reports/p20-arrivals.md`)."""
    from automap.config import Settings

    row = bar(app, settings=Settings(
        fast_travel_targets={"pool-of-radiance": [0, 30]}))
    assert [r.id for r in row.rows] == [0]


def test_nothing_ticked_says_so_rather_than_looking_broken(app):
    """An empty dropdown is the player's own choice here, so the row names the
    setting to go and look at, and the button refuses with the same reason
    instead of the emulator's."""
    from automap.config import Settings

    row = bar(app, machine(area=13),
              settings=Settings(fast_travel_targets={"pool-of-radiance": []}))
    assert row.rows == ()
    assert row.area() is None
    assert not row.combo.isEnabled()
    assert row.combo.itemText(0) == actionbar.NOTHING_TICKED
    assert not row.button.isEnabled()
    assert "Fast travel" in row.button.toolTip()
    assert row.run() is None


def test_a_session_of_another_title_is_offered_nothing_and_told_why(app):
    """#14. `AREAS` is thirty Pool of Radiance `ECL` scripts with `POOL` disk
    numbers in them, and a trip writes both into the machine -- so a session
    of a title with no table of its own that was offered them would write
    Pool of Radiance's numbers into it. Offering nothing is the fix; falling
    back to that list is the one answer that corrupts.

    Champions of Krynn stands in for "a title with no table" here -- Curse of
    the Azure Bonds moved out of this role when `#192 (Convert a Curse of the
    Azure Bonds DOS save into a C64 one, which the importer refuses today)`
    step 0b built its own twenty-five rows, the way Silver Blades moved out of
    it under `#20 (Build an area table for Silver Blades)`.
    """
    from automap.config import Settings
    from goldbox import games

    row = bar(app, machine(area=13), settings=Settings(),
              title=games.CHAMPIONS_OF_KRYNN.title,
              game=games.CHAMPIONS_OF_KRYNN)
    assert row.all_rows == () and row.rows == ()
    assert not row.has_areas
    assert not row.combo.isEnabled()
    assert row.combo.itemText(0) == ("No areas are known for Champions of "
                                     "Krynn.")
    assert not row.button.isEnabled()
    assert "Champions of Krynn" in row.button.toolTip()
    assert row.run() is None
    # And the ticks are not Pool of Radiance's either: nothing is ticked for a
    # title with no table to tick.
    assert row.settings.chosen_areas(games.CHAMPIONS_OF_KRYNN) == ()


def test_the_row_follows_the_title_when_the_disks_change(app):
    """The one place the title moves under a live row: `set_maps`."""
    from automap.config import Settings
    from goldbox import games

    row = bar(app, settings=Settings(), title=games.POOL_OF_RADIANCE.title,
              game=games.POOL_OF_RADIANCE)
    assert [r.name for r in row.rows] == ["New Phlan", "Sokol Keep",
                                          "The Slums"]
    row.set_title(games.SECRET_OF_THE_SILVER_BLADES.title,
                  games.SECRET_OF_THE_SILVER_BLADES)
    # Silver Blades has a table now -- twenty-two areas, fourteen of them
    # driven into on a running machine (`#20 (Build an area table for Silver
    # Blades)`) -- and `automap/config.py` gives it no default ticks, so the
    # dropdown is empty because nothing is chosen rather than because there is
    # nothing to choose. `all_rows` is the table and `rows` is the ticks.
    assert row.rows == ()
    assert len(row.all_rows) == 22
    assert "No areas ticked" in row.combo.itemText(0)
    row.set_title(games.POOL_OF_RADIANCE.title, games.POOL_OF_RADIANCE)
    assert [r.name for r in row.rows] == ["New Phlan", "Sokol Keep",
                                          "The Slums"]


def test_the_button_carries_its_refusal_in_its_tooltip(app):
    row = bar(app, machine(mode=COMBAT))
    assert not row.button.isEnabled()
    assert "$6E11" in row.button.toolTip()
    assert not row.back_button.isEnabled()
    assert "nothing to go back to" in row.back_button.toolTip()


def test_with_nothing_attached_the_row_is_disabled_rather_than_inert(app):
    row = bar(app)
    assert not row.button.isEnabled()
    assert "no emulator attached" in row.button.toolTip()


def test_no_disk_is_named_anywhere_in_the_row(app):
    """The game stops and asks for the disk it wants, so saying it first told
    the player only what the game was about to."""
    row = bar(app, machine(area=0, disk=3))
    row.combo.setCurrentIndex(row.rows.index(area(13)))       # POOL8
    assert not hasattr(row, "disk")
    assert "POOL" not in row.button.toolTip()


def test_the_button_carries_the_warning_as_its_own_help_text(app):
    """Donald's wording, exactly, on the button that does the thing. It shows
    while the button is usable; a disabled button says why it is disabled
    instead, which is the more urgent answer and the trip is not happening
    anyway."""
    row = bar(app, machine(area=13))
    assert row.button.isEnabled()
    assert row.button.toolTip() == (
        "Fast travel to areas you haven't been to is dangerous and can "
        "break the game.")
    assert row.button.toolTip() == actionbar.DANGER


def test_there_is_no_help_icon_any_more(app):
    """It went with the visited filter: Donald asked for the icon and its
    tooltip out altogether, and the sentence that replaced them is on the
    button and in Preferences, where nobody has to hover to find it."""
    from PyQt6.QtWidgets import QToolButton

    row = bar(app)
    assert not hasattr(row, "help_icon")
    assert row.findChildren(QToolButton) == []


def test_a_square_is_chosen_off_the_map_only_where_that_means_something(app):
    """The three cases of `docs/118-debug-mode.md`, and the two P20 added.

    An overland area gets no square because outdoors the position is
    `$49C3`/`$49C4`, and a `dynamic_geo` area gets none because it loads a map
    `geos` does not name -- area 3 loaded `GEO05` and area 5 `GEO04`
    (`work/reports/p20-arrivals.md`).
    """
    from goldbox.geo import Geo
    from tests.gamedata import synthetic_geo
    g = Geo(synthetic_geo())
    row = bar(app, maps={"GEO14": g, "GEO19": g, "GEO03": g})

    def chosen(id):
        row.combo.setCurrentIndex(row.rows.index(area(id)))
        return row.arrival()

    assert chosen(20) == actions.landing_square(g)   # a map and no known square
    assert chosen(21) == (8, 14, 0)                  # ECL15 places the party
    assert chosen(25) is None                        # overland
    assert chosen(3) is None                         # picks its map at run time


def test_the_row_fasttravels_what_the_combo_box_is_showing(app):
    target = machine(area=0)
    row = bar(app, target)
    row.combo.setCurrentIndex(row.rows.index(area(13)))
    outcome = row.run()
    assert outcome.ok
    assert target.memory[actions.FASTTRAVEL_SLOT] == bytes([13 | 0x80])
    assert target.memory[actions.FASTTRAVEL_X] == bytes([6, 15, 0])   # the table's
    assert target.jumps == [actions.NEWECL_TAIL]


def test_the_row_travels_on_the_click_with_nothing_to_dismiss(app):
    """Retired: `test_the_row_asks_first_and_a_no_writes_nothing`. There is no
    dialog left to answer -- a click writes and jumps."""
    from PyQt6.QtWidgets import QMessageBox

    def showing():
        # *Visible*, not merely existing: `conftest.py` holds one QApplication
        # for the whole session, so a message box any earlier test built is
        # still a top-level widget here -- Identify Items and Level Up both
        # still confirm, and both run before this one. Counting them does not
        # work either, because PyQt hands out a fresh Python wrapper for each
        # enumeration, so `id()` is not stable between two calls.
        return [w for w in app.topLevelWidgets()
                if isinstance(w, QMessageBox) and w.isVisible()]

    target = machine(area=0)
    row = bar(app, target)
    assert not hasattr(row, "ask")
    row.button.click()
    assert target.jumps == [actions.NEWECL_TAIL]
    assert not showing()


def test_a_refused_fasttravel_is_reported_as_an_alarm(app):
    said = []
    row = bar(app, machine(mode=COMBAT),
              say=lambda text, detail="", alarm=False: said.append((text, alarm)))
    row.combo.setCurrentIndex(row.rows.index(area(13)))
    row.run()
    assert said and said[-1][1] is True
    assert "$6E11" in said[-1][0]


# --- the map window ----------------------------------------------------------

def window(app, tmp_path, monkeypatch, target=None):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from PyQt6.QtWidgets import QMainWindow

    from automap.state import Automapper
    from automap.window import AutomapBinding
    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    return AutomapBinding(root, Automapper(target, {}), drive=False)


def test_the_flag_no_longer_decides_whether_the_row_is_built(app, tmp_path,
                                                             monkeypatch):
    """`AutomapBinding` used to read `WISH_DEBUG` once at build time. It does
    not read it at all now, which is what makes the row's launch-time timing
    problem go away: there is no flag left to be applied too late."""
    monkeypatch.delenv(debugmode.ENV, raising=False)
    assert window(app, tmp_path, monkeypatch).fasttravel_bar is not None
    monkeypatch.setenv(debugmode.ENV, "1")
    assert window(app, tmp_path, monkeypatch).fasttravel_bar is not None


def test_the_fast_travel_row_follows_the_poll(app, tmp_path, monkeypatch):
    # Standing in the Kobold Caves, so the area the window's own settings
    # select first -- New Phlan -- is somewhere else and the trip is legal.
    target = machine(area=13)
    win = window(app, tmp_path, monkeypatch, target)
    for _ in range(win.LIVE_EVERY):
        win.tick()
    assert win.fasttravel_bar.target is target
    assert win.fasttravel_bar.button.isEnabled()


# --- choosing a backend ------------------------------------------------------

def fake_session(app):
    from wish.session import Session
    return Session(find=lambda pref=None: None)


def wish_window(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from wish.window import WishWindow
    return WishWindow(maps={}, session=fake_session(app))


def test_the_hosted_window_has_the_fast_travel_row_too(app, tmp_path,
                                                       monkeypatch):
    """Both entry points: `wish-automap` builds `AutomapBinding` itself, the
    `wish` window hosts one. The row used to want `WISH_DEBUG` on the command
    line here, because the map is built before the remembered settings are
    applied; with no flag to read there is nothing left to be applied late."""
    monkeypatch.delenv(debugmode.ENV, raising=False)
    win = wish_window(app, tmp_path, monkeypatch)
    assert win.map.fasttravel_bar is not None
    assert win.map.fasttravel_bar.button.text() == "Fast Travel"


def test_the_backend_menu_offers_every_backend_and_no_preference(app, tmp_path,
                                                                 monkeypatch):
    from wish import backends
    from wish.window import ANY_BACKEND
    win = wish_window(app, tmp_path, monkeypatch)
    names = set(win.backend_actions)
    assert ANY_BACKEND in names
    assert {b.name for b in backends.backends()} <= names
    assert win.backend_actions[ANY_BACKEND].isChecked()


def test_the_menu_says_which_are_answering_and_which_are_unverified(
        app, tmp_path, monkeypatch):
    """The Ultimate's reads are confirmed on hardware now (#240), so it no
    longer carries the caveat -- but the menu must still raise it for whatever
    backend genuinely is unverified, which this proves with a stand-in rather
    than the real Ultimate."""
    import dataclasses

    from wish import backends, ultimate
    monkeypatch.setattr(ultimate, "ULTIMATE",
                        dataclasses.replace(ultimate.ULTIMATE, verified=False))
    win = wish_window(app, tmp_path, monkeypatch)
    monkeypatch.setattr(backends, "VICE",
                        dataclasses.replace(backends.VICE, probe=lambda: True))
    win.label_backends()
    assert win.backend_actions["VICE"].text() == "VICE - answering"
    for backend in backends.backends():
        if not backend.verified:
            assert "unverified" in win.backend_actions[backend.name].text()
        else:
            assert "unverified" not in win.backend_actions[backend.name].text()


def test_choosing_a_backend_is_remembered_and_acted_on(app, tmp_path,
                                                       monkeypatch):
    from automap.config import Settings
    win = wish_window(app, tmp_path, monkeypatch)
    win._prefer_backend("Ultimate")
    assert win.settings.backend == "Ultimate"
    assert Settings.load().backend == "Ultimate"
    assert win.session._preferred == "Ultimate"
    win._prefer_backend("")
    assert Settings.load().backend == ""
    assert win.session._preferred is None


def test_a_different_backend_drops_the_connection_so_the_next_poll_reattaches(
        app, tmp_path, monkeypatch):
    from wish import backends
    win = wish_window(app, tmp_path, monkeypatch)
    win.session.target = object()
    win.session.backend = backends.VICE
    win._prefer_backend("Ultimate")
    assert win.session.target is None


# --- did it land? ------------------------------------------------------------

def loaded(geo_bytes: bytes, **kw) -> Machine:
    """A machine with a map resident at `$0400`, as `ResidentGeo` reads it."""
    target = machine(**kw)
    target.memory[0x0400] = geo_bytes
    return target


def test_a_fasttravel_is_verified_by_the_map_at_0400(app):
    """An exact 1024-byte match against the disk copy: a hit is certain and
    needs no fingerprinting."""
    from goldbox.geo import Geo
    from tests.gamedata import synthetic_geo
    raw = synthetic_geo()
    row = area(13)                                  # GEO0D, the kobold caves
    target = loaded(raw, area=0)
    row_bar = bar(app, target, maps={row.geos[0]: Geo(raw)})
    row_bar.combo.setCurrentIndex(row_bar.rows.index(row))
    assert row_bar.run().ok
    assert row_bar._pending is not None             # watching for it
    assert row_bar.check_arrival() == row.geos[0]
    assert row_bar._pending is None                 # and stops watching
    # The area's name, in the words the status line uses. The GEO file and
    # the address it matched at are the debug log's business.



def test_an_area_change_is_given_thirty_seconds(app, monkeypatch):
    """Not five. Stepping into an encounter in New Phlan takes about 25 to
    load, and four runs "died" on a timeout that was too short."""
    import automap.actionbar as ab
    from goldbox.geo import Geo
    from tests.gamedata import synthetic_geo
    row = area(13)
    target = loaded(bytes(1024), area=0)            # some other map
    row_bar = bar(app, target, maps={row.geos[0]: Geo(synthetic_geo())})
    row_bar.combo.setCurrentIndex(row_bar.rows.index(row))
    clock = [1000.0]
    monkeypatch.setattr(ab.time, "monotonic", lambda: clock[0])
    assert row_bar.run().ok
    clock[0] += ab.VERIFY_SECONDS - 1
    assert row_bar.check_arrival() is None
    assert row_bar._pending is not None             # still waiting, not failed
    clock[0] += 2
    assert row_bar.check_arrival() is None
    assert row_bar._pending is None                # stopped watching
    # And said nothing about it. The timeout used to write a sentence naming
    # three things that might have gone wrong, which is the sort of GUI help
    # text Donald has ruled out; the debug log carries it instead.



def test_nothing_is_read_at_0400_when_no_fasttravel_is_in_flight(app):
    target = machine()
    row = bar(app, target, maps={"GEO0D": None})
    target.reads.clear()
    row.attach(target)
    assert not [r for r in target.reads if r[0] == 0x0400]


def test_the_roster_button_levels_the_character_whose_card_it_is(app):
    """The old action-bar button called `apply(target)` with no slot, which
    silently meant slot 0 -- the ambiguity Donald reported. The card knows
    which character it is, so the signal carries the slot."""
    from PyQt6.QtWidgets import QMainWindow

    from automap.window import AutomapBinding
    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    window = AutomapBinding.__new__(AutomapBinding)
    seen = {}

    class Bar:
        def ask(self, question):
            seen["asked"] = question
            return True

    class Messages:
        def say(self, text, detail="", alarm=False):
            seen["said"] = text

    class Action:
        confirm = "sure?"

        def __init__(self, game=None):
            seen["action_game"] = game

        @staticmethod
        def class_for(record, game=None):
            seen["class_for_game"] = game
            return "fighter"

        @staticmethod
        def preview(record, class_name="", spell=None, game=None):
            return None

        def apply(self, target, **kwargs):
            seen["kwargs"] = kwargs
            return actions.Outcome(True, "SILAS is a fighter 6")

    window.actions_bar, window.messages = Bar(), Messages()
    window.state = type("S", (), {"title": "Pool of Radiance"})()
    window.mapper = type("M", (), {"target": object()})()
    window._refresh_roster = lambda: seen.update(refreshed=True)
    window.ask = lambda question: seen.update(asked=question) or True
    member = type("Member", (), {"record": object(), "name": "SILAS"})()
    party = type("Party", (), {"by_slot": lambda self, slot: member})()
    monkey, was_read = actions.LevelUp, actions.read_party
    actions.LevelUp = Action
    actions.read_party = lambda target, game=None: party
    try:
        AutomapBinding._level_up(window, 3)
    finally:
        actions.LevelUp, actions.read_party = monkey, was_read
    assert seen["kwargs"] == {"slot": 3, "class_name": "fighter", "spell": None}
    assert "asked" not in seen           # no confirmation: the button is the ask
    assert seen["said"] == "level up: SILAS is a fighter 6"
    assert seen["refreshed"], "the card still shows the old level and xp"
    # And the title went with it: every table the plan reads is per-title, and
    # passing none is how a Curse character got Pool of Radiance's (#16).
    assert seen["class_for_game"].key == "pool-of-radiance"


def test_the_level_up_button_is_not_offered_in_a_title_we_would_refuse(app):
    """#16. A button that appears and then fails is worse than one that never
    appears: `level_up_blockers` refuses every title but Pool of Radiance, so
    the card does not offer the press."""
    from PyQt6.QtWidgets import QMainWindow

    from automap.state import Automapper
    from automap.window import AutomapBinding
    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)

    pool = AutomapBinding(root, Automapper(MemoryTarget({}), {}), drive=False)
    assert pool.roster.levelling
    assert pool.fasttravel_bar.has_areas

    curse = AutomapBinding(root,
        Automapper(MemoryTarget({}), {},
                   title="Curse of the Azure Bonds"), drive=False)
    assert not curse.roster.levelling
    # Fast Travel and Level Up are refused on separate grounds -- Curse got
    # its own area table under `#192 (Convert a Curse of the Azure Bonds DOS
    # save into a C64 one, which the importer refuses today)` step 0b, so it
    # is offered here even though levelling still is not.
    assert curse.fasttravel_bar.has_areas
    # Cards built after the fact are told too -- they are made on demand.
    card = curse.roster.cards[0]
    assert not card.levelling


def test_the_click_warns_only_when_the_clamp_costs_an_earned_level(app):
    """No dialog in the common case -- Donald had that removed once already.
    The exception is `classes_disqualified`: the clamp takes a class below a
    threshold it had already passed, so a level the character earned goes, and
    that is worth a question. The refusal must write nothing."""
    from PyQt6.QtWidgets import QMainWindow

    from automap.window import AutomapBinding
    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    from goldbox.levelup import Plan
    window = AutomapBinding.__new__(AutomapBinding)
    seen = {}

    class Messages:
        def say(self, text, detail="", alarm=False):
            seen["said"] = text

    costly = Plan(class_name="thief", from_level=1, to_level=2, fields={},
                  hit_points_rolled=3, experience_lost=2502,
                  classes_disqualified=("magic-user",))

    class Action:
        confirm = ""
        plan = costly

        def __init__(self, game=None):
            seen["action_game"] = game

        @staticmethod
        def class_for(record, game=None):
            return "thief"

        @classmethod
        def preview(cls, record, class_name="", spell=None, game=None):
            return cls.plan

        def apply(self, target, **kwargs):
            seen["applied"] = kwargs
            return actions.Outcome(True, "LADY KATHERINE is a thief 2")

    window.messages = Messages()
    window.state = type("S", (), {"title": "Pool of Radiance"})()
    window.mapper = type("M", (), {"target": object()})()
    window._refresh_roster = lambda: None
    window.ask = lambda question: seen.update(asked=question) or False
    member = type("Member", (), {"record": object(),
                                 "name": "LADY KATHERINE"})()
    party = type("Party", (), {"by_slot": lambda self, slot: member})()
    monkey, was_read = actions.LevelUp, actions.read_party
    actions.LevelUp = Action
    actions.read_party = lambda target, game=None: party
    try:
        AutomapBinding._level_up(window, 0)
        assert "applied" not in seen, "the player said no"
        assert "2502" in seen["asked"] and "magic-user" in seen["asked"]

        # Nothing lost, nothing asked.
        seen.clear()
        Action.plan = Plan(class_name="thief", from_level=1, to_level=2,
                           fields={}, hit_points_rolled=3)
        AutomapBinding._level_up(window, 0)
        assert "asked" not in seen
        assert seen["applied"]["class_name"] == "thief"
    finally:
        actions.LevelUp, actions.read_party = monkey, was_read
        Action.plan = costly


def test_the_spell_names_come_off_the_disk_directory_not_from_it(tmp_path):
    """`find_disks` returns the directory, not a list of images. Iterating it
    crashed the window the first time a magic-user levelled -- `'PosixPath'
    object is not iterable`."""
    import automap.window as win

    window = win.AutomapBinding.__new__(win.AutomapBinding)
    window._spell_names = None
    window.state = type("S", (), {"title": None})()
    (tmp_path / "POOL1.D64").write_bytes(b"")       # a directory with a disk
    monkey = win.find_disks if hasattr(win, "find_disks") else None
    assert monkey is None                            # imported inside, not at top
    import automap.paths as paths
    was = paths.find_disks
    paths.find_disks = lambda game=None: tmp_path
    try:
        assert win.AutomapBinding._names_for_spells(window) == {}
    finally:
        paths.find_disks = was


def test_an_uncaught_exception_reaches_the_debug_log(tmp_path, monkeypatch):
    """The crash Donald hit killed the process -- PyQt aborts on an exception
    raised inside a slot, and `Aborted (core dumped)` puts the traceback on a
    stderr the windowed Windows build has not got. With the hook installed it
    lands in the file a bug report can carry, and the window survives."""
    import sys

    from wish import debuglog

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    was = sys.excepthook
    debuglog._previous_hook = None
    path = debuglog.start()
    try:
        debuglog.install_excepthook()
        assert sys.excepthook is debuglog.crash
        try:
            raise TypeError("'PosixPath' object is not iterable")
        except TypeError:
            sys.excepthook(*sys.exc_info())
    finally:
        debuglog.stop()
        sys.excepthook = was
        debuglog._previous_hook = None
    written = path.read_text(encoding="utf-8")
    assert "unhandled exception" in written
    assert "'PosixPath' object is not iterable" in written
    assert "/home/" not in written        # scrubbed, like every other line


def test_the_debug_log_cannot_grow_without_bound(tmp_path, monkeypatch):
    """Donald: "I don't want someone's disk filling up because it's been on for
    6 months." One file per session is not a bound -- a session left running
    writes for ever. Each file rotates and the directory is pruned, so the
    whole thing has a stated ceiling."""
    from wish import debuglog

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(debuglog, "MAX_BYTES", 2_000)
    path = debuglog.start()
    try:
        for _ in range(400):
            debuglog.note("%s", "x" * 120)
        parts = sorted(debuglog.log_dir().glob("wish-*.log*"))
        assert len(parts) > 1, "it never rotated"
        assert all(p.stat().st_size <= debuglog.MAX_BYTES * 2 for p in parts)
    finally:
        debuglog.stop()
    assert debuglog.ceiling() == debuglog.KEEP * debuglog.MAX_BYTES * (
        debuglog.PARTS + 1)
    assert path.exists()
