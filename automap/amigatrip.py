"""Fast Travel on an Amiga title, by the game's own script statements.

The C64 trip ends by setting the program counter, which no Amiga backend lets
Wish do. The Amiga engine is the DOS one, where `NEWECL` loads the next area's
script and raises a flag the main loop acts on, so a trip is three writes:

1. a few of the game's own statements (`SAVE` the square, then `NEWECL area`)
   at the end of the loaded area's 0x1E00-byte script buffer, past the script;
2. the **step entry**, the word the main loop hands the interpreter once a
   forward key leaves the 3D menu, pointed at them;
3. one forward key: `01 b8` in the one-key buffer (Curse, Silver Blades, Pools
   of Darkness), or a RAWKEY message linked onto the game window's port (Pool
   of Radiance, whose menu reads its messages itself).

The game's interpreter then changes the area, with its own loader, disk prompt,
came-from byte and arriving script. Measured under `fs-uae-gdb` in Curse (2
trips), Pool of Radiance (4) and Pools of Darkness (3); Silver Blades was read
from its code only. `docs/96-live-memory-automapper.md`, "Fast Travel and
Return without the program counter", has the per-title table and the grades.

**Nothing here is game data.** The statements are built from opcode numbers and
operand forms; a script's length is read off the player's disk at run time by
`script_lengths`, and never stored.

**Where the bytes go.** The statements end at the buffer's last byte, and on
Pool of Radiance the 52-byte message sits below them, longword-aligned. A tier
says whether that fits past the departing area's script:

* tier 1, every statement in the buffer;
* tier 2, only `NEWECL` in the buffer, with the square written straight into
  the engine's variables first. **No row has it confirmed**, so `free_tail`
  never answers 2 until a live run sets `direct_confirmed`;
* tier 3, no trip from that area.

**The init span.** An area whose script leaves too little tail (Pool of
Radiance's Buccaneer Base and Zhentil Outpost) has its **init entry**, the
fifth header word, run only when the loader has just filled the buffer, and
nothing else reaches it. The statements and the message go at that entry's
bytes, the last ones of the script, and `INIT_ROOM` names each such span by
its offset and the SHA-1 of its bytes on the disk. A trip is placed there only
for a disk whose span hashes to it, and armed only while the live span still
reads as the disk's. A save made while such a trip is armed would run it on
loading, so every write is journalled to a file first, and `repair` puts it
back after a crash. Every trip `arm` writes is journalled, tail trips too, since
a crash partway leaves statements that block the next arm.

**A trip that does not fire is put back.** `disarm` writes back every word that
still holds what `arm` wrote, newest first, and leaves alone any the game has
since changed. **Silver Blades and Pools of Darkness do not clear the buffer
before a load**, so after their trips `tidy` zeroes the statements that still
read as written and lie past the arriving area's script.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import pathlib
import re
import struct
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from . import amiga, departures
from .target import NotConnected

_log = logging.getLogger("wish.automap.amigatrip")

#: Every title's script buffer, zero-filled to this size before the block is
#: copied in (Pool of Radiance, Curse) or with the last area's bytes left past
#: the block (Silver Blades, Pools of Darkness).
BUFFER_SIZE = 0x1E00

#: Opcodes, the same in all four dispatch tables: `SAVE value, [address]` and
#: `NEWECL area`.
SAVE = 0x09
NEWECL = 0x20
#: The boat exit's redraw statements: `PICTURE value`, `CLEAR BOX` and
#: `LOADFILES a, b, c`.
PICTURE = 0x0E
CLEAR_BOX = 0x3D
LOADFILES = 0x21

#: Operand forms: a one-byte immediate, and a little-endian two-byte address.
IMMEDIATE = 0x00
ADDRESS = 0x01

#: The one-key buffer's `flag, character` for a pending keypad 8.
FORWARD_KEY = b"\x01\xb8"

#: Pool of Radiance's synthetic key: an `IntuiMessage` of class RAWKEY, code
#: raw key 8, node type `NT_MESSAGE`, no reply port.
MESSAGE_SIZE = 0x34
NT_MESSAGE = 5
RAWKEY = 0x400
RAW_KEY_8 = 0x08
#: `struct Window` to its `UserPort`, and `struct MsgPort` to its `mp_MsgList`.
WINDOW_USERPORT = 0x56
#: The window's first gadget, and the fields of an Intuition gadget.
WINDOW_FIRST_GADGET = 0x3E
GADGET_NEXT = 0x00
GADGET_LEFT_EDGE = 0x04
GADGET_WIDTH = 0x08
GADGET_ID = 0x26
FIRST_GADGET_ID = 1000
CHARACTER_WIDTH = 8
PORT_LIST = 0x14

#: How the facing is stored in memory: doubled, 0 north to 6 west.
FACING_SCALE = 2


# -- the rows ----------------------------------------------------------------


@dataclass(frozen=True)
class Spot:
    """Where a value sits in memory, as an offset into the data hunk.

    With `pointer`, the address is the `u32` at that data-hunk offset plus
    `offset`. The value is stored big-endian in `width` bytes, multiplied by
    `scale` (2 for the doubled facing).
    """

    offset: int
    width: int = 1
    scale: int = 1
    pointer: int | None = None


@dataclass(frozen=True)
class Difference:
    """A trip that behaves differently from the C64's, held until decided.

    `covers(here, to, back)` says whether a trip from area `here` to area `to`
    (`back` for Return) is one of them; `offered` stays False until Donald
    decides, or until the measurement named in `waits_on` is made.
    """

    name: str
    waits_on: str
    test: Callable[..., bool] = field(compare=False)
    offered: bool = False

    def covers(self, here: int | None, to: int | None, back: bool) -> bool:
        return bool(self.test(here, to, back))


@dataclass(frozen=True)
class TripRow:
    """One title's trip, as data-hunk offsets (`h32` on Pool of Radiance).

    `confirmed` is True only where a trip was measured live with these
    addresses; `direct_confirmed` only where a tier-2 direct square write was.
    """

    key: str
    title: str
    #: `u16be`: the ECL address the main loop runs after a forward key.
    step_entry: int
    #: `u32`: the script buffer, whose byte 0 is `[pointer] + buffer_bias`
    #: and has the ECL address `ecl_origin`.
    buffer_pointer: int
    buffer_bias: int
    ecl_origin: int
    #: The area id byte, `EclBlockId`.
    area: int
    #: The mode byte and its value walking in the 3D view.
    mode: int
    clears_buffer: bool
    #: The ECL addresses `SAVE` writes for x, y and facing.
    square_targets: tuple[int, int, int]
    #: The same three in memory, for a tier-2 write and for `square`.
    square_spots: tuple[Spot, Spot, Spot]
    world_mode: int = 4
    #: Pools of Darkness: the mode, menu kind and menu text of an overland,
    #: where the one menu item reads as `Encamp` (PROBABLE, not read live).
    overland_mode: int | None = None
    overland_menu_kind: int | None = None
    overland_menu_text: bytes | None = None
    #: The menu-kind word (1 at a horizontal menu), where the menu's text is,
    #: and the world menu's text, which is NUL-terminated in memory.
    menu_kind: int | None = None
    menu_at: int | None = None
    menu_text: bytes | None = None
    #: The one-key buffer, `flag, character`.
    key_buffer: int | None = None
    #: The area-file byte the exits set (`$7F12`), and where it is in memory.
    area_file: int | None = None
    area_file_spot: Spot | None = None
    #: The travel-grid square: Pool of Radiance's `$49C3`/`$49C4` (and
    #: `$49E6`), Pools of Darkness' overland cell `$25`/`$26`. Only Pool of
    #: Radiance has `grid_spots` to read it back.
    grid_targets: tuple[int, int] | None = None
    grid_spots: tuple[Spot, Spot] | None = None
    indoors_spot: Spot | None = None
    grid_areas: tuple[int, ...] = ()
    #: Pool of Radiance: the view byte, its 3D value and its grid values.
    view: int | None = None
    world_view: int = 1
    grid_mode: int = 3
    grid_views: tuple[int, ...] = ()
    #: Pool of Radiance: the `u32` game window, whose `UserPort` takes the key.
    window_pointer: int | None = None
    #: Pool of Radiance: the travel grid's menu text, laid out like the world
    #: menu's `menu_text` (words split on spaces).
    grid_menu_text: bytes | None = None
    #: The player's disk: the script file's path, compared without case
    #: because three titles name theirs `ECL.GLB`, and the bytes before the
    #: script in each of its blocks.
    script_file: str = ""
    script_header: int = 0
    confirmed: bool = False
    direct_confirmed: bool = False
    #: True where a door was stood on and its key sent live (Pool of Radiance).
    door_confirmed: bool = False
    #: Destinations whose script plays an opening unless the area byte already
    #: names them. The trip writes the area byte first, so `fired` judges by
    #: the step entry instead.
    came_from_areas: tuple[int, ...] = ()
    differences: tuple[Difference, ...] = ()


def _return_landing() -> Difference:
    return Difference(
        "return_landing",
        "decision 1: Return lands where the arriving script puts the party",
        lambda here, to, back: back)


#: The one-sided entry-1 routes' stand facings: the side of the route square
#: the step cannot cross, so the party stands there without stepping (a step
#: into the square would pass a minute and roll for a wandering monster).
ENTRY1_FACING: Mapping[tuple[int, int], int] = MappingProxyType({
    (0, 21): 0,
    (0, 26): 0,
    (0, 27): 0,
    (9, 6): 3,
    (13, 27): 2,
    (22, 23): 0,
    (22, 26): 0,
    (23, 22): 0,
})

#: Doors whose route square has no side the step cannot cross: the party
#: stands on this square and facing instead, which has the same square id.
ENTRY1_STAND: Mapping[tuple[int, int], tuple[int, int, int]] = MappingProxyType({
    (0, 11): (6, 2, 2),
})


#: The doors a live Pool of Radiance run walked out of with these writes, as
#: `(area, destination)`; every other door stays held.
DOORS_PROVEN = frozenset({(7, 5), (13, 27), (14, 26), (16, 27)})


#: The words after a block's header of five `GOTO`s, which the interpreter
#: writes when a script block loads; the first is the step entry.
ENTRY_WORDS = 5


@dataclass(frozen=True)
class InitRoom:
    """An area's init span: the buffer offsets `start` to `end`, of which the
    first `size` bytes are the script's on the disk (SHA-1 `sha1`) and the
    rest are zero in the buffer."""

    start: int
    end: int
    size: int
    sha1: str


#: The init spans `tools/amiga/tripspace.py refs pool-of-radiance` derives:
#: nothing reachable from entries 0-3 covers or names a byte of them, and no
#: `RANDOM` statement lies in them. Keyed by `(title key, area)`.
INIT_ROOM: Mapping[tuple[str, int], InitRoom] = MappingProxyType({
    ("pool-of-radiance", 1): InitRoom(
        0x1DA0, BUFFER_SIZE, 87, "fdc435c680775b7416869785d01877ce796e6b98"),
    ("pool-of-radiance", 28): InitRoom(
        0x1D93, BUFFER_SIZE, 96, "68732fae8431cdd654fb89b9ec56e6f4b60e1379"),
})


def entry_words(target, row: TripRow) -> bytes:
    """The step entry and, on Pool of Radiance, the four words after it. A new
    area can share the first (areas 14 and 27 do) but not all five. The
    other titles' words after the entry are not measured, so they read the
    entry alone."""
    words = ENTRY_WORDS if row.key == "pool-of-radiance" else 1
    return target.read(target.data_base + row.step_entry, 2 * words)


def stand_for(here: int, to: int, route) -> tuple[int, int, int] | None:
    """`(x, y, facing)` to stand the party on for the door `route` of the trip
    `here` to `to`, or None where the stand is not known.

    Entry 0 stands on its own square and facing; an entry 0 row without a
    facing is held, because the facing decides the outcome. Entry 1 stands on
    the route square facing `ENTRY1_FACING`'s side, or on `ENTRY1_STAND`'s.
    """
    if route.entry == 0:
        return tuple(route.square) if len(route.square) == 3 else None
    if route.entry == 1:
        if (here, to) in ENTRY1_STAND:
            return ENTRY1_STAND[(here, to)]
        facing = ENTRY1_FACING.get((here, to))
        if facing is None:
            return None
        return (route.square[0], route.square[1], facing)
    return None


def departure_for(key: str, here: int | None, to: int,
                  to_overland: bool | None = None):
    """The `departures` row an Amiga trip from `here` to `to` reproduces, or
    None."""
    if here is None:
        return None
    return departures.find(key, departures.AMIGA, here, to, to_overland)


class GuardUnreadable(ValueError):
    """A departure guard's variable could not be read, so whether the
    departure applies is unknown."""


def departure_prologue(key: str, here: int | None, to: int,
                       to_overland: bool | None = None, read=None) -> bytes:
    """The `SAVE` statements of the departure's `writes`, run ahead of the
    trip. A route row writes nothing: its door runs the script.

    Without `read`, the row's `SAVE`s whatever its guards say, which is the
    most room the trip can need. With `read` (a function from a script
    variable to its word, or None when it cannot be read), the guards are
    tested here and the `SAVE`s are made only when they hold; no script runs
    between arming and the trip's first statement, so the values cannot
    change. A guard that cannot be read raises `GuardUnreadable`.
    """
    row = departure_for(key, here, to, to_overland)
    if row is None or not row.writes:
        return b""
    if read is not None:
        held = departures.applies(row, read, None)
        if held is None:
            raise GuardUnreadable(f"a guard of the departure from area {here} "
                                  "could not be read")
        if not held:
            return b""
    out = b"".join(save(value, address) for address, value in row.writes)
    return out + clear_box() if row.clear_box else out


def leg_held(row: TripRow, here: int | None, to: int, back: bool,
             lengths: Mapping[int, int], to_overland: bool | None = None,
             init_areas: frozenset[int] = frozenset()) -> bool:
    """Whether the trip `here` to `to` is held, by a difference, by the
    disks or by the room past the departing script. `init_areas` are the
    areas whose init span the player's disks match (`init_rooms`)."""
    if any(d.covers(here, to, back) and not d.offered
           for d in row.differences):
        return True
    if lengths and to not in lengths:
        # The title's disks have no script for that area (Silver Blades has
        # no area 4), and its loader retries a missing one for ever.
        return True
    # Sized with the prologue the trip will put ahead of itself, so the check
    # made up front and the one made on arming agree.
    try:
        prologue = (leave_grid_prologue(row, here, to)
                    + departure_prologue(row.key, here, to, to_overland))
    except ValueError:
        return True
    smallest = plan(to, (0, 0, 0), prologue=prologue)
    return free_tail(row, here, lengths, smallest, init_areas) not in (1, 2)


