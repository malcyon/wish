from __future__ import annotations

"""The combat view, against a captured fight.

The arena is composed rather than captured -- see `tests/gamedata.py`. It used
to be a snapshot of live memory taken out of a running
machine at `work/drive/c3-combat1.bin` and trimmed to the seven ranges the view
reads. It is stored as chunks of `addr, length, bytes` so the addresses travel
with the data and nothing here has to repeat them.
"""


import dataclasses
import pathlib

import pytest
from gamedata import synthetic_arena

from automap import combat
from automap.render import Label
from automap.state import Automapper
from automap.target import MemoryTarget

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def arena() -> MemoryTarget:
    """A duel: the party's slot 0 at (25,13) against a monster at (30,13).

    Composed by `tests/gamedata.py` from the player's own saved games plus a
    generated map and position table -- not a capture of live machine memory,
    which would carry whatever game code was resident at the time.
    """
    return MemoryTarget(synthetic_arena())


@pytest.fixture
def battle():
    return combat.read_battle(arena())


# --- the gate ---------------------------------------------------------------

def test_no_fight_means_no_combat_memory_is_read():
    """$8B00 reads as a graphics buffer in the world, not as $FF, so an
    ungated reader draws 64 combatants stacked at (0,0)."""
    machine = arena()
    machine.memory[combat.MODE] = b"\x01"          # DUNGEON, not COMBAT
    assert combat.read_battle(machine) is None
    assert all(addr in (combat.MODE, combat.PARAMS, combat.CAMERA)
               for addr, _ in machine.reads)


def test_a_parameter_block_that_cannot_be_one_is_refused():
    """$0600 is ordinary RAM between fights. The captured world snapshot reads
    `00 08 00 00 00 8c ...` there -- a map base of zero."""
    machine = arena()
    machine.memory[combat.PARAMS] = bytes.fromhex(
        "00 08 00 00 00 8c 8b 8d 90 91 00 00 00 00 00 00 00 87 80 87".replace(" ", ""))
    assert combat.read_battle(machine) is None


def test_the_shape_is_read_and_never_assumed():
    """`SQRPACI00` bounds 17 x 35, so hard-coding 56 x 26 would be wrong."""
    block = bytearray(synthetic_arena()[combat.PARAMS])
    block[combat.P_STRIDE] = 20
    block[combat.P_MAX_X], block[combat.P_MAX_Y] = 17, 35
    shape = combat.shape_from_params(bytes(block))
    assert (shape.stride, shape.width, shape.height) == (18, 18, 36)
    assert shape.length == 18 * 36
    assert shape.index(3, 2) == 39


def test_the_stride_comes_from_the_bounds_not_from_0607():
    """`GDRIVE00 $C3AF` is `LDX $0612 / INX / STX $4B`: the renderer derives
    the row stride from the maximum square, and `$0607` is something else.

    In a fight both are 56 and it never shows. `SQRPACI00` has `$0607` = 20
    against a true 18, and 18 x 36 = 648 is exactly the grid in front of the
    glyph table in a `SQRDATA` file. This test is here because the earlier one
    asserted the wrong field and would have sheared the overland map.
    """
    block = bytearray(synthetic_arena()[combat.PARAMS])
    block[combat.P_STRIDE] = 99                 # nonsense, and ignored
    block[combat.P_MAX_X], block[combat.P_MAX_Y] = 17, 35
    assert combat.shape_from_params(bytes(block)).stride == 18


# --- what the fight holds ---------------------------------------------------

def test_the_captured_duel_decodes(battle):
    assert (battle.shape.width, battle.shape.height) == (56, 26)
    assert battle.shape.map_base == 0x8C00 and battle.shape.stride == 56
    assert battle.camera == (22, 10)
    assert [(c.index, c.name, c.square) for c in battle.combatants] == [
        (0, "BRUTUS", (25, 13)), (8, "ORC", (30, 13))]


def test_the_party_is_the_first_eight_slots(battle):
    """0-7 the party in save-slot order, 8 upward the monsters -- the same
    encoding the effects owner byte uses."""
    assert [c.index for c in battle.party] == [0]
    assert [c.index for c in battle.enemies] == [8]
    assert battle.party[0].kind == "party" and battle.enemies[0].kind == "enemy"


