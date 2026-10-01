"""`goldbox/curse_worldmap.py`: Curse's world map read by the statements that use it.

The synthetic tests assemble scripts here from the instruction formats, with
made-up place names and tables, so they run without the game. The player-disk
tests read `ECL50`, `ECL51` and `GDRIVE02` off the player's own Curse disks.
"""

from __future__ import annotations

import gamedata
import pytest

from goldbox import curse_worldmap as W
from goldbox.d64 import split_load_address

BASE = 0x8000
CHOICE = 0x7F79
INDEX = 0x7F7A
NAME_TEXT = 0x7B01
MENU_TEXT = 0x7B33


def pack(text: str) -> bytes:
    """The game's six-bit packing, run forwards: letters drop to `$01`-`$1A`."""
    groups = [ord(c) - 0x40 if "A" <= c <= "Z" else ord(c) for c in text] + [0]
    bits = "".join(f"{g:06b}" for g in groups)
    bits += "0" * (-len(bits) % 8)
    return bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8))


def imm(value):
    return ("imm", value)


def addr(where):
    return ("addr", where)


def text(words):
    return ("str", words)


class Assembler:
    """Lays statements out at `BASE`; an address may name a label."""

    def __init__(self):
        self.items: list = []

    def label(self, name):
        self.items.append(("label", name))

    def op(self, code, *operands):
        self.items.append(("op", code, operands))

    def data(self, raw: bytes):
        self.items.append(("data", bytes(raw)))

    @staticmethod
    def _size(operand):
        kind, value = operand
        return {"imm": 2, "addr": 3}.get(kind) or 2 + len(pack(value))

    def build(self) -> bytes:
        labels, at = {}, 0
        for item in self.items:
            if item[0] == "label":
                labels[item[1]] = BASE + at
            elif item[0] == "op":
                at += 1 + sum(self._size(o) for o in item[2])
            else:
                at += len(item[1])
        out = bytearray()
        for item in self.items:
            if item[0] == "op":
                out.append(item[1])
                for kind, value in item[2]:
                    if kind == "imm":
                        out += bytes((0x00, value))
                    elif kind == "addr":
                        a = labels[value] if isinstance(value, str) else value
                        out += bytes((0x01, a & 0xFF, a >> 8))
                    else:
                        payload = pack(value)
                        out += bytes((0x80, len(payload))) + payload
            elif item[0] == "data":
                out += item[1]
        return bytes(out)


def script(names, table, width, menus, leaving=(), waypoints=None,
           decoy=None):
    """A world-map script in the game's instruction formats.

    `menus` maps a place to its JOURNEY ON rows, or to a pair (short, full)
    for a place whose last row is offered on a condition. `decoy` is a block
    of data placed before the real table, which the reader must not take.
    """
    a = Assembler()
    for entry in ("start", "start", "start", "start", "start"):
        a.op(W.GOTO, addr(entry))
    a.label("start")
    a.op(W.GOSUB, addr("neighbours"))
    a.op(W.ONGOTO, addr(W.NODE), imm(len(names)),
         *[addr(f"menu{n}") for n in range(len(names))])
    for n in range(len(names)):
        a.label(f"menu{n}")
        rows = menus.get(n, ())
        if rows and isinstance(rows[0], tuple):
            short, full = rows
            a.op(W.BOTH_EQUAL, addr(0x4C59), imm(1), addr(0x4C5A), imm(1))
            a.op(0x16)
            a.op(W.GOTO, addr(f"full{n}"))
            a.op(W.MENU, addr(CHOICE), addr(MENU_TEXT), imm(len(short)),
                 *[text(r) for r in short])
            a.op(W.GOTO, addr("choice"))
            a.label(f"full{n}")
            a.op(W.MENU, addr(CHOICE), addr(MENU_TEXT), imm(len(full)),
                 *[text(r) for r in full])
        else:
            a.op(W.MENU, addr(CHOICE), addr(MENU_TEXT), imm(len(rows)),
                 *[text(r) for r in rows])
        a.op(W.GOTO, addr("choice"))
    a.label("choice")
    a.op(W.GETTABLE, addr(W.NEIGHBOURS), addr(CHOICE), addr(W.DESTINATION))
    a.op(W.GOSUB, addr("names"))
    a.op(W.ADD, addr(CHOICE), addr(W.LEG), addr(W.LEG))
    for leg, other in leaving:
        a.op(W.COMPARE, addr(W.LEG), imm(leg))
        a.op(0x16)
        a.op(W.NEWECL, imm(other))
    if waypoints is not None:
        a.op(W.GETTABLE, addr("waypoints"), addr(W.LEG), addr(W.MARKER))
    a.op(W.RETURN)
    a.label("neighbours")
    a.op(W.MUL, addr(W.DESTINATION), imm(width), addr(INDEX))
    a.op(W.SAVE, addr(INDEX), addr(W.LEG))
    for slot in range(width):
        if slot:
            a.op(W.ADD, imm(1), addr(INDEX), addr(INDEX))
        a.op(W.GETTABLE, addr("table"), addr(INDEX), addr(W.NEIGHBOURS + slot))
    a.op(W.RETURN)
    a.label("names")
    a.op(W.ONGOTO, addr(W.DESTINATION), imm(len(names)),
         *[addr(f"name{n}") for n in range(len(names))])
    for n, name in enumerate(names):
        a.label(f"name{n}")
        if name is not None:
            a.op(W.SAVE, text(name), ("addr", NAME_TEXT))
        a.op(W.RETURN)
    if decoy is not None:
        a.data(decoy)
    a.label("table")
    a.data(bytes(table))
    if waypoints is not None:
        a.label("waypoints")
        a.data(bytes(waypoints))
    return a.build()