def _square(machine: amiga.AmigaMachine) -> tuple[Spot, Spot, Spot]:
    return (Spot(machine.party_x, machine.width),
            Spot(machine.party_y, machine.width),
            Spot(machine.party_facing, 1, FACING_SCALE))


_POOL = amiga.MACHINES["pool-of-radiance"]
_GRID = _POOL.travel_grid
_GRID_AREAS = tuple(_GRID.areas)
#: Curse's Tilverton streets.
_TILVERTON = 1


#: One row per `amiga.MACHINES` key, from the table and the live trips in
#: `docs/96-live-memory-automapper.md`.
ROWS: dict[str, TripRow] = {
    # CONFIRMED: code and 4 trips (one boot, `fs-uae-gdb`), 3 of them fired
    # by the synthetic message.
    "pool-of-radiance": TripRow(
        key="pool-of-radiance", title=_POOL.title,
        step_entry=0xAA, buffer_pointer=0xA4, buffer_bias=0,
        ecl_origin=0x9900, area=0x2F73, mode=0xBA, clears_buffer=True,
        square_targets=(0xC04B, 0xC04C, 0xC04D), square_spots=_square(_POOL),
        grid_targets=(0x49C3, 0x49C4),
        grid_spots=(Spot(_GRID.x, 2, pointer=_GRID.block_pointer),
                    Spot(_GRID.y, 2, pointer=_GRID.block_pointer)),
        indoors_spot=Spot(_GRID.indoors, 2, pointer=_GRID.block_pointer),
        grid_areas=_GRID_AREAS,
        view=_GRID.view, grid_views=tuple(_GRID.views),
        window_pointer=0x28,
        menu_text=b"Area Cast View Encamp Search Look",
        grid_menu_text=b"Cast View Encamp Search Look",
        script_file="/ecl.dax", script_header=2,
        confirmed=True, door_confirmed=True),
    # CONFIRMED: code and 2 trips.
    "curse-of-the-azure-bonds": TripRow(
        key="curse-of-the-azure-bonds", title="Curse of the Azure Bonds",
        step_entry=0x584C, buffer_pointer=0x5006, buffer_bias=0x8000,
        ecl_origin=0x8000, area=0x5CE1, mode=0x3D56, clears_buffer=True,
        square_targets=(0xC04B, 0xC04C, 0xC04D),
        square_spots=_square(amiga.MACHINES["curse-of-the-azure-bonds"]),
        menu_kind=0x1C24, menu_at=0x3342,
        menu_text=b"Area\0Cast\0View\0Encamp\0Search\0Look",
        key_buffer=0x3804, area_file=0x7F12,
        script_file="/DISKB/ECL.GLB",
        confirmed=True,
        came_from_areas=(_TILVERTON,)),
    # PROBABLE: code only, plus the menu text read live.
    "secret-of-the-silver-blades": TripRow(
        key="secret-of-the-silver-blades",
        title="Secret of the Silver Blades",
        step_entry=0x732E, buffer_pointer=0x6956, buffer_bias=0x8000,
        ecl_origin=0x8000, area=0x79C9, mode=0x525C, clears_buffer=False,
        square_targets=(0xC04B, 0xC04C, 0xC04D),
        square_spots=_square(amiga.MACHINES["secret-of-the-silver-blades"]),
        menu_kind=0x2384, menu_at=0x4A5E,
        menu_text=b"Area Cast View Encamp Search Look",
        key_buffer=0x4F6C, area_file=0x7F12,
        script_file="/DISK2/ECL.GLB",
        confirmed=False,
        differences=(_return_landing(),)),
    # CONFIRMED: code and 3 trips.
    "pools-of-darkness": TripRow(
        key="pools-of-darkness", title="Pools of Darkness",
        step_entry=0x72C6, buffer_pointer=0x6EA6, buffer_bias=0x8000,
        ecl_origin=0x8000, area=0x7A0A, mode=0x5B12, clears_buffer=False,
        square_targets=(0x34, 0x35, 0x11), grid_targets=(0x25, 0x26),
        square_spots=_square(amiga.MACHINES["pools-of-darkness"]),
        menu_kind=0x235E, menu_at=0x4F34,
        menu_text=b"Area Cast View Encamp Search Look",
        key_buffer=0x5742,
        overland_mode=3, overland_menu_kind=4, overland_menu_text=b"Encamp",
        script_file="/Disk3/ECL.GLB",
        confirmed=True,
        differences=(_return_landing(),)),
}