def test_bit_seven_of_a_square_agrees_with_the_position_table(battle):
    """Occupancy is in the map as well as in $8B00, so the two check each
    other. $C086 BPL branches past the glyph lookup when bit 7 is set."""
    standing = {c.square for c in battle.combatants}
    marked = {(x, y)
              for y in range(battle.shape.height)
              for x in range(battle.shape.width) if battle.occupied(x, y)}
    assert marked == standing
    assert all(battle.square(x, y) == 0 for x, y in standing)   # floor beneath


def test_the_combat_numbers_come_from_the_roster_not_the_record(battle):
    """$0E1 is the unarmoured base -- AC 10 for every player character -- and
    the roster block carries the AC they are actually fighting at."""
    brutus = battle.party[0]
    assert (brutus.hp, brutus.hp_max) == (11, 11)
    assert (brutus.armour_class, brutus.thac0) == (9, 18)
    assert brutus.record.armour_class_base_value == 10


def test_a_round_is_over_when_every_initiative_byte_is_spent(battle):
    assert not battle.round_over
    assert {c.index: c.initiative for c in battle.combatants} == {0: 2, 8: 1}


def test_the_whole_fight_costs_two_bursts():
    machine = arena()
    combat.read_battle(machine)
    assert [addr for addr, _ in machine.reads] == [
        combat.MODE, combat.PARAMS, combat.CAMERA,
        0x8C00, combat.ROSTER, 0x8B00, combat.INITIATIVE, combat.RECORDS]


# --- the tooltip ------------------------------------------------------------

def test_the_tooltip_only_shows_what_is_decoded(battle):
    lines = battle.enemies[0].lines()
    assert lines[0] == "8. ORC  (30,13)"
    assert "5 / 5 hp" in lines
    assert "AC 6   THAC0 19   move 9" in lines
    assert "1 hit dice" in lines
    # 10 + 1 a hit point, times 5 hit points -- the Monster Manual orc.
    assert "15 experience" in lines
    assert any(line.startswith("saves 14 / 15 / 16 / 17 / 17") for line in lines)


def test_a_trait_code_nobody_has_named_shows_its_number(battle):
    """Visibly unnamed rather than silently dropped -- that is how a new code
    gets noticed."""
    who = battle.enemies[0]
    raw = bytearray(who.record.to_bytes())
    raw[0x0AD], raw[0x0AE] = 83, 200      # one named, one not
    who.record.set_raw("item_effects", bytes(raw[0x0AD:0x0B7]))
    lines = who.lines()
    assert "petrifying gaze" in lines
    assert "trait 200" in lines


def test_the_fill_byte_is_not_a_trait(battle):
    """255 is the byte after the last used slot in a MON* record. A live ORC
    carries it, and printing "fill, not a code" as a trait is noise."""
    who = battle.enemies[0]
    who.record.set_raw("item_effects", bytes([255] + [0] * 9))
    assert not [line for line in who.lines() if "fill" in line]


def test_a_dead_combatant_is_dimmed_rather_than_removed(battle):
    dead = combat.Combatant(index=9, x=4, y=5, slot=9, pose=0, on_map=True,
                            initiative=0, hp=0, hp_max=7)
    assert dead.dimmed and dead.kind == "enemy-dim"
    assert "dead or gone from the fight" in dead.lines()


def test_one_that_leaves_the_map_keeps_its_last_square(battle):
    """$FF $FF is off the map. Removing it would lose what happened; the last
    square it stood on is remembered from the previous poll and dimmed."""
    machine = arena()
    # The position table sits immediately past the 64 roster blocks, so it is
    # inside the one $8300 chunk rather than beside it.
    page = bytearray(machine.memory[combat.ROSTER])
    at = 0x8B00 - combat.ROSTER + 8 * combat.POSITION_STRIDE
    page[at], page[at + 1] = 0xFF, 0xFF
    machine.memory[combat.ROSTER] = bytes(page)
    after = combat.read_battle(machine, previous=battle)
    gone = next(c for c in after.combatants if c.index == 8)
    assert gone.square == (30, 13) and not gone.on_map and gone.dimmed
    # ...but never invented: with nothing remembered there is nothing to draw.
    assert [c.index for c in combat.read_battle(machine).combatants] == [0]