NO = W.NO_ROAD
#: Four places, three slots each: 1-3 is listed from 3 only, 2-3 only on a
#: condition from 2.
TABLE = [1, 2, NO,  0, NO, NO,  0, 3, NO,  2, 1, NO]
NAMES = ["AMBER", "BRIGHT FORD", "COLD HILL", "DUN"]
MENUS = {0: ("BRIGHT FORD", "COLD HILL"), 1: ("AMBER",),
         2: (("AMBER",), ("AMBER", "DUN")), 3: ("COLD HILL", "BRIGHT FORD")}


def test_the_packing_here_is_the_one_the_reader_unpacks():
    assert W.unpack(pack("COLD HILL, 3'S.")) == "COLD HILL, 3'S."


def test_one_script_gives_places_roads_and_names():
    body = script(NAMES, TABLE, 3, MENUS)
    world = W.read_world_map({"ECL50": body})
    assert [p.name for p in world.places] == NAMES
    assert [p.script for p in world.places] == [0x50] * 4
    assert [(r.a, r.b) for r in world.roads] == [(0, 1), (0, 2), (1, 3), (2, 3)]
    assert [(r.a, r.b) for r in world.roads if r.one_way] == [(1, 3)]
    one_way = next(r for r in world.roads if r.one_way)
    assert one_way.forward is None and one_way.backward.source == 3


def test_the_row_width_comes_from_the_code():
    body = script(NAMES, TABLE, 3, MENUS)
    world = W.read_world_map({"ECL50": body})
    leg = next(g for g in world.legs if (g.source, g.target) == (3, 1))
    assert (leg.slot, leg.index) == (1, 3 * 3 + 1)


def test_a_row_offered_in_only_some_menus_is_conditional():
    world = W.read_world_map({"ECL50": script(NAMES, TABLE, 3, MENUS)})
    flags = {(g.source, g.target): g.conditional for g in world.legs}
    assert flags[(2, 3)] is True
    assert flags[(2, 0)] is False
    assert world.places[2].rows == ("AMBER", "DUN")


def test_the_table_is_the_one_the_code_reads_not_a_lookalike():
    wrong = [3, 2, 1] * 4
    body = script(NAMES, TABLE, 3, MENUS, decoy=bytes(wrong))
    world = W.read_world_map({"ECL50": body})
    assert [(r.a, r.b) for r in world.roads] == [(0, 1), (0, 2), (1, 3), (2, 3)]


def test_a_menu_that_disagrees_with_the_table_is_refused():
    menus = {**MENUS, 1: ("AMBER", "DUN")}
    with pytest.raises(W.WorldMapError, match="place 1"):
        W.read_world_map({"ECL50": script(NAMES, TABLE, 3, menus)})


def test_no_neighbour_routine_is_refused():
    with pytest.raises(W.WorldMapError, match="0 routines"):
        W.read_script(bytes(64), 0x50)


#: Two scripts sharing one table: places 0-1 in `$50`, 2-3 in `$51`, and the
#: legs 1->2 (index 3) and 2->1 (index 4) hand over.
SHARED = [1, NO,  0, 2,  1, 3,  2, NO]


