"""Debug mode, the Warp row, and choosing a backend.

Nothing here needs an emulator and nothing here opens a dialog. A warp is
exercised against `MemoryTarget` with a program counter bolted on, which is
what makes the assertions worth making: the addresses written, and their
order, are the part that has to be right.

**What these tests cannot show.** That entering `NEWECL`'s handler at `$2034`
from `DUNGEON`'s key-wait loop does what the game does when it reaches that
address itself. Nothing has ever tried it; see `docs/118-debug-mode.md`, open
question 1. These tests pin the sequence so that a live correction is one
edit in one function.
"""

from __future__ import annotations

import pytest

from automap import actions
from automap.target import MemoryTarget
from wish import debugmode

WORLD, COMBAT = 1, 2                    # $6E11: DUNGEON, COMBAT
IN_THE_LOOP = 0x10C2                    # a PC the warp will accept


class Machine(MemoryTarget):
    """A `MemoryTarget` that also has a CPU, which is all a warp adds.

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
    """A machine standing in an area, ready to be warped out of."""
    return Machine({actions.MODE: bytes([mode]),
                    actions.WARP_SLOT: bytes([area]),
                    actions.WARP_DISK: bytes([disk]),
                    actions.WARP_INDOORS: bytes([indoors]),
                    actions.WARP_X: bytes([5, 6, 1])}, pc=pc)


def area(id: int = 20):
    row = actions.area_by_id(id)
    if row is None:                     # pragma: no cover - the table is there
        pytest.skip("por/areas.py has no such area")
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


def test_debug_mode_is_not_a_setting(monkeypatch):
    """A logging setting that survives a restart is one you forget is on, and
    this one writes to the running machine."""
    from automap.config import Settings
    assert not hasattr(Settings(), "debug")


# --- the write sequence ------------------------------------------------------

def test_the_writes_are_newecls_own_in_newecls_order():
    """`DUNGEON $2011`-`$2032`, with the operand fetch removed."""
    writes = actions.newecl_writes(0, 20, disk=2, arrival=(1, 14, 1))
    assert writes == (
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
    assert writes[actions.WARP_FROM] == bytes([0x7F])
    assert writes[actions.WARP_SLOT] == bytes([1 | 0x80])


def test_a_square_is_only_written_when_there_is_one():
    """Six areas are placed by the arriving script's own entry 4, and area 7
    has a square but no facing."""
    plain = dict(actions.newecl_writes(0, 1))
    assert actions.WARP_X not in plain
    partial = dict(actions.newecl_writes(0, 7, arrival=(5, 7)))
    assert partial[actions.WARP_X] == bytes([5, 7])


def test_a_warp_writes_then_jumps_into_the_tail_of_newecl():
    target = machine(area=0)
    warp = actions.Warp()
    outcome = warp.apply(target, area=area(13))     # the kobold caves
    assert outcome.ok
    assert [addr for addr, _ in outcome.writes] == [
        actions.WARP_DISK, actions.WARP_X, actions.WARP_FROM,
        actions.WARP_SLOT, actions.WARP_SCRATCH]
    assert target.jumps == [0x2034]
    assert target.memory[actions.WARP_SLOT] == bytes([13 | 0x80])


def test_the_quest_flags_are_said_out_loud():
    outcome = actions.Warp().apply(machine(), area=area(20))
    assert any("quest flags" in note for note in outcome.notes)


# --- what it refuses ---------------------------------------------------------

def test_a_warp_is_refused_when_dungeon_is_not_resident():
    """`$2034` is some other overlay's code, and jumping there is a crash."""
    verdict = actions.Warp().legality(machine(mode=COMBAT), area(20))
    assert not verdict and "$6E11" in verdict.reason


def test_a_warp_is_refused_from_anywhere_but_the_key_wait_loop():
    """Mid-script or mid-load, the stack reload at `$203A` throws away work in
    flight. It is also the check that `PC_REGISTER` is the register we think."""
    target = machine(pc=0x2011)
    verdict = actions.Warp().legality(target, area(20))
    assert not verdict and "key-wait" in verdict.reason
    assert target.jumps == []