def row_for(key_or_row) -> TripRow:
    """A row, from itself or from its `amiga.MACHINES` key."""
    if isinstance(key_or_row, TripRow):
        return key_or_row
    return ROWS[key_or_row]


# -- the statements ----------------------------------------------------------


def _byte(value: int, what: str) -> int:
    if not 0 <= value <= 0xFF:
        raise ValueError(f"{what} {value} does not fit a one-byte operand")
    return value


def save(value: int, address: int) -> bytes:
    """`SAVE value, [address]`: six bytes."""
    if not 0 <= address <= 0xFFFF:
        raise ValueError(f"address {address:#x} does not fit an operand")
    return bytes((SAVE, IMMEDIATE, _byte(value, "value"),
                  ADDRESS, address & 0xFF, address >> 8))


def newecl(area: int) -> bytes:
    """`NEWECL area`: three bytes."""
    return bytes((NEWECL, IMMEDIATE, _byte(area, "area")))


def picture(value: int) -> bytes:
    """`PICTURE value`: three bytes."""
    return bytes((PICTURE, IMMEDIATE, _byte(value, "value")))


def clear_box() -> bytes:
    """`CLEAR BOX`: one byte, no operands."""
    return bytes((CLEAR_BOX,))


def loadfiles(first: int, second: int, third: int) -> bytes:
    """`LOADFILES first, second, third`: seven bytes."""
    out = bytes((LOADFILES,))
    for value, what in ((first, "first"), (second, "second"), (third, "third")):
        out += bytes((IMMEDIATE, _byte(value, what)))
    return out


def boat_exit_groups() -> tuple[bytes, ...]:
    """The five statement groups Pool of Radiance's grid scripts run before a
    boat's `NEWECL`, in order: `PICTURE #255`, `CLEAR BOX`, `SAVE 1,[$49E6]`,
    `SAVE 127` into `$6E22`-`$6E27`, and `LOADFILES 127,127,127`.
    """
    return (picture(255), clear_box(), save(1, 0x49E6),
            b"".join(save(127, a) for a in range(0x6E22, 0x6E28)),
            loadfiles(127, 127, 127))


