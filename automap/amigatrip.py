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

**A trip that does not fire is put back.** `disarm` writes back every word that
still holds what `arm` wrote, newest first, and leaves alone any the game has
since changed. **Silver Blades and Pools of Darkness do not clear the buffer
before a load**, so after their trips `tidy` zeroes the statements that still
read as written and lie past the arriving area's script.
"""

from __future__ import annotations

import logging
import pathlib
import struct
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from . import amiga
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
    test: Callable[[int | None, int | None, bool], bool] = field(compare=False)
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
    #: Pool of Radiance: the travel-grid square `$49C3`/`$49C4` and `$49E6`.
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
    #: The player's disk: the script file's path, compared without case
    #: because three titles name theirs `ECL.GLB`, and the bytes before the
    #: script in each of its blocks.
    script_file: str = ""
    script_header: int = 0
    confirmed: bool = False
    direct_confirmed: bool = False
    differences: tuple[Difference, ...] = ()


def _return_landing() -> Difference:
    return Difference(
        "return_landing",
        "decision 1: Return lands where the arriving script puts the party",
        lambda here, to, back: back)


def _pool_doors(here, to, back) -> bool:
    from . import fasttravel
    return here is not None and fasttravel.choose_door(
        fasttravel.exits_from(here)) is not None


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
        script_file="/ecl.dax", script_header=2,
        confirmed=True,
        differences=(
            _return_landing(),
            Difference("leave_grid",
                       "decision 3: leaving the wilderness grid for a town",
                       lambda here, to, back: here in _GRID_AREAS
                       and to not in _GRID_AREAS),
            Difference("doors", "decision 4: Pool's doors", _pool_doors),
            Difference("weak_gate",
                       "decision 5: the gate reads only the mode and view",
                       lambda here, to, back: True),
            Difference("onto_grid",
                       "FT-L1: a leg onto the grid with $49C3/$49C4, not run",
                       lambda here, to, back: to in _GRID_AREAS),
        )),
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
        differences=(
            _return_landing(),
            Difference("tilverton",
                       "decision 2: arriving in Tilverton replayed the opening",
                       lambda here, to, back: to == _TILVERTON),
        )),
    # PROBABLE: code only. The menu text was never read, so the gate cannot
    # pass; FT-L1 measures it.
    "secret-of-the-silver-blades": TripRow(
        key="secret-of-the-silver-blades",
        title="Secret of the Silver Blades",
        step_entry=0x732E, buffer_pointer=0x6956, buffer_bias=0x8000,
        ecl_origin=0x8000, area=0x79C9, mode=0x525C, clears_buffer=False,
        square_targets=(0xC04B, 0xC04C, 0xC04D),
        square_spots=_square(amiga.MACHINES["secret-of-the-silver-blades"]),
        menu_kind=0x2384, menu_at=0x4A5E, menu_text=None,
        key_buffer=0x4F6C, area_file=0x7F12,
        script_file="/DISK2/ECL.GLB",
        confirmed=False,
        differences=(_return_landing(),)),
    # CONFIRMED: code and 3 trips.
    "pools-of-darkness": TripRow(
        key="pools-of-darkness", title="Pools of Darkness",
        step_entry=0x72C6, buffer_pointer=0x6EA6, buffer_bias=0x8000,
        ecl_origin=0x8000, area=0x7A0A, mode=0x5B12, clears_buffer=False,
        square_targets=(0x34, 0x35, 0x11),
        square_spots=_square(amiga.MACHINES["pools-of-darkness"]),
        menu_kind=0x235E, menu_at=0x4F34,
        menu_text=b"Area Cast View Encamp Search Look",
        key_buffer=0x5742,
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
class Plan:
    """What one trip writes: the destination, the square (`(x, y)` or
    `(x, y, facing)`), the grid square, the tier and the area-file byte."""

    area: int
    square: tuple[int, ...] | None
    overland: tuple[int, int] | None
    tier: int = 1
    area_file: int | None = None


def plan(area: int, square=None, overland=None, tier: int = 1,
         area_file: int | None = None) -> Plan:
    return Plan(area, None if square is None else tuple(square),
                None if overland is None else tuple(overland), tier,
                area_file)


#: The trip `free_tail` sizes when it is given no plan: x, y and facing.
_SMALLEST = Plan(0, (0, 0, 0), None)


def _statements(row: TripRow, p: Plan) -> bytes:
    if p.tier == 1:
        return encode(row, p.square, p.area, p.area_file, p.overland)
    return newecl(p.area)


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


def free_tail(row, area: int | None, lengths: Mapping[int, int],
              trip: Plan | None = None) -> int:
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
    full = Plan(trip.area, trip.square, trip.overland, 1, trip.area_file)
    if _lowest(row, len(_statements(row, full))) >= length:
        return 1
    if (row.direct_confirmed and _direct_spots(row, trip) is not None
            and _lowest(row, len(newecl(trip.area))) >= length):
        return 2
    return 3


def _script_blocks(row: TripRow, data: bytes) -> dict[int, int]:
    if row.script_file.lower().endswith(".dax"):
        from goldbox import amiga_dax
        return {area: len(block) - row.script_header
                for area, block in amiga_dax.blocks(data, row.script_file)}
    blocks = amiga.glib_blocks(data)
    if not blocks:
        return {}
    table = blocks[0]
    count = int.from_bytes(table[:2], "big")
    if len(table) < 2 + 4 * count:
        raise ValueError(f"{row.script_file} block 0 counts {count} areas "
                         f"in {len(table)} bytes")
    out = {}
    for area, block in struct.iter_unpack(">HH", table[2:2 + 4 * count]):
        if 1 <= block < len(blocks):
            out[area] = max(out.get(area, 0),
                            len(blocks[block]) - row.script_header)
    return out


def script_lengths(row, disks) -> dict[int, int]:
    """`{area: script length}` off the player's own disks, read now.

    `disks` is a folder of ADFs, or an iterable of image paths or image
    bytes. Every copy of the script file found is read, and an area two files
    disagree on takes the longer length, which leaves the smaller tail.
    """
    from goldbox.amiga_adf import AmigaDisk
    row = row_for(row)
    if isinstance(disks, (str, pathlib.Path)):
        folder = pathlib.Path(disks)
        images = sorted(folder.glob("*.adf")) + sorted(folder.glob("*.ADF"))
    else:
        images = list(disks)
    want = row.script_file.upper()
    out: dict[int, int] = {}
    for n, image in enumerate(images):
        try:
            disk = (AmigaDisk(image) if isinstance(image, (bytes, bytearray))
                    else AmigaDisk.open(str(image)))
            paths = [p for p, _e in disk.walk() if p.upper() == want]
            for path in paths:
                for area, length in _script_blocks(
                        row, disk.read_file(path)).items():
                    out[area] = max(out.get(area, 0), length)
        except Exception as exc:              # not a disk, or not this title's
            _log.debug("disk %d gave no %s: %s", n, row.script_file, exc)
    return out


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


def gate(target, row) -> bool:
    """Whether the game sits at its world menu with no key pending.

    Curse, Silver Blades, Pools of Darkness: menu kind 1, the world menu's
    text, the walking mode and an empty key buffer. Pool of Radiance has no
    menu global: the walking mode and the 3D view, or the grid's mode and a
    grid view, and an empty message list on the window's port.
    """
    row = row_for(row)
    base = _base(target)
    if base is None:
        return False
    if row.window_pointer is not None:
        mode, view = target.read_blocks([(base + row.mode, 1),
                                         (base + row.view, 1)])
        here = (mode[0], view[0])
        if here != (row.world_mode, row.world_view) and not (
                here[0] == row.grid_mode and here[1] in row.grid_views):
            return False
        port = _port(target, row)
        return target.read(port + PORT_LIST, 12) == empty_list(port)
    if row.menu_text is None or row.menu_kind is None or row.menu_at is None:
        return False
    kind, text, mode, key = target.read_blocks([
        (base + row.menu_kind, 2),
        (base + row.menu_at, len(row.menu_text) + 1),
        (base + row.mode, 1), (base + row.key_buffer, 1)])
    return (int.from_bytes(kind, "big") == 1
            and text == row.menu_text + b"\0"
            and mode[0] == row.world_mode and key[0] == 0)


# -- arming, and putting back -------------------------------------------------


#: The kinds of write `arm` makes, in its order. The buffer kinds are put back
#: and zeroed byte by byte; the rest only whole.
KINDS = ("square", "statements", "message", "entry", "trigger")
_BYTEWISE = ("statements", "message")


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
    at, message_at = layout(row, len(statements))
    buffer = _long(target, base + row.buffer_pointer) + row.buffer_bias
    writes = []
    if p.tier == 2:
        writes += [(_address(target, spot), _encode_spot(spot, value),
                    "square") for spot, value in spots]
    writes.append((buffer + at, statements, "statements"))
    if message_at is not None:
        if (buffer + message_at) % 4:
            raise ArmError(f"the script buffer at {buffer:#x} is not "
                           "longword-aligned")
        port = _port(target, row)
        window = _long(target, base + row.window_pointer)
        writes.append((buffer + message_at, rawkey_message(port, window),
                       "message"))
        trigger = (port + PORT_LIST, link(buffer + message_at), "trigger")
    else:
        trigger = (base + row.key_buffer, FORWARD_KEY, "trigger")
    writes.append((base + row.step_entry,
                   (row.ecl_origin + at).to_bytes(2, "big"), "entry"))
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
        elif kind in _BYTEWISE and row.clears_buffer and any(was):
            raise ArmError(f"the script buffer is not free at {address:#x}")


def arm(target, row, p: Plan) -> Armed | None:
    """Write the trip: the tier-2 square, the statements (and Pool's message),
    the step entry, then the key, each checked before the next.

    None, with nothing left written, when the game is not at its world menu,
    the plan goes nowhere new, or a write fails and every earlier one could be
    put back. A failure that cannot be put back raises.
    """
    row = row_for(row)
    if _base(target) is None or not gate(target, row):
        return None
    here = area_id(target, row)
    if here == p.area:
        return None
    try:
        buffer, writes = _prepare(target, row, p)
        originals = target.read_blocks([(a, len(d)) for a, d, _k in writes])
        _check(row, writes, originals)
    except ArmError as exc:
        _log.debug("amiga trip not armed: %s", exc)
        return None
    done: list[Written] = []
    for (address, data, kind), was in zip(writes, originals):
        try:
            target.write(address, data, verify=kind != "trigger")
        except (NotConnected, ValueError) as exc:
            _log.warning("amiga trip: the %s write at %#x failed (%s); "
                         "putting back %d earlier writes", kind, address, exc,
                         len(done))
            _restore(target, done)
            return None
        done.append(Written(address, was, data, kind))
    return Armed(row, p, here, buffer, tuple(done))


def fired(target, armed: Armed) -> bool | None:
    """True once the area byte has left the departing area, else None."""
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


def _restore(target, records) -> int:
    """Put back, newest first, every record still holding what was written:
    whole, or byte by byte for the buffer kinds. Returns the writes made."""
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
        elif cur == w.data and cur != w.original:
            target.write(w.address, w.original)
            made += 1
    return made


def disarm(target, armed: Armed) -> bool:
    """Put back a trip that did not fire. False, with nothing written, if the
    area has changed after all: the caller tidies instead."""
    if fired(target, armed):
        return False
    _restore(target, armed.records)
    return True


def tidy(target, armed: Armed, new_area: int | None,
         lengths: Mapping[int, int]) -> int:
    """Zero the statements a trip left past the arriving area's script.

    Only on a title whose loader does not clear the buffer, only bytes that
    still read as written, and only past `lengths[new_area]`. An unknown
    area, or a buffer that moved, is left alone. Returns the bytes written.
    """
    row = armed.row
    length = None if new_area is None else lengths.get(new_area)
    if row.clears_buffer or length is None or _base(target) is None:
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