def test_two_scripts_each_name_only_the_places_they_handle():
    left = script(["AMBER", "BRIGHT FORD", "COLD HILL", "COLD HILL"], SHARED, 2,
                  {0: ("BRIGHT FORD",), 1: ("AMBER", "COLD HILL")},
                  leaving=[(3, 0x51)])
    right = script(["BRIGHT FORD", "BRIGHT FORD", "COLD HILL", "DUN"], SHARED, 2,
                   {2: ("BRIGHT FORD", "DUN"), 3: ("COLD HILL",)},
                   leaving=[(4, 0x50)])
    world = W.read_world_map({"ECL50": left, "ECL51": right})
    assert [p.name for p in world.places] == NAMES
    assert [p.script for p in world.places] == [0x50, 0x50, 0x51, 0x51]
    hand = {g.index: g.leaves_for for g in world.legs if g.leaves_for}
    assert hand == {3: 0x51, 4: 0x50}
    assert len(world.roads) == 3 and not any(r.one_way for r in world.roads)


def test_a_place_its_owner_does_not_name_is_unknown():
    left = script(["AMBER", "BRIGHT FORD", "COLD HILL", "COLD HILL"], SHARED, 2,
                  {0: ("BRIGHT FORD",), 1: ("AMBER", "COLD HILL")},
                  leaving=[(3, 0x51)])
    right = script(["BRIGHT FORD", "BRIGHT FORD", "COLD HILL", None], SHARED, 2,
                   {2: ("BRIGHT FORD", "DUN"), 3: ("COLD HILL",)},
                   leaving=[(4, 0x50)])
    world = W.read_world_map({"ECL50": left, "ECL51": right})
    assert world.places[3].name is None


def test_scripts_with_different_tables_are_refused():
    left = script(NAMES, TABLE, 3, MENUS)
    other = list(TABLE)
    other[0] = 3
    right = script(NAMES, other, 3, {0: ("DUN", "COLD HILL"), **{
        k: v for k, v in MENUS.items() if k}})
    with pytest.raises(W.WorldMapError, match="differs"):
        W.read_world_map({"ECL50": left, "ECL51": right})


def test_waypoints_are_read_per_leg():
    marks = [4, 5, NO, 4, NO, NO, 5, 6, NO, 6, 7, NO]
    body = script(NAMES, TABLE, 3, MENUS, waypoints=marks)
    world = W.read_world_map({"ECL50": body})
    got = {(g.source, g.target): g.waypoint for g in world.legs}
    assert got[(0, 1)] == 4 and got[(3, 1)] == 7


def driver(columns, rows, base=0xC000):
    """A display driver: two JMPs, the marker routine, then the tables."""
    code = bytearray()
    code += bytes((0x4C, 0x10, base >> 8 & 0xFF, 0x4C, 0x20, base >> 8 & 0xFF))
    code += bytes(0x20 - len(code))
    tables = 0x40
    col_at, row_at = base + tables, base + tables + len(columns)
    code += bytes((0xAE, W.MARKER & 0xFF, W.MARKER >> 8,
                   0xBD, row_at & 0xFF, row_at >> 8, 0x18, 0x69, 0x01))
    code += bytes((0xAE, W.MARKER & 0xFF, W.MARKER >> 8,
                   0xBC, col_at & 0xFF, col_at >> 8, 0xC8, 0x60))
    code += bytes(tables - len(code))
    return bytes(code + bytes(columns) + bytes(rows))


def test_marker_cells_are_column_then_row_one_cell_on():
    cells = W.read_marker_cells(driver([3, 11, 20], [14, 6, 10]))
    assert cells == ((4, 15), (12, 7), (21, 11))


def test_marker_cells_join_the_places():
    body = script(NAMES, TABLE, 3, MENUS)
    world = W.read_world_map({"ECL50": body},
                             driver([0, 1, 2, 3, 9], [5, 6, 7, 8, 9]))
    assert [p.cell for p in world.places] == [(1, 6), (2, 7), (3, 8), (4, 9)]
    assert len(world.cells) == 5


def test_a_driver_without_the_marker_tables_is_refused():
    with pytest.raises(W.WorldMapError, match="no column and row"):
        W.read_marker_cells(bytes((0x4C, 0x10, 0xC0, 0x4C, 0x20, 0xC0)) + bytes(64))


# -- the player's disks -------------------------------------------------------