# --- geometry ---------------------------------------------------------------

def test_only_the_part_of_the_map_the_fight_uses_is_drawn(battle):
    """56 x 26 is 1456 squares and both maps seen put the action in a corner."""
    x0, y0, w, h = combat.extent(battle)
    assert (w, h) < (battle.shape.width, battle.shape.height)
    assert all(x0 <= c.x < x0 + w and y0 <= c.y < y0 + h
               for c in battle.combatants)
    assert combat.cell_for(w) <= combat.CELL_MAX


def test_the_battlefield_draws_ground_and_combatants(battle):
    prims = list(combat.battlefield(battle))
    kinds = [p.kind for p in prims]
    assert kinds.count("party") == 1 and kinds.count("enemy") == 1
    assert kinds.count("camera") == 1
    assert "block" in kinds                       # the arena has walls in view
    hp = [p for p in prims if isinstance(p, Label)]
    assert sorted(p.text for p in hp) == ["11", "5"]


def test_whoever_may_still_act_is_outlined(battle):
    """$A380 counts initiative down and the round ends when all 64 are zero,
    so a non-zero byte is somebody who has not moved yet."""
    kinds = [p.kind for p in combat.battlefield(battle)]
    assert kinds.count("ready") == 2                 # both, at the round's start
    spent = dataclasses.replace(
        battle, combatants=tuple(dataclasses.replace(c, initiative=0)
                                 for c in battle.combatants))
    assert "ready" not in [p.kind for p in combat.battlefield(spent)]
    assert spent.round_over


def test_a_click_lands_on_the_square_under_it(battle):
    box = combat.extent(battle)
    cell = combat.cell_for(box[2])
    x0, y0 = box[0], box[1]
    px = combat.MARGIN + (25 - x0) * cell + cell / 2
    py = combat.MARGIN + (13 - y0) * cell + cell / 2
    assert combat.square_at(px, py, box, cell) == (25, 13)
    assert combat.square_at(-5, -5, box, cell) is None
    assert battle.at(25, 13).name == "BRUTUS"


# --- the tab ----------------------------------------------------------------

def make_window(app, tmp_path, monkeypatch, target):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from automap.window import AutomapBinding
    from PyQt6.QtWidgets import QMainWindow
    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    return AutomapBinding(root, Automapper(target, {}), drive=False)


def test_the_canvas_swaps_on_the_mode_flag_and_back(app, tmp_path, monkeypatch):
    """And the area map's explored squares survive the round trip."""
    machine = arena()
    machine.memory[combat.MODE] = b"\x01"
    window = make_window(app, tmp_path, monkeypatch, machine)
    window.state.exploration.visit(3, 4)

    for _ in range(window.LIVE_EVERY):
        window.tick()
    assert window.stack.currentWidget() is window.canvas
    seen = set(window.state.exploration.seen)

    machine.memory[combat.MODE] = b"\x02"
    for _ in range(window.LIVE_EVERY):
        window.tick()
    assert window.stack.currentWidget() is window.battle_canvas
    assert window.battle is not None
    assert "combat" in window.status_text()

    machine.memory[combat.MODE] = b"\x01"
    window.tick()
    assert window.stack.currentWidget() is window.canvas
    assert window.battle is None
    assert window.state.exploration.seen == seen


def test_the_canvas_answers_a_tooltip(app, tmp_path, monkeypatch, battle):
    from automap.window import CombatCanvas
    canvas = CombatCanvas()
    canvas.show_battle(battle)
    x0, y0, w, _ = canvas.box
    cell = canvas.cell
    px = combat.MARGIN + (30 - x0) * cell + cell / 2
    py = combat.MARGIN + (13 - y0) * cell + cell / 2
    assert canvas.tooltip_at(px, py).startswith("8. ORC")
    assert canvas.tooltip_at(combat.MARGIN + cell / 2,
                             combat.MARGIN + cell / 2) is None