def encode(row, square, area: int, area_file: int | None = None,
           grid=None) -> bytes:
    """The tier-1 statements: the square, the grid square, the area file,
    then `NEWECL`.

    `square` is `(x, y)` or `(x, y, facing)` with facing 0-3, or None; `grid`
    is `(x, y)` or None. A field the row has no target for raises.
    """
    row = row_for(row)
    out = b""
    if square is not None:
        for value, target in zip(square, row.square_targets):
            out += save(value, target)
    if grid is not None:
        if row.grid_targets is None:
            raise ValueError(f"{row.title} has no travel grid")
        for value, target in zip(grid, row.grid_targets):
            out += save(value, target)
    if area_file is not None:
        if row.area_file is None:
            raise ValueError(f"{row.title} has no area-file byte")
        out += save(area_file, row.area_file)
    return out + newecl(area)


def rawkey_message(port: int, window: int) -> bytes:
    """A 52-byte RAWKEY `IntuiMessage` for raw key 8, already linked as the
    only node of `port`'s message list: `ln_Succ` the list's tail, `ln_Pred`
    its head. No reply port, so Kickstart's `ReplyMsg` only marks it free."""
    return struct.pack(
        ">IIBBIIHIHHIhhIIII",
        port + PORT_LIST + 4, port + PORT_LIST, NT_MESSAGE, 0, 0, 0,
        MESSAGE_SIZE, RAWKEY, RAW_KEY_8, 0, 0, 0, 0, 0, 0, window, 0)


def link(message: int) -> bytes:
    """The 12 bytes at `port + PORT_LIST` that make `message` its one node:
    head, tail and tail-pred."""
    return struct.pack(">III", message, 0, message)


def empty_list(port: int) -> bytes:
    """What an empty `mp_MsgList` holds: head at the tail node, tail 0,
    tail-pred at the head node."""
    return struct.pack(">III", port + PORT_LIST + 4, 0, port + PORT_LIST)


# -- the tiers ---------------------------------------------------------------


@dataclass(frozen=True)
class Placement:
    """Buffer offsets of a trip's statements and of its message, which is None
    on a title that takes its key from the one-key buffer."""

    statements_at: int
    message_at: int | None
    #: The init span the trip is written into, or None past the script.
    room: InitRoom | None = None


@dataclass(frozen=True)
class Plan:
    """What one trip writes: the destination, the square (`(x, y)` or
    `(x, y, facing)`), the grid square, the tier and the area-file byte."""

    area: int
    square: tuple[int, ...] | None
    overland: tuple[int, int] | None
    tier: int = 1
    area_file: int | None = None
    prologue: bytes = b""
    #: Where `place` put the statements and message; None writes them at
    #: `layout`'s offsets.
    placement: Placement | None = None


def plan(area: int, square=None, overland=None, tier: int = 1,
         area_file: int | None = None, prologue: bytes = b"",
         placement: Placement | None = None) -> Plan:
    return Plan(area, None if square is None else tuple(square),
                None if overland is None else tuple(overland), tier,
                area_file, prologue, placement)


def leave_grid_prologue(row, here: int | None, to: int) -> bytes:
    """The boat exit's five statement groups, run ahead of a trip that leaves
    a wilderness grid window for a place off the grid.

    Without them the frame keeps the wilderness picture around it. The
    addresses are Pool of Radiance's, the only title with grid areas.
    """
    row = row_for(row)
    if here in row.grid_areas and to not in row.grid_areas:
        return b"".join(boat_exit_groups())
    return b""


#: The trip `free_tail` sizes when it is given no plan: x, y and facing.
_SMALLEST = Plan(0, (0, 0, 0), None)


def _statements(row: TripRow, p: Plan) -> bytes:
    if p.tier == 1:
        return p.prologue + encode(row, p.square, p.area, p.area_file,
                                   p.overland)
    return p.prologue + newecl(p.area)


def layout(row, size: int) -> tuple[int, int | None]:
    """Buffer offsets of `size` bytes of statements and of the message, which
    is None on a title that takes its key from the one-key buffer."""
    row = row_for(row)
    at = BUFFER_SIZE - size
    if row.window_pointer is None:
        return at, None
    return at, (at - MESSAGE_SIZE) & ~3


def _lowest(row: TripRow, size: int) -> int:
    at, message = layout(row, size)
    return at if message is None else message


def _direct_spots(row: TripRow, p: Plan) -> list[tuple[Spot, int]] | None:
    """The tier-2 writes, as `(spot, value)`; None if one has no spot."""
    out = []
    if p.square is not None:
        out += list(zip(row.square_spots, p.square))
    if p.overland is not None:
        if row.grid_spots is None:
            return None
        out += list(zip(row.grid_spots, p.overland))
    if p.area_file is not None:
        if row.area_file_spot is None:
            return None
        out.append((row.area_file_spot, p.area_file))
    return out


def place(row, area: int | None, lengths: Mapping[int, int],
          trip: Plan, init_areas: frozenset[int] = frozenset()
          ) -> Placement | None:
    """Where a tier-1 `trip` from `area` goes, or None when it does not fit.

    The default layout (statements at the buffer's end, the message below
    them) is tried first. On a title with a message, the packed layout then
    puts the statements at the script's end and the message after them, which
    saves the message's alignment and the gap before the statements. Last, for
    an area in `init_areas`, the statements go at its init entry and the
    message after them, inside the span.
    """
    row = row_for(row)
    length = None if area is None else lengths.get(area)
    if length is None:
        return None
    size = len(_statements(row, dataclasses.replace(trip, tier=1)))
    at, message_at = layout(row, size)
    if (at if message_at is None else message_at) >= length:
        return Placement(at, message_at)
    if row.window_pointer is None:
        return None
    message_at = (length + size + 3) & ~3
    if message_at + MESSAGE_SIZE <= BUFFER_SIZE:
        return Placement(length, message_at)
    room = INIT_ROOM.get((row.key, area)) if area in init_areas else None
    if room is not None:
        message_at = (room.start + size + 3) & ~3
        if message_at + MESSAGE_SIZE <= room.end:
            return Placement(room.start, message_at, room)
    return None


def free_tail(row, area: int | None, lengths: Mapping[int, int],
              trip: Plan | None = None,
              init_areas: frozenset[int] = frozenset()) -> int:
    """The tier a trip from `area` gets: 1, 2 or 3 (none).

    `lengths` is `script_lengths`' table for the player's disks. Without
    `trip`, the 21-byte trip (x, y, facing and `NEWECL`) is sized, which is
    the largest unless a grid square or an area-file byte is added.
    """
    row = row_for(row)
    length = None if area is None else lengths.get(area)
    if length is None:
        return 3
    trip = trip or _SMALLEST
    if place(row, area, lengths, trip, init_areas) is not None:
        return 1
    if (row.direct_confirmed and _direct_spots(row, trip) is not None
            and _lowest(row, len(trip.prologue + newecl(trip.area))) >= length):
        return 2
    return 3


def _script_bodies(row: TripRow, data: bytes) -> dict[int, bytes]:
    """`{area: the script's bytes in the buffer}` of one copy of the script
    file: each block less the bytes the loader skips."""
    if row.script_file.lower().endswith(".dax"):
        from goldbox import amiga_dax
        return {area: block[row.script_header:]
                for area, block in amiga_dax.blocks(data, row.script_file)}
    blocks = amiga.glib_blocks(data)
    if not blocks:
        return {}
    table = blocks[0]
    count = int.from_bytes(table[:2], "big")
    if len(table) < 2 + 4 * count:
        raise ValueError(f"{row.script_file} block 0 counts {count} areas "
                         f"in {len(table)} bytes")
    out: dict[int, bytes] = {}
    for area, block in struct.iter_unpack(">HH", table[2:2 + 4 * count]):
        if 1 <= block < len(blocks):
            body = blocks[block][row.script_header:]
            if len(body) >= len(out.get(area, b"")):
                out[area] = body
    return out