def test_a_warp_to_the_area_we_are_in_is_refused():
    """`NEWECL` skips a same-area transition, so `$4A00` would not be cleared
    and nothing would happen -- silently, which is the objection."""
    verdict = actions.Warp().legality(machine(area=20), area(20))
    assert not verdict and "already in that area" in verdict.reason


def test_a_backend_with_no_cpu_cannot_warp():
    plain = MemoryTarget({actions.MODE: bytes([WORLD])})
    verdict = actions.Warp().legality(plain, area(20))
    assert not verdict and "program counter" in verdict.reason


def test_nothing_is_written_by_a_refused_warp():
    target = machine(mode=COMBAT)
    before = dict(target.memory)
    outcome = actions.Warp().apply(target, area=area(20))
    assert not outcome.ok and outcome.writes == ()
    assert target.memory == before and target.jumps == []


# --- going back --------------------------------------------------------------

def test_warp_back_is_refused_until_a_warp_has_been_made():
    warp = actions.Warp()
    verdict = warp.back_verdict(machine())
    assert not verdict and "nothing to go back to" in verdict.reason


def test_warp_back_returns_to_the_square_the_warp_started_on():
    """The waypoint is read before the writes: the first two of them are the
    disk and the square, so one taken afterwards would record the destination."""
    target = machine(area=0, disk=3)
    warp = actions.Warp()
    assert warp.apply(target, area=area(20)).ok
    assert warp.back == actions.Waypoint(0, 3, (5, 6, 1))
    target.memory[actions.WARP_SLOT] = bytes([20])       # the game arrived
    target._pc = IN_THE_LOOP
    outcome = warp.apply_back(target)
    assert outcome.ok
    assert dict(outcome.writes)[actions.WARP_X] == bytes([5, 6, 1])
    assert dict(outcome.writes)[actions.WARP_SLOT] == bytes([0x80])
    assert warp.back is None                              # and no further back


# --- the area table ----------------------------------------------------------

def test_the_areas_come_from_por_areas_and_are_not_copied_here():
    """One table. `automap/actions.py` reads `por/areas.py` and holds no copy
    of its own; the row objects are that module's."""
    from por import areas as table
    assert actions.area_rows() == tuple(table.AREAS)


def test_an_arrival_square_is_taken_from_the_table():
    assert actions.Warp.arrival_of(area(0)) == (15, 1, 3)     # New Phlan
    assert actions.Warp.arrival_of(area(7)) == (5, 7)         # no facing known
    assert actions.Warp.arrival_of(area(9)) is None           # none harvested


def test_a_square_is_chosen_off_the_map_when_the_table_has_none():
    """The fallback for the fifteen areas nobody has harvested: never the
    party's current square, which is a wall in the next area along."""
    from por.geo import Geo
    from tests.gamedata import synthetic_geo
    geo = Geo(synthetic_geo())
    square = actions.walkable_square(geo)
    assert square is not None
    x, y, facing = square
    assert geo.is_passable(x, y, facing)
    assert actions.walkable_square(None) is None


# --- the row under the map ---------------------------------------------------

@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def bar(app, target=None, **kw):
    from automap.actionbar import WarpBar
    row = WarpBar(**kw)
    row.ask = lambda _question: True          # never open a dialog in a test
    if target is not None:
        row.attach(target)
    return row


def test_the_row_lists_every_area_by_name_with_the_unnamed_last(app):
    row = bar(app)
    assert row.combo.count() == len(actions.area_rows())
    names = [r.name for r in row.rows]
    assert names[0] is not None and names[-1] is None
    assert row.combo.itemText(0).startswith(names[0])
    assert ", POOL" in row.combo.itemText(0)


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


def test_the_disk_line_names_the_disk_the_area_is_on(app):
    row = bar(app, machine(area=0, disk=3))
    row.combo.setCurrentIndex(row.rows.index(area(13)))       # kobold caves
    assert "POOL8" in row.disk.text() and "POOL3" in row.disk.text()


def test_the_row_says_it_is_unproven_before_anything_is_clicked(app):
    row = bar(app)
    assert "No warp has ever been tried" in row.note.text()
    assert "copy of your save disk" in row.note.text()