#: The fourteen places, in `$4C9B` order, as each owning script prints them.
CURSE_PLACES = [
    "TILVERTON", "SHADOWDALE", "ASHABENFORD", "DAGGER FALLS", "STANDING STONES",
    "VOONLAR", "PHLAN", "TESHWAVE", "ESSEMBRA", "HAP", "YULASH", "HILLSFAR",
    "ZHENTIL KEEP", "MYTH DRANNOR",
]


def _payload(name):
    return split_load_address(gamedata.curse_file(name))[1]


@pytest.fixture(scope="module")
def curse_world():
    return W.read_world_map({n: _payload(n) for n in ("ECL50", "ECL51")},
                            _payload("GDRIVE02"))


@gamedata.needs_curse_disks
def test_curse_has_fourteen_places_and_twenty_roads(curse_world):
    assert len(curse_world.places) == 14
    assert len(curse_world.roads) == 20
    assert [p.name for p in curse_world.places] == CURSE_PLACES
    assert {p.script for p in curse_world.places} == {0x50, 0x51}


@gamedata.needs_curse_disks
def test_curse_tilverton_to_dagger_falls_is_the_one_road_listed_one_way(curse_world):
    one_way = [(r.a, r.b) for r in curse_world.roads if r.one_way]
    assert one_way == [(0, 3)]
    road = next(r for r in curse_world.roads if (r.a, r.b) == (0, 3))
    assert road.forward.conditional is False and road.backward is None
    assert curse_world.places[3].rows == ("SHADOWDALE", "TESHWAVE")


@gamedata.needs_curse_disks
def test_curse_standing_stones_to_myth_drannor_is_the_one_conditional_leg(curse_world):
    assert [(g.source, g.target) for g in curse_world.legs if g.conditional] == [(4, 13)]
    assert all(g.conditional is not None for g in curse_world.legs)


@gamedata.needs_curse_disks
def test_curse_hand_overs_are_the_three_border_roads_each_way(curse_world):
    hand = sorted((g.source, g.target, g.leaves_for)
                  for g in curse_world.legs if g.leaves_for)
    assert hand == [(1, 5, 0x51), (3, 7, 0x51), (4, 11, 0x51),
                    (5, 1, 0x50), (7, 3, 0x50), (11, 4, 0x50)]


@gamedata.needs_curse_disks
def test_curse_shadowdale_marker_cell_is_where_the_live_run_saw_it(curse_world):
    """The run measured the marker at column 12, row 7 with `$4C9B` = 1."""
    assert curse_world.places[1].cell == (12, 7)
    assert len(curse_world.cells) == 32
    assert all(0 <= c < 40 and 0 <= r < 16 for c, r in curse_world.cells)


@gamedata.needs_curse_disks
def test_curse_reader_agrees_with_the_tools_decoder():
    """Every opcode read here has the operand count `DUNGEON` gives it, and
    every name decodes the same through `tools/areas/ecltext.py`."""
    from tools.areas import eclsweep, ecltext
    machine = eclsweep.Machine(_payload("DUNGEON"), "curse-of-the-azure-bonds")
    for op, count in W.OPERANDS.items():
        assert machine.operands(op) == count, f"opcode ${op:02X}"
    for op, count in W.COUNTED.items():
        assert eclsweep.COUNTED[op] == count
    for name in ("ECL50", "ECL51"):
        body = _payload(name)
        reached = eclsweep.walk(machine, body, BASE)
        seen = {}
        for at, statement in reached.items():
            if statement.op == W.SAVE and body[at + 1] == W.STRING:
                n = body[at + 2]
                seen[at] = (W.unpack(body[at + 3:at + 3 + n]),
                            ecltext.unpack(body[at + 3:at + 3 + n]))
        assert seen and all(a == b for a, b in seen.values())
        found = W.read_script(body, int(name[3:], 16))
        assert found.base == BASE
        fills = [s for s in reached.values() if s.op == W.GETTABLE
                 and s.address(2) == W.NEIGHBOURS]
        assert len(fills) == 1
        at = fills[0].address(0) - BASE
        assert body[at:at + len(found.table)] == found.table


@gamedata.needs_curse_disks
def test_curse_scripts_run_where_the_tools_walk_says():
    from goldbox import c64_port
    from tools.areas import eclsweep
    game = c64_port.by_key("curse-of-the-azure-bonds")
    _machine, base, *_ = eclsweep.load_port(
        eclsweep.registry(game.key), game, None)
    assert base == BASE