def _script_copies(row: TripRow, disks):
    """The `{area: script}` table of every copy of the script file on
    `disks`, which is a folder of ADFs or an iterable of image paths or
    image bytes."""
    from goldbox.amiga_adf import AmigaDisk
    if isinstance(disks, (str, pathlib.Path)):
        folder = pathlib.Path(disks)
        images = sorted(folder.glob("*.adf")) + sorted(folder.glob("*.ADF"))
    else:
        images = list(disks)
    want = row.script_file.upper()
    for n, image in enumerate(images):
        try:
            disk = (AmigaDisk(image) if isinstance(image, (bytes, bytearray))
                    else AmigaDisk.open(str(image)))
            paths = [p for p, _e in disk.walk() if p.upper() == want]
            for path in paths:
                yield _script_bodies(row, disk.read_file(path))
        except Exception as exc:              # not a disk, or not this title's
            _log.debug("disk %d gave no %s: %s", n, row.script_file, exc)


def script_lengths(row, disks) -> dict[int, int]:
    """`{area: script length}` off the player's own disks, read now.

    `disks` is a folder of ADFs, or an iterable of image paths or image
    bytes. Every copy of the script file found is read, and an area two files
    disagree on takes the longer length, which leaves the smaller tail.
    """
    row = row_for(row)
    out: dict[int, int] = {}
    for bodies in _script_copies(row, disks):
        for area, body in bodies.items():
            out[area] = max(out.get(area, 0), len(body))
    return out


def init_rooms(row, disks) -> frozenset[int]:
    """The areas whose init span `INIT_ROOM` records and whose bytes on the
    player's disks hash to the record, in every copy of the script file that
    has the area."""
    row = row_for(row)
    wanted = {area: room for (key, area), room in INIT_ROOM.items()
              if key == row.key}
    if not wanted:
        return frozenset()
    good: set[int] = set()
    bad: set[int] = set()
    for bodies in _script_copies(row, disks):
        for area, room in wanted.items():
            body = bodies.get(area)
            if body is None:
                continue
            same = (len(body) - room.start == room.size
                    and hashlib.sha1(body[room.start:]).hexdigest() == room.sha1)
            (good if same else bad).add(area)
    return frozenset(good - bad)


# -- reading the game --------------------------------------------------------


def _base(target) -> int | None:
    return getattr(target, "data_base", None)


def _long(target, addr: int) -> int:
    return int.from_bytes(target.read(addr, 4), "big")


def _address(target, spot: Spot) -> int:
    base = _base(target)
    if spot.pointer is None:
        return base + spot.offset
    return _long(target, base + spot.pointer) + spot.offset


def _encode_spot(spot: Spot, value: int) -> bytes:
    return (value * spot.scale).to_bytes(spot.width, "big")


def _decode_spot(spot: Spot, blob: bytes) -> int | None:
    value = int.from_bytes(blob, "big")
    if value % spot.scale:
        return None
    return value // spot.scale


def area_id(target, row) -> int | None:
    """The area the game has loaded, or None before the target is located."""
    row = row_for(row)
    base = _base(target)
    if base is None:
        return None
    return target.read(base + row.area, 1)[0]


def square(target, row) -> tuple[int, int, int] | None:
    """The party's `(x, y, facing)`, facing 0-3, as the engine holds it."""
    row = row_for(row)
    if _base(target) is None:
        return None
    blobs = target.read_blocks([(_address(target, s), s.width)
                                for s in row.square_spots])
    got = [_decode_spot(s, b) for s, b in zip(row.square_spots, blobs)]
    if None in got or got[2] > 3:
        return None
    return tuple(got)


def overland(target, row) -> tuple[int, int] | None:
    """Pool of Radiance's travel-grid square while the party is outdoors
    (`$49E6` reads 0); None indoors and on every other title."""
    row = row_for(row)
    if row.grid_spots is None or _base(target) is None:
        return None
    spots = (row.indoors_spot, *row.grid_spots)
    indoors, x, y = target.read_blocks([(_address(target, s), s.width)
                                        for s in spots])
    if int.from_bytes(indoors, "big"):
        return None
    return int.from_bytes(x, "big"), int.from_bytes(y, "big")


def _port(target, row: TripRow) -> int:
    window = _long(target, _base(target) + row.window_pointer)
    return _long(target, window + WINDOW_USERPORT)


def gadget_layout(text: bytes, prefix: int = 0) -> tuple[tuple[int, int, int], ...]:
    """`(id, LeftEdge, Width)` of each gadget the engine's menu routine puts on
    the window for `text`, newest (the window's head) first. It splits on
    space and `_`, sets LeftEdge to 8 x (`prefix` characters + the word's
    column) and Width to 8 x the word's length + 2."""
    words = []
    column = 0
    for word in text.replace(b"_", b" ").split(b" "):
        if word:
            words.append((column, len(word)))
        column += len(word) + 1
    return tuple((FIRST_GADGET_ID + i,
                  CHARACTER_WIDTH * (prefix + col),
                  CHARACTER_WIDTH * length + 2)
                 for i, (col, length) in reversed(list(enumerate(words))))


def menu_gadgets(target, row, limit: int = 8) -> tuple[tuple[int, int, int], ...]:
    """`(id, LeftEdge, Width)` of the gadgets on the game window, head first,
    until a NextGadget of 0 or `limit` gadgets."""
    row = row_for(row)
    gadget = _long(target, _long(target, _base(target) + row.window_pointer)
                   + WINDOW_FIRST_GADGET)
    found = []
    while gadget and len(found) < limit:
        record = target.read(gadget, GADGET_ID + 2)
        found.append((
            int.from_bytes(record[GADGET_ID:GADGET_ID + 2], "big"),
            int.from_bytes(record[GADGET_LEFT_EDGE:GADGET_LEFT_EDGE + 2], "big",
                           signed=True),
            int.from_bytes(record[GADGET_WIDTH:GADGET_WIDTH + 2], "big")))
        gadget = int.from_bytes(record[GADGET_NEXT:GADGET_NEXT + 4], "big")
    return tuple(found)