def test_the_row_warps_what_the_combo_box_is_showing(app):
    target = machine(area=0)
    row = bar(app, target)
    row.combo.setCurrentIndex(row.rows.index(area(13)))
    outcome = row.run()
    assert outcome.ok
    assert target.memory[actions.WARP_SLOT] == bytes([13 | 0x80])
    assert target.memory[actions.WARP_X] == bytes([6, 15, 0])   # the table's
    assert target.jumps == [actions.NEWECL_TAIL]


def test_the_row_asks_first_and_a_no_writes_nothing(app):
    target = machine(area=0)
    row = bar(app, target)
    row.ask = lambda _question: False
    assert row.run() is None
    assert target.jumps == []


def test_a_refused_warp_is_reported_as_an_alarm(app):
    said = []
    row = bar(app, machine(mode=COMBAT),
              say=lambda text, detail="", alarm=False: said.append((text, alarm)))
    row.combo.setCurrentIndex(row.rows.index(area(13)))
    row.run()
    assert said and said[-1][1] is True
    assert "$6E11" in said[-1][0]


# --- the map window ----------------------------------------------------------

def window(app, tmp_path, monkeypatch, target=None, debug=True):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from automap.state import Automapper
    from automap.window import AutomapWindow
    return AutomapWindow(Automapper(target, {}), drive=False, debug=debug)


def test_the_warp_row_is_absent_unless_debug_mode_is_on(app, tmp_path,
                                                        monkeypatch):
    assert window(app, tmp_path, monkeypatch, debug=False).warp_bar is None
    assert window(app, tmp_path, monkeypatch, debug=True).warp_bar is not None


def test_the_window_reads_the_flag_when_none_is_passed(app, tmp_path,
                                                       monkeypatch):
    monkeypatch.delenv(debugmode.ENV, raising=False)
    assert window(app, tmp_path, monkeypatch, debug=None).warp_bar is None
    monkeypatch.setenv(debugmode.ENV, "1")
    assert window(app, tmp_path, monkeypatch, debug=None).warp_bar is not None


def test_the_warp_row_follows_the_poll(app, tmp_path, monkeypatch):
    target = machine(area=0)
    win = window(app, tmp_path, monkeypatch, target)
    for _ in range(win.LIVE_EVERY):
        win.tick()
    assert win.warp_bar.target is target
    assert win.warp_bar.button.isEnabled()


# --- choosing a backend ------------------------------------------------------

def fake_session(app):
    from wish.session import Session
    return Session(find=lambda pref=None: None)


def wish_window(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from wish.window import WishWindow
    return WishWindow(maps={}, session=fake_session(app))


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
    """Nobody on this project has a Commodore 64 Ultimate, and the menu must
    not imply otherwise."""
    import dataclasses

    from wish import backends
    win = wish_window(app, tmp_path, monkeypatch)
    monkeypatch.setattr(backends, "VICE",
                        dataclasses.replace(backends.VICE, probe=lambda: True))
    win.label_backends()
    assert win.backend_actions["VICE"].text() == "VICE - answering"
    for backend in backends.backends():
        if not backend.verified:
            assert "unverified" in win.backend_actions[backend.name].text()


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


def test_a_warp_is_verified_by_the_map_at_0400(app):
    """An exact 1024-byte match against the disk copy: a hit is certain and
    needs no fingerprinting."""
    from por.geo import Geo
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
    assert "byte for byte" in row_bar.note.text()


def test_an_area_change_is_given_thirty_seconds(app, monkeypatch):
    """Not five. Stepping into an encounter in New Phlan takes about 25 to
    load, and four runs "died" on a timeout that was too short."""
    import automap.actionbar as ab
    from por.geo import Geo
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
    assert row_bar._pending is None
    assert "after 30s" in row_bar.note.text()


def test_nothing_is_read_at_0400_when_no_warp_is_in_flight(app):
    target = machine()
    row = bar(app, target, maps={"GEO0D": None})
    target.reads.clear()
    row.attach(target)
    assert not [r for r in target.reads if r[0] == 0x0400]