def gate(target, row) -> bool:
    """Whether the game sits at its world menu with no key pending.

    Curse, Silver Blades, Pools of Darkness: menu kind 1, the world menu's
    text, the walking mode and an empty key buffer. Pools of Darkness also
    opens on an overland: its mode, its menu kind and its menu text. Pool of Radiance has no
    menu global: the walking mode and the 3D view with the world menu's
    gadgets, or the grid's mode and a grid view with the grid menu's, and an
    empty message list on the window's port. Camp and the world menu share
    gadget ids, so the gadgets' positions and widths tell them apart.
    """
    row = row_for(row)
    base = _base(target)
    if base is None:
        return False
    if row.window_pointer is not None:
        mode, view = target.read_blocks([(base + row.mode, 1),
                                         (base + row.view, 1)])
        here = (mode[0], view[0])
        if here == (row.world_mode, row.world_view):
            text = row.menu_text
        elif here[0] == row.grid_mode and here[1] in row.grid_views:
            text = row.grid_menu_text
        else:
            return False
        if text is None or menu_gadgets(target, row) != gadget_layout(text):
            return False
        port = _port(target, row)
        return target.read(port + PORT_LIST, 12) == empty_list(port)
    if row.menu_text is None or row.menu_kind is None or row.menu_at is None:
        return False
    kind, text, mode, key = target.read_blocks([
        (base + row.menu_kind, 2),
        (base + row.menu_at, len(row.menu_text) + 1),
        (base + row.mode, 1), (base + row.key_buffer, 1)])
    if key[0] != 0:
        return False
    if (int.from_bytes(kind, "big") == 1 and text == row.menu_text + b"\0"
            and mode[0] == row.world_mode):
        return True
    if row.overland_mode is None or row.overland_menu_kind is None \
            or row.overland_menu_text is None:
        return False
    if mode[0] != row.overland_mode \
            or int.from_bytes(kind, "big") != row.overland_menu_kind:
        return False
    return target.read(base + row.menu_at,
                       len(row.overland_menu_text) + 1) \
        == row.overland_menu_text + b"\0"


# -- arming, and putting back -------------------------------------------------


#: The kinds of write `arm` and `arm_door` make, in their order. The buffer kinds are put back
#: and zeroed byte by byte; the rest while they read as ours, whole or as the
#: prefix a write that failed part way left over the original.
KINDS = ("square", "wall", "attribute", "statements", "message", "init",
         "entry", "came_from", "trigger")
#: `init` is a statements or message write into an init span, whose original
#: bytes are the script's own and are put back, not zeroed.
_BYTEWISE = ("statements", "message", "init")


@dataclass(frozen=True)
class Written:
    """One write `arm` made: where, what was there, and what it wrote."""

    address: int
    original: bytes
    data: bytes
    kind: str


@dataclass(frozen=True)
class Armed:
    """A trip armed and waiting on the area byte."""

    row: TripRow
    plan: Plan
    from_area: int
    #: The address of the script buffer's byte 0 when the trip was armed.
    buffer: int
    records: tuple[Written, ...]

    @property
    def writes(self) -> tuple[tuple[int, bytes], ...]:
        """Every `(address, bytes)` written, in order, as `Outcome` wants."""
        return tuple((w.address, w.data) for w in self.records)


class ArmError(RuntimeError):
    """`arm` found the game not ready, before writing anything."""


class ArmIncomplete(RuntimeError):
    """A write failed and putting back what had been written failed too.
    `armed` holds every record made, for a later `disarm`."""

    def __init__(self, armed: "Armed", why: str):
        super().__init__(why)
        self.armed = armed


def _prepare(target, row: TripRow, p: Plan) -> tuple[int, list]:
    """The writes for `p`, in order, as `(address, data, kind)`."""
    base = _base(target)
    if p.tier == 2:
        spots = _direct_spots(row, p) if row.direct_confirmed else None
        if spots is None:
            raise ArmError("tier 2 is not confirmed for this title")
    elif p.tier != 1:
        raise ArmError(f"tier {p.tier} arms no trip")
    statements = _statements(row, p)
    room = None if p.placement is None else p.placement.room
    if p.placement is not None:
        at, message_at = p.placement.statements_at, p.placement.message_at
    else:
        at, message_at = layout(row, len(statements))
    buffer = _long(target, base + row.buffer_pointer) + row.buffer_bias
    writes = []
    if p.tier == 2:
        writes += [(_address(target, spot), _encode_spot(spot, value),
                    "square") for spot, value in spots]
    writes.append((buffer + at, statements,
                   "statements" if room is None else "init"))
    if message_at is not None:
        if (buffer + message_at) % 4:
            raise ArmError(f"the script buffer at {buffer:#x} is not "
                           "longword-aligned")
        port = _port(target, row)
        window = _long(target, base + row.window_pointer)
        writes.append((buffer + message_at, rawkey_message(port, window),
                       "message" if room is None else "init"))
        trigger = (port + PORT_LIST, link(buffer + message_at), "trigger")
    else:
        trigger = (base + row.key_buffer, FORWARD_KEY, "trigger")
    writes.append((base + row.step_entry,
                   (row.ecl_origin + at).to_bytes(2, "big"), "entry"))
    if p.area in row.came_from_areas:
        writes.append((base + row.area, bytes([p.area]), "came_from"))
    writes.append(trigger)
    return buffer, writes


def _check(row: TripRow, writes: list, originals: list[bytes]) -> None:
    for (address, data, kind), was in zip(writes, originals):
        if kind == "trigger":
            if row.window_pointer is not None:
                port = address - PORT_LIST
                if was != empty_list(port):
                    raise ArmError("the window's port has a message waiting")
            elif was[0] != 0:
                raise ArmError("a key is already waiting")
        elif (kind in _BYTEWISE and kind != "init" and row.clears_buffer
              and any(was)):
            raise ArmError(f"the script buffer is not free at {address:#x}")


def _check_init(target, row: TripRow, buffer: int, room: InitRoom) -> None:
    """Whether the live init span is the one `room` records: the script's
    bytes then zeros, and the init entry word pointing at its start."""
    base = _base(target)
    entry = row.step_entry + 2 * (ENTRY_WORDS - 1)
    live, word = target.read_blocks([(buffer + room.start,
                                      room.end - room.start),
                                     (base + entry, 2)])
    if (hashlib.sha1(live[:room.size]).hexdigest() != room.sha1
            or any(live[room.size:])):
        raise ArmError("the init span is not the script's on the disk")
    if int.from_bytes(word, "big") != row.ecl_origin + room.start:
        raise ArmError("the init entry does not point at the span")


def arm(target, row, p: Plan, token=None) -> Armed | None:
    """Write the trip: the tier-2 square, the statements (and Pool's message),
    the step entry, then the key, each checked before the next.

    None, with nothing left written, when the game is not at its world menu,
    the plan goes nowhere new, or a write fails and everything it and the
    earlier ones left could be put back. A failure that cannot be put back
    raises `ArmIncomplete`. If the area changed while putting back (a
    half-linked message the game took), the trip happened: the `Armed` is
    returned for `fired`.
    """
    row = row_for(row)
    if _base(target) is None or not gate(target, row):
        return None
    here = area_id(target, row)
    if here == p.area:
        return None
    journalled = False
    try:
        buffer, writes = _prepare(target, row, p)
        originals = target.read_blocks([(a, len(d)) for a, d, _k in writes])
        _check(row, writes, originals)
        if p.placement is not None and p.placement.room is not None:
            _check_init(target, row, buffer, p.placement.room)
        journal_write(target, row, here, buffer, writes, originals, token)
        journalled = True
    except ArmError as exc:
        _log.debug("amiga trip not armed: %s", exc)
        return None
    armed = _write_all(target, row, p, here, buffer, writes, originals)
    if armed is None and journalled:
        # Nothing is left in the game, so no journal may say otherwise.
        _unjournal(target)
    return armed


def _write_all(target, row: TripRow, p: Plan, here: int, buffer: int,
               writes: list, originals: list[bytes]) -> Armed | None:
    """Make `writes` in order, verified but for the key. None when one failed
    and everything written could be put back; the `Armed` otherwise."""
    done: list[Written] = []
    for (address, data, kind), was in zip(writes, originals):
        try:
            target.write(address, data, verify=kind != "trigger")
        except (NotConnected, ValueError) as exc:
            _log.warning("amiga trip: the %s write at %#x failed (%s); "
                         "putting it and %d earlier writes back", kind,
                         address, exc, len(done))
            # Part of it may have landed, so it is put back like the rest.
            done.append(Written(address, was, data, kind))
            armed = Armed(row, p, here, buffer, tuple(done))
            try:
                put_back = _put_back(target, armed)
            except (NotConnected, ValueError) as again:
                raise ArmIncomplete(armed, f"the {kind} write failed and "
                                    f"putting back failed too: {again}"
                                    ) from again
            return None if put_back else armed
        done.append(Written(address, was, data, kind))
    return Armed(row, p, here, buffer, tuple(done))


def stand_writes(target, row, stand, geo, attribute: bool = True
                 ) -> list[tuple[int, bytes, str]]:
    """The door's `(address, data, kind)` writes for the party standing at
    `stand`: the square, the wall nibble ahead and (unless `attribute` is
    False) the square's attribute byte, which the engine caches at the last
    redraw, then the key's message and its link.

    `geo` is a `goldbox.geo.Geo`. Only Pool of Radiance has the cached bytes'
    addresses (`amiga.MACHINES[...].notes`) and a message-list key.
    """
    row = row_for(row)
    x, y, facing = stand
    base = _base(target)
    notes = amiga.MACHINES[row.key].notes
    writes = [(_address(target, spot), _encode_spot(spot, value), "square")
              for spot, value in zip(row.square_spots, stand)]
    writes.append((base + notes["wall_ahead"], bytes([geo.wall(x, y, facing)]),
                   "wall"))
    if attribute:
        writes.append((base + notes["square_attribute"],
                       bytes([geo.attributes(x, y)]), "attribute"))
    at, message_at = layout(row, 0)
    buffer = _long(target, base + row.buffer_pointer) + row.buffer_bias
    if (buffer + message_at) % 4:
        raise ArmError(f"the script buffer at {buffer:#x} is not "
                       "longword-aligned")
    port = _port(target, row)
    window = _long(target, base + row.window_pointer)
    writes.append((buffer + message_at, rawkey_message(port, window),
                   "message"))
    writes.append((port + PORT_LIST, link(buffer + message_at), "trigger"))
    return writes


def arm_door(target, row, stand) -> Armed | None:
    """Stand the party at `stand` and send one forward key, so the game's own
    step runs the door's handler. No statements and no step entry are written.

    None, with nothing left written, when the game is not at its world menu,
    no map is resident, or a write fails and could be put back. The `Armed`
    has `plan.tier` 0.
    """
    from goldbox.geo import Geo
    row = row_for(row)
    if _base(target) is None or not gate(target, row):
        return None
    blob = target.geo()
    if blob is None:
        return None
    here = area_id(target, row)
    try:
        writes = stand_writes(target, row, stand, Geo(blob))
        originals = target.read_blocks([(a, len(d)) for a, d, _k in writes])
        _check(row, writes, originals)
    except ArmError as exc:
        _log.debug("amiga door not armed: %s", exc)
        return None
    buffer = _long(target, _base(target) + row.buffer_pointer) \
        + row.buffer_bias
    return _write_all(target, row, Plan(here, tuple(stand), None, 0), here,
                      buffer, writes, originals)


def port_empty(target, row) -> bool:
    """Whether the game has taken the key: its window's message list is empty
    again, or on a title with no window pointer its one-key buffer reads 0."""
    row = row_for(row)
    if row.window_pointer is None:
        return target.read(_base(target) + row.key_buffer, 1)[0] == 0
    port = _port(target, row)
    return target.read(port + PORT_LIST, 12) == empty_list(port)


def door_fired(target, armed: Armed) -> bool:
    """True once the game has taken a door's key. The area byte is no judge:
    a question answered NO takes the key and stays."""
    return port_empty(target, armed.row)


def trip_fired(target, armed: Armed) -> bool | None:
    """`door_fired` for a door, `fired` for a script trip."""
    if armed.plan.tier == 0:
        return True if door_fired(target, armed) else None
    return fired(target, armed)


def fired(target, armed: Armed) -> bool | None:
    """True once the area byte has left the departing area, else None.

    A trip that writes the area byte itself cannot be judged by it; the game
    has loaded the new script once the step entry no longer reads as written.
    A rewrite of the entry to the value already there would go unseen.
    """
    if any(w.kind == "came_from" for w in armed.records):
        w = next(w for w in armed.records if w.kind == "entry")
        (cur,) = target.read_blocks([(w.address, len(w.data))])
        return True if _ours(cur, w) == 0 and cur != w.original else None
    here = area_id(target, armed.row)
    if here is not None and here != armed.from_area:
        return True
    return None


def _runs(mask: list[bool]) -> list[tuple[int, int]]:
    """`(start, end)` of every run of True."""
    out, start = [], None
    for i, on in enumerate([*mask, False]):
        if on and start is None:
            start = i
        elif not on and start is not None:
            out.append((start, i))
            start = None
    return out


def _ours(cur: bytes, w: Written) -> int:
    """How many leading bytes of a word-kind record to put back: all of it
    while it reads as written, the landed prefix while the rest still reads
    as the original, and none once anything else has written there."""
    n = 0
    while n < len(cur) and cur[n] == w.data[n]:
        n += 1
    return n if cur[n:] == w.original[n:] else 0


def _restore(target, records) -> int:
    """Put back, newest first, every record still holding what was written:
    byte by byte for the buffer kinds, by `_ours` for the rest. Returns the
    writes made."""
    records = list(records)[::-1]
    if not records:
        return 0
    now = target.read_blocks([(w.address, len(w.data)) for w in records])
    made = 0
    for w, cur in zip(records, now):
        if w.kind in _BYTEWISE:
            same = [c == d for c, d in zip(cur, w.data)]
            for start, end in _runs(same):
                target.write(w.address + start, w.original[start:end])
                made += 1
        else:
            n = _ours(cur, w)
            if n and cur[:n] != w.original[:n]:
                target.write(w.address, w.original[:n])
                made += 1
    return made


def _put_back(target, armed: Armed) -> bool:
    """Take the key back first, then check the area again before the rest.

    The game runs the statements within a frame of taking the key, so a key
    taken between the caller's look at the area and this one shows here as a
    changed area. False then, with only the key's record touched.
    """
    keys = [w for w in armed.records if w.kind == "trigger"]
    if armed.plan.tier == 0:
        # A restored key reads as an empty list too, so a door is judged
        # before its key is taken back, and only once a key was written.
        if keys and door_fired(target, armed):
            return False
        _restore(target, keys)
        _restore(target, [w for w in armed.records if w.kind != "trigger"])
        return True
    if keys and any(w.kind == "came_from" for w in armed.records):
        # The game clears the key flag when it takes the key, and then holds
        # the area byte's 1 itself, so putting the departing area back would
        # undo its own write. A key flag changed on its own is not that trip.
        (cur,) = target.read_blocks([(keys[0].address, len(keys[0].data))])
        if cur != keys[0].data and fired(target, armed):
            return False
    _restore(target, keys)
    if fired(target, armed):
        return False
    _restore(target, [w for w in armed.records if w.kind != "trigger"])
    journal_clear(target, armed)
    return True


def disarm(target, armed: Armed) -> bool:
    """Put back a trip that did not fire. False if the area has changed after
    all, before or while putting back: the caller tidies instead."""
    if trip_fired(target, armed):
        return False
    return _put_back(target, armed)


def tidy(target, armed: Armed, new_area: int | None,
         lengths: Mapping[int, int]) -> int:
    """Zero the statements a trip left past the arriving area's script.

    Only on a title whose loader does not clear the buffer (or for a door's
    message, which no load may have cleared), only bytes that
    still read as written, and only past `lengths[new_area]`. An unknown
    area, or a buffer that moved, is left alone. Returns the bytes written.
    """
    row = armed.row
    journal_clear(target, armed)
    length = None if new_area is None else lengths.get(new_area)
    # A door that was answered NO leaves the area loaded, so its message
    # stays in a buffer the loader would otherwise have cleared.
    if ((row.clears_buffer and armed.plan.tier != 0) or length is None
            or _base(target) is None):
        return 0
    buffer = _long(target, _base(target) + row.buffer_pointer) \
        + row.buffer_bias
    if buffer != armed.buffer:
        return 0
    mine = [w for w in armed.records if w.kind in _BYTEWISE]
    if not mine:
        return 0
    now = target.read_blocks([(w.address, len(w.data)) for w in mine])
    zeroed = 0
    for w, cur in zip(mine, now):
        first = w.address - buffer
        same = [c == d and first + i >= length
                for i, (c, d) in enumerate(zip(cur, w.data))]
        for start, end in _runs(same):
            target.write(w.address + start, bytes(end - start))
            zeroed += end - start
    return zeroed


# -- the journal -------------------------------------------------------------


def journal_dir() -> pathlib.Path:
    """Where a trip written into an init span is recorded, beside the other
    tools' caches (`tools/registry/scratch.py`'s `cache_dir`, which `automap`
    does not import)."""
    return pathlib.Path.home() / ".cache" / "wish" / "amigatrip"


def connection_name(target) -> str:
    """A file-name-safe name for the machine `target` reads: its lane holder,
    its host and port, or `local`."""
    debugger = getattr(getattr(target, "target", target), "debugger", None)
    holder = getattr(debugger, "holder", None)
    host, port = getattr(debugger, "host", None), getattr(debugger, "port", None)
    name = holder or (f"{host}-{port}" if host else "local")
    return re.sub(r"[^A-Za-z0-9._-]", "-", str(name)).strip(".") or "local"


def journal_path(target) -> pathlib.Path:
    return journal_dir() / f"{connection_name(target)}.json"


def _started(pid: int) -> str | None:
    """When process `pid` began, as the kernel counts it, so a reused pid is
    told from the process that wrote a journal. None where `/proc` is absent."""
    try:
        stat = pathlib.Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    # The command name, in brackets, may hold spaces.
    return stat.rpartition(")")[2].split()[19]


def _owner(token=None) -> dict:
    """The process writing a journal: its pid, start time and the token of
    the instance that armed the trip."""
    return {"pid": os.getpid(), "started": _started(os.getpid()),
            "token": token}


def _windows_alive(pid: int) -> bool:
    import ctypes
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int,
                                     ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.CloseHandle.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.OpenProcess(0x100000, False, pid)
    if not handle:
        # Access denied means the process exists; only an invalid parameter
        # (no such pid) means it has gone.
        return ctypes.GetLastError() == 5
    try:
        # SYNCHRONIZE: a wait of zero times out only on a live process.
        return kernel32.WaitForSingleObject(handle, 0) == 0x102
    finally:
        kernel32.CloseHandle(handle)


def _owner_alive(owner, token=None, journal=None) -> bool:
    """Whether the process that wrote a journal is still running, or is this
    process under another instance's token. A journal with no readable owner
    counts as dead, as does one with a pid of 0 or below."""
    try:
        pid, started = int(owner["pid"]), owner.get("started")
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
    if pid <= 0:
        return False
    if pid == os.getpid():
        if started is not None and _started(pid) not in (None, started):
            return False
        return owner.get("token") != token
    if os.name == "nt":
        return _windows_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        _log.info("amiga trip: the journal %s is left unrepaired, since its "
                  "owner cannot be signalled", journal)
        return True
    except OSError:
        return True
    return started is None or _started(pid) in (None, started)


def journal_write(target, row: TripRow, here: int, buffer: int, writes: list,
                  originals: list[bytes], token=None) -> None:
    """Record `writes` and what they will overwrite, before the first is made.
    An unwritable journal is an `ArmError`: nothing is armed that a crash
    could leave in the game."""
    saved = {"title": row.key, "from_area": here, "data_base": _base(target),
             "buffer": buffer, "owner": _owner(token),
             "records": [{"address": a, "original": was.hex(),
                          "data": d.hex(), "kind": k}
                         for (a, d, k), was in zip(writes, originals)]}
    path = journal_path(target)
    temp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(json.dumps(saved), encoding="utf-8")
        os.replace(temp, path)
    except OSError as exc:
        raise ArmError(f"the journal {path} cannot be written: {exc}") from exc
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def journal_clear(target, armed: Armed) -> None:
    """Delete the journal once a trip `arm` journalled has fired or been put
    back. A door writes no statements, journals nothing, and so leaves a
    journal of another Wish alone."""
    if any(w.kind in ("statements", "init") for w in armed.records):
        _unjournal(target)


def _unjournal(target) -> None:
    try:
        journal_path(target).unlink(missing_ok=True)
    except OSError:
        _log.warning("amiga trip: the journal could not be deleted",
                     exc_info=True)


def repair(target, token=None) -> bool:
    """Put back a trip that an earlier run of Wish left armed, from its
    journal. True when a journal was found and dealt with.

    A journal for another boot of the game (the data hunk moved) or for an
    area the party has left holds nothing to undo and is deleted. Otherwise
    each recorded word that still reads as written is put back, newest
    first, as `disarm` does. A machine that cannot be read or written leaves
    the journal for the next attempt. A journal whose writing process is
    still running belongs to another Wish on the same machine, and one
    written under another `token` by this process to another trip of it; both
    are left alone.
    """
    path = journal_path(target)
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        row = ROWS[saved["title"]]
        records = tuple(Written(r["address"], bytes.fromhex(r["original"]),
                                bytes.fromhex(r["data"]), r["kind"])
                        for r in saved["records"])
        here, base, buffer = (saved["from_area"], saved["data_base"],
                              saved["buffer"])
        owner = saved.get("owner")
    except FileNotFoundError:
        return False
    except (OSError, ValueError, KeyError, TypeError):
        _log.warning("amiga trip: the journal %s cannot be read, so a trip "
                     "may still be in the game", path, exc_info=True)
        return False
    if _owner_alive(owner, token, path):
        return False
    if _base(target) is None:
        return False
    if base == _base(target) and records:
        armed = Armed(row, Plan(here, None, None), here, buffer, records)
        if not fired(target, armed):
            _log.info("amiga trip: putting back a trip left armed in area %s "
                      "at 0x%x (%d records)", here, buffer, len(records))
            _put_back(target, armed)
    path.unlink(missing_ok=True)
    return True
