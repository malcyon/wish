#!/usr/bin/env python3
"""Free bytes past each Amiga area script, for a Fast Travel trip.

An Amiga trip writes a few of the game's own statements past the end of the
loaded area script and points the step entry at them (`docs/96-live-memory-
automapper.md`, "Fast Travel and Return without the program counter"). How
many bytes are free is the script buffer's `0x1E00` less the script's length
**as stored on the player's disk**: Silver Blades and Pools of Darkness do not
clear the buffer before a load, so a scan for zeros reads the last script's
leftovers as free space.

    tools/amiga/tripspace.py                           every title on the disks
    tools/amiga/tripspace.py --title pools-of-darkness
    tools/amiga/tripspace.py --disks DIR               loose .adf files in DIR
    tools/amiga/tripspace.py refs pools-of-darkness    the tail-reference walk
    tools/amiga/tripspace.py landings                  Pools of Darkness' overland cells

`refs` walks every statement reachable from a script's five entries with the
operand counts read from the title's own executable, and reports any operand
naming a byte past the script's end, and for each area with fewer than
`NEWECL_BYTES` free whether its init entry's first bytes are reached from any
other entry. Pool of Radiance's `/program` has no skip switch to read, so its
walk uses `POOL_SKIP_GROUPS` and `POOL_HANDLERS`, and `refs pool-of-radiance`
also prints each area's init span: the room from the init entry to the end of
the buffer, the statements of entries 0-3 that cover or name it, and the SHA-1
of the span's disk bytes that `automap/amigatrip.py`'s `INIT_ROOM` records.

`landings` prints, for each Pools of Darkness overland, the cell `$25`/`$26`
that the game's first exit into it writes (`overland_landings`); `Area.overland`
holds the same cells.

Everything is read from the disks at run time; nothing here holds a script
byte, a length or an operand table copied from the game.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import pathlib
import re
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from automap.amiga import glib_blocks  # noqa: E402
from goldbox import amiga_dax  # noqa: E402

#: The script buffer every Amiga title loads an area into.
BUFFER = 0x1E00

#: `SAVE value, target`: the opcode, a two-byte immediate, a three-byte target.
SAVE_BYTES = 6
#: `NEWECL area`: the opcode and a two-byte immediate.
NEWECL_BYTES = 3
#: The square's three `SAVE`s (x, y, facing) and the `NEWECL`.
FULL_BYTES = 3 * SAVE_BYTES + NEWECL_BYTES
#: Pool of Radiance's two extra `SAVE`s for the travel-grid square.
GRID_BYTES = 2 * SAVE_BYTES
#: Pool of Radiance's synthetic RAWKEY `IntuiMessage`, which sits in the tail
#: too, below the statements.
POOL_MESSAGE_BYTES = 52

POOL = "pool-of-radiance"
CURSE = "curse-of-the-azure-bonds"
SILVER_BLADES = "secret-of-the-silver-blades"
DARKNESS = "pools-of-darkness"
TITLES = (POOL, CURSE, SILVER_BLADES, DARKNESS)

#: Where each title keeps its scripts on disk, and its executable.
LIBRARY = {POOL: "ecl.dax", CURSE: "ECL.GLB", SILVER_BLADES: "ECL.GLB",
           DARKNESS: "ECL.GLB"}
EXECUTABLE = {POOL: "program", CURSE: "Curse", SILVER_BLADES: "Secret",
              DARKNESS: "Pools of Darkness"}

#: Pool of Radiance's loader (`/program` `0x9718`) copies an `ecl.dax` block
#: from its third byte on: the first two are a header the buffer never holds.
POOL_HEADER = 2

#: How each title's volume names begin, as `automap.maps._volume_title` reads them.
VOLUMES = {POOL: ("poolgame", "pooldata"), CURSE: ("curse",),
           SILVER_BLADES: ("secret",), DARKNESS: ("pod ", "pools of darkness")}


@dataclasses.dataclass(frozen=True)
class Space:
    """One area's script and the room after it."""

    title: str
    area: int
    block: int
    length: int

    @property
    def free(self) -> int:
        return BUFFER - self.length


def statements(*, square: bool = True, area_file: bool = False,
               grid: bool = False) -> int:
    """Bytes of script statements a trip writes.

    `square` is False for tier 2, where Wish writes the square straight into
    memory and the tail holds only the `NEWECL`. `area_file` adds the `SAVE`
    of the area-file byte, `grid` Pool of Radiance's grid square.
    """
    if not square:
        return NEWECL_BYTES
    return (FULL_BYTES + (SAVE_BYTES if area_file else 0)
            + (GRID_BYTES if grid else 0))


def lowest(title: str, size: int) -> int:
    """The lowest buffer offset a trip of `size` statement bytes writes.

    The statements end at the buffer's end. Pool of Radiance's message sits
    below them, on a longword boundary, as `automap.amigatrip.layout` puts it.
    """
    at = BUFFER - size
    return (at - POOL_MESSAGE_BYTES) & ~3 if title == POOL else at


def tier(title: str, length: int, *, area_file: bool = False,
         grid: bool = False) -> int:
    """1 when the whole trip fits after a script `length` bytes long, 2 when
    only `NEWECL` (and Pool of Radiance's message) does, 3 when neither."""
    if lowest(title, statements(area_file=area_file, grid=grid)) >= length:
        return 1
    if lowest(title, statements(square=False)) >= length:
        return 2
    return 3


def pool_spaces(ecl_dax: bytes) -> list[Space]:
    """Pool of Radiance: one `ecl.dax` block per area, numbered by area.

    The index's unpacked size is what the loader copies, less the header;
    `goldbox.amiga_dax` documents that every block unpacks to that size.
    """
    return [Space(POOL, bid, bid, raw - POOL_HEADER)
            for bid, _off, _comp, raw in amiga_dax.index(ecl_dax, "ecl.dax")]


def glib_spaces(title: str, ecl_glb: bytes) -> list[Space]:
    """Curse, Silver Blades, Pools of Darkness: block 0 of `ECL.GLB` is a
    `u16be` count and that many `(area, block)` pairs; the engine's lookup
    reads it the same way and loads the whole block."""
    blocks = glib_blocks(ecl_glb)
    if not blocks or len(blocks[0]) < 2:
        raise ValueError(f"{title}: ECL.GLB has no area table")
    count = struct.unpack_from(">H", blocks[0])[0]
    if len(blocks[0]) < 2 + 4 * count:
        raise ValueError(f"{title}: ECL.GLB's area table is cut short")
    out = []
    for area, block in struct.iter_unpack(">HH", blocks[0][2:2 + 4 * count]):
        if not 1 <= block < len(blocks):
            raise ValueError(f"{title}: area {area} names block {block}, "
                             f"past the {len(blocks)} the file holds")
        out.append(Space(title, area, block, len(blocks[block])))
    return out


def spaces(title: str, library: bytes) -> list[Space]:
    """Every area's script length and free bytes, from the title's script
    library as read off the player's disk, in area order."""
    got = pool_spaces(library) if title == POOL else glib_spaces(title, library)
    longer = [s.area for s in got if s.length > BUFFER]
    if longer:
        raise ValueError(f"{title}: areas {longer} are longer than the buffer")
    return sorted(got, key=lambda s: s.area)


# -- finding the files on the player's disks ---------------------------------

def title_of(volume: str) -> str | None:
    name = volume.lower()
    for title, prefixes in VOLUMES.items():
        if name.startswith(prefixes) or name in prefixes:
            return title
    return None


def disk_files(images, wanted: dict[str, str]):
    """`(title, label, file name, bytes)` for each file named in `wanted`
    (title -> base name) on each disk of that title, skipping duplicates."""
    from goldbox.amiga_adf import AmigaDisk, AmigaDiskError
    seen = set()
    for label, data in images:
        try:
            disk = AmigaDisk(data)
            title = title_of(disk.volume_name)
            names = [p for p, _e in disk.walk()] if title else []
        except (AmigaDiskError, ValueError):
            continue
        for path in names:
            if title in wanted and \
                    path.rsplit("/", 1)[-1].lower() == wanted[title].lower():
                body = disk.read_file(path)
                key = (title, hashlib.sha256(body).hexdigest())
                if key not in seen:
                    seen.add(key)
                    yield title, label, path, body


def images(disks: str | None):
    """Loose `.adf` files in `disks`, or every Gold Box disk the registry's
    `amiga` entry reaches, zips included."""
    if disks:
        for path in sorted(pathlib.Path(disks).iterdir()):
            if path.suffix.lower() == ".adf":
                yield str(path), path.read_bytes()
        return
    from tools.amiga import amigasaves
    yield from amigasaves.images()


# -- the operand counts, read from the executable ---------------------------

#: `cmpi.w #n,d0; bcc; add.w d0,d0; lea table(pc),a0; move.w (a0,d0.w),d0;
#: jmp (pc,d0.w)`: a SAS/C switch on an opcode.
SWITCH = re.compile(rb"\x0c\x40(..)(?:\x64[^\x00]|\x64\x00..)\xd0\x40\x41\xfa(..)"
                    rb"\x30\x30\x00\x00\x4e\xfb\x00\x00", re.S)
#: `addq.w #1, d16(a4)`: step the script pointer past an opcode with no operands.
STEP = b"\x52\x6c"
PUSH = b"\x3f\x3c"
CALLS = (b"\x4e\xba", b"\x4e\xac")
POP2 = b"\x54\x4f"
#: `addi.w #-1, d16(a4)`: back over the end of the fixed operands, to read more.
BACK = b"\x06\x6c\xff\xff"


def _case(data: bytes, at: int):
    """One case of the skip switch: `(n, counted)` or None if unrecognised."""
    if data[at:at + 2] == STEP:
        return (0, False)
    if data[at:at + 2] == PUSH and data[at + 4:at + 6] in CALLS:
        n = struct.unpack_from(">H", data, at + 2)[0]
        if data[at + 8:at + 10] == POP2:
            return (n, False)
        if data[at + 8:at + 12] == BACK:
            return (n, True)
    return None


def skip_model(code: bytes) -> tuple[tuple[int, bool], ...] | None:
    """The per-opcode operand counts of the routine a false `IF` calls to step
    over the next statement, or None if there is not exactly one.

    Each case is either `addq.w #1` on the script pointer (no operands), or a
    call loading `n` operands, optionally followed by stepping back and loading
    as many more as the `n`th operand says (`counted`). Only a switch whose
    every case is one of those is that routine.
    """
    found = []
    for m in SWITCH.finditer(code):
        count = struct.unpack(">H", m[1])[0]
        lea = m.start(2) - 2
        table = lea + 2 + struct.unpack(">h", m[2])[0]
        base = m.end() - 2
        cases = []
        for op in range(count):
            at = base + struct.unpack_from(">h", code, table + 2 * op)[0]
            cases.append(_case(code, at) if 0 <= at < len(code) else None)
        if all(c is not None for c in cases):
            found.append(tuple(cases))
    return found[0] if len(found) == 1 else None


#: Where Curse's and Silver Blades' skip switch disagrees with the opcode's own
#: handler: the switch steps one byte over `$15`, `ONGOTO`, `ONGOSUB` and
#: `HORIZMENU`, and one operand over `$34` and `$36`, which load two. Pools of
#: Darkness' switch agrees with its handlers. A walk follows the handlers.
HANDLER_COUNTS = {
    CURSE: {0x15: (3, True), 0x25: (2, True), 0x26: (2, True),
            0x2B: (2, True), 0x34: (2, False), 0x36: (2, False)},
    SILVER_BLADES: {0x15: (3, True), 0x25: (2, True), 0x26: (2, True),
                    0x2B: (2, True), 0x34: (2, False), 0x36: (2, False)},
}

#: Pool of Radiance's operand counts, as its interpreter has them
#: (`/program`, disk 1). A false `IF` calls the if-chain at `0xB33E`, whose
#: groups are `count: opcodes` below; an opcode in none of them steps one byte.
#: Four opcodes are not in the chain because the skip steps one byte over them
#: while their handler loads a counted run. The counts are the engine's own
#: loader calls, not game data.
POOL_SKIP_GROUPS = {
    1: (0x01, 0x02, 0x0A, 0x0E, 0x11, 0x12, 0x1D, 0x20, 0x2D, 0x32, 0x34,
        0x36, 0x38, 0x39, 0x3C),
    2: (0x03, 0x08, 0x09, 0x0C, 0x0F, 0x10, 0x1F, 0x22),
    3: (0x04, 0x05, 0x06, 0x07, 0x0B, 0x21, 0x28, 0x2A, 0x2F, 0x30, 0x35,
        0x37, 0x3B),
    4: (0x14, 0x23),
    5: (0x2E,),
    6: (0x1E, 0x2C),
    8: (0x27,),
    14: (0x29,),
}
#: Where the dispatcher at `0x2ACE2`'s handlers load more than the chain
#: skips: `$0C` and `$36` one operand more, and `$15`, `ONGOTO`, `ONGOSUB` and
#: `HORIZMENU` a fixed count followed by as many more as the last gives. `$1F`
#: has no handler, and no script statement uses it.
POOL_HANDLERS = {0x0C: (3, False), 0x36: (2, False), 0x15: (3, True),
                 0x25: (2, True), 0x26: (2, True), 0x2B: (2, True)}
#: Pool of Radiance's opcodes run from `$00` to `CLEAR BOX` (`$3D`).
POOL_OPCODES = 0x3E


def pool_models():
    """`(model, skip)` for Pool of Radiance: the counts a walk follows and the
    counts a false `IF` skips with, in the form `decode` reads."""
    skip = [(0, False)] * POOL_OPCODES
    for n, ops in POOL_SKIP_GROUPS.items():
        for op in ops:
            skip[op] = (n, False)
    model = list(skip)
    model[0x1F] = (0, False)
    for op, counts in POOL_HANDLERS.items():
        model[op] = counts
    return tuple(model), tuple(skip)


EXIT, GOTO, GOSUB, RETURN, NEWECL = 0x00, 0x01, 0x02, 0x13, 0x20
ONGOTO, ONGOSUB = 0x25, 0x26
CONDITIONS = range(0x16, 0x1C)
#: Nothing runs after these. Pools of Darkness' `$23` clears the text window
#: and calls the `EXIT` handler.
STOPS = {EXIT, GOTO, RETURN, NEWECL}
EXTRA_STOPS = {DARKNESS: {0x23}}

#: Every SAS/C title runs its scripts from ECL address `$8000`; Pool of
#: Radiance's, as its DOS and C64 versions, from `$9900`.
SCRIPT_BASE = 0x8000
BASES = {POOL: 0x9900}
ENTRIES = 5


@dataclasses.dataclass(frozen=True)
class Statement:
    at: int
    end: int
    op: int
    operands: tuple[tuple[int, int], ...]

    def address(self, n: int) -> int | None:
        if n >= len(self.operands) or self.operands[n][0] in (0x00, 0x80):
            return None
        return self.operands[n][1]


def _operand(body: bytes, i: int):
    """`(length, kind, value)` as the engine's operand loader reads it: kinds 1
    to 3 and `$81` carry a two-byte value, `$80` a string of that many bytes,
    and anything else one byte."""
    if i + 1 >= len(body):
        return None
    kind = body[i]
    if kind == 0x80:
        return 2 + body[i + 1], kind, body[i + 1]
    if kind in (1, 2, 3, 0x81):
        if i + 2 >= len(body):
            return None
        return 3, kind, body[i + 1] | body[i + 2] << 8
    return 2, kind, body[i + 1]


def decode(model, body: bytes, i: int) -> Statement | None:
    if not 0 <= i < len(body) or body[i] >= len(model):
        return None
    op = body[i]
    n, counted = model[op]
    j, operands = i + 1, []
    while len(operands) < n:
        got = _operand(body, j)
        if got is None:
            return None
        size, kind, value = got
        operands.append((kind, value))
        j += size
        if counted and len(operands) == n:
            if kind != 0x00:
                return None
            n, counted = n + value, False
    return Statement(i, j, op, tuple(operands)) if j <= len(body) else None


def walk(title: str, model, skip, body: bytes, entries=range(ENTRIES)):
    """Every statement reachable from the chosen entry `GOTO`s, and the
    offsets a walk tried and could not decode."""
    found: dict[int, Statement] = {}
    bad: set[int] = set()
    stops = STOPS | EXTRA_STOPS.get(title, set())
    base = BASES.get(title, SCRIPT_BASE)
    work = []
    for n in entries:
        head = decode(model, body, 4 * n)
        if head is not None and head.op == GOTO and head.address(0) is not None:
            work.append(head.address(0) - base)
    while work:
        i = work.pop()
        if i in found or i in bad:
            continue
        s = decode(model, body, i)
        if s is None:
            bad.add(i)
            continue
        found[i] = s
        nxt = []
        if s.op in (GOTO, GOSUB) and s.address(0) is not None:
            nxt.append(s.address(0) - base)
        if s.op in (ONGOTO, ONGOSUB):
            nxt += [s.address(k) - base
                    for k in range(2, len(s.operands)) if s.address(k) is not None]
        if s.op not in stops:
            nxt.append(s.end)
        if s.op in CONDITIONS:
            skipped = decode(skip, body, s.end)
            if skipped is not None:
                nxt.append(skipped.end)
        work += nxt
    return found, bad


def tail_references(found, length: int,
                    base: int = SCRIPT_BASE) -> list[tuple[int, int, int]]:
    """`(statement offset, opcode, address)` for every operand naming a byte
    of the buffer past the script."""
    out = []
    for s in found.values():
        for kind, value in s.operands:
            if kind not in (0x00, 0x80) and \
                    base + length <= value < base + BUFFER:
                out.append((s.at, s.op, value))
    return out


def init_overlap(title: str, model, skip, body: bytes,
                 span: int | None = NEWECL_BYTES
                 ) -> tuple[int, list[int], list[int]]:
    """Whether the first `span` bytes of the init entry (to the buffer's end,
    where `span` is None) are dead outside it.

    Returns the init entry's offset, every statement reachable from the other
    four entries that covers one of those bytes, and every operand of those
    statements naming one of them. Both lists empty means nothing but the
    init entry, which the engine runs only straight after loading the script,
    reaches those bytes.
    """
    base = BASES.get(title, SCRIPT_BASE)
    head = decode(model, body, 4 * (ENTRIES - 1))
    init = head.address(0) - base
    if span is None:
        span = BUFFER - init
    found, _bad = walk(title, model, skip, body, range(ENTRIES - 1))
    covers = sorted(s.at for s in found.values()
                    if s.at < init + span and s.end > init)
    names = sorted(s.at for s in found.values() for kind, value in s.operands
                   if kind not in (0x00, 0x80)
                   and init <= value - base < init + span)
    return init, covers, names


@dataclasses.dataclass(frozen=True)
class InitSpace:
    """An area's init span, from its init entry to the buffer's end."""

    area: int
    start: int
    #: Statements of entries 0-3 covering, or naming, a byte of the span.
    covers: tuple[int, ...]
    names: tuple[int, ...]
    #: The script's bytes in the span on the disk, and their SHA-1.
    size: int
    sha1: str

    @property
    def free(self) -> bool:
        """Nothing outside the init entry reaches the span."""
        return not self.covers and not self.names


def init_space(title: str, model, skip, area: int, body: bytes) -> InitSpace:
    """The init span of one area's `body` (its script, header dropped)."""
    init, covers, names = init_overlap(title, model, skip, body, span=None)
    disk = body[init:]
    return InitSpace(area, init, tuple(covers), tuple(names), len(disk),
                     hashlib.sha1(disk).hexdigest())


#: Pools of Darkness' overland cell: x and y.
OVERLAND_VARS = (0x25, 0x26)
SAVE = 0x09


def overland_landings(title: str, model, skip, library: bytes,
                      targets=None) -> dict[int, tuple[int, int]]:
    """The cell `$25`/`$26` the game's first exit into each overland writes.

    An exit is a `NEWECL` with an immediate target, counted only if the
    `SAVE`s straight before it (each ending where the next statement starts)
    write constants to both variables. Exits are ordered by the departing
    area, then by script address; `targets` limits the areas reported.
    """
    blocks = glib_blocks(library)
    out: dict[int, tuple[int, int]] = {}
    for space in spaces(title, library):
        found, _bad = walk(title, model, skip, blocks[space.block])
        saves = {s.end: s for s in found.values()
                 if s.op == SAVE and len(s.operands) == 2
                 and s.operands[0][0] == 0x00 and s.operands[1][0] == 1}
        for at in sorted(found):
            s = found[at]
            if s.op != NEWECL or not s.operands or s.operands[0][0] != 0x00:
                continue
            to = s.operands[0][1]
            if to in out or (targets is not None and to not in targets):
                continue
            cell = {}
            end = s.at
            while end in saves:
                save = saves[end]
                var = save.operands[1][1]
                if var in OVERLAND_VARS:
                    cell.setdefault(var, save.operands[0][1])
                end = save.at
            if all(v in cell for v in OVERLAND_VARS):
                out[to] = tuple(cell[v] for v in OVERLAND_VARS)
    return out


# -- the command -------------------------------------------------------------

def table(args) -> int:
    titles = [args.title] if args.title else list(TITLES)
    wanted = {t: LIBRARY[t] for t in titles}
    any_found = False
    for title, label, path, body in disk_files(images(args.disks), wanted):
        any_found = True
        rows = spaces(title, body)
        digest = hashlib.sha256(body).hexdigest()[:12]
        print(f"{title}  {path}  sha256 {digest}  ({label.rsplit('/', 1)[-1]})")
        print("  area  block  length  free  tier  tier+area-file  tier+grid")
        for s in rows:
            print(f"  {s.area:4}  {s.block:5}  {s.length:6}  {s.free:4}  "
                  f"{tier(title, s.length):4}  "
                  f"{tier(title, s.length, area_file=True):14}  "
                  f"{tier(title, s.length, grid=True):9}")
        short = [s.area for s in rows if tier(title, s.length) > 1]
        print(f"  {len(rows)} scripts; not tier 1: {short}")
    if not any_found:
        print("No Amiga script library found on the disks.")
        return 1
    return 0


def pool_refs(args) -> int:
    """`refs` for Pool of Radiance: the walk of every script, and each area's
    init span with who reaches it and the SHA-1 of its disk bytes."""
    model, skip = pool_models()
    status = 1
    for _t, _label, path, lib in disk_files(images(args.disks),
                                            {POOL: LIBRARY[POOL]}):
        status = 0
        print(f"{path} sha256 {hashlib.sha256(lib).hexdigest()[:12]}")
        for area, block in amiga_dax.blocks(lib, LIBRARY[POOL]):
            body = block[POOL_HEADER:]
            got, bad = walk(POOL, model, skip, body)
            hits = tail_references(got, len(body), BASES[POOL])
            space = init_space(POOL, model, skip, area, body)
            line = (f"  area {area:3} len {len(body):5} free "
                    f"{BUFFER - len(body):4}: {len(got):4} statements, "
                    f"{len(bad)} undecodable, {len(hits)} tail refs")
            if BUFFER - len(body) < FULL_BYTES and not space.covers:
                line += (f"; init {BASES[POOL] + space.start:#06x}, span "
                         f"{space.start:#06x}-{BUFFER:#06x}, entries 0-3 cover "
                         f"{len(space.covers)} statements and name "
                         f"{len(space.names)}, {space.size} disk bytes "
                         f"sha1 {space.sha1}")
            print(line)
    if status:
        print("No Pool of Radiance script library found on the disks.")
    return status


def glib_model(title: str, images_):
    """`(model, skip)` for a title whose operand counts are read from its own
    executable, or None. Prints what it read."""
    found = list(disk_files(images_, {title: EXECUTABLE[title]}))
    models = {}
    for _t, label, path, body in found:
        from tools.amiga.amiga68k import Executable
        try:
            code = Executable.parse(body).data
        except Exception:                       # not a hunk file we can read
            code = b""
        model = skip_model(code)
        digest = hashlib.sha256(body).hexdigest()[:12]
        print(f"{path} sha256 {digest}: "
              + ("skip switch read" if model else "no skip switch (packed?)"))
        if model:
            models[model] = digest
    if len(models) != 1:
        print(f"{len(models)} distinct operand models; need exactly one.")
        return None
    print(f"Operand model from the skip switch of {next(iter(models.values()))}"
          f"; a library whose own executable is unreadable is walked with it.")
    skip = next(iter(models))
    model = list(skip)
    for op, counts in HANDLER_COUNTS.get(title, {}).items():
        model[op] = counts
    return tuple(model), skip


def refs(args) -> int:
    title = args.title
    if title == POOL:
        return pool_refs(args)
    got = glib_model(title, images(args.disks))
    if got is None:
        return 1
    model, skip = got
    status = 0
    for _t, label, path, lib in disk_files(images(args.disks),
                                           {title: LIBRARY[title]}):
        blocks = glib_blocks(lib)
        print(f"{path} sha256 {hashlib.sha256(lib).hexdigest()[:12]}")
        for s in spaces(title, lib):
            body = blocks[s.block]
            got, bad = walk(title, model, skip, body)
            hits = tail_references(got, s.length)
            line = (f"  area {s.area:3} block {s.block:2} len {s.length:5} "
                    f"free {s.free:4}: {len(got):4} statements, "
                    f"{len(bad)} undecodable, {len(hits)} tail refs")
            if s.free < NEWECL_BYTES:
                init, covers, names = init_overlap(title, model, skip, body)
                first = decode(model, body, init)
                line += (f"; init ${SCRIPT_BASE + init:04X}, first statement "
                         f"{first.end - first.at if first else '?'} bytes; "
                         f"entries 0-3 cover it at {covers}, name it at {names}")
            print(line)
            if hits or bad:
                status = 2
                print(f"     tail refs {[(hex(a), hex(o), hex(v)) for a, o, v in hits]}"
                      f" undecodable at {sorted(bad)[:8]}")
    return status


def landings(args) -> int:
    from goldbox import areas
    ids = {a.id for a in areas.TABLES[areas.POOLS_OF_DARKNESS]
           if a.overland_view}
    got = glib_model(DARKNESS, images(args.disks))
    if got is None:
        return 1
    model, skip = got
    status = 1
    for _t, _label, path, lib in disk_files(images(args.disks),
                                            {DARKNESS: LIBRARY[DARKNESS]}):
        status = 0
        cells = overland_landings(DARKNESS, model, skip, lib, ids)
        print(f"{path} sha256 {hashlib.sha256(lib).hexdigest()[:12]}")
        for area in sorted(ids):
            cell = cells.get(area)
            print(f"  overland {area:3}: "
                  + (f"({cell[0]}, {cell[1]})" if cell else "no constant exit"))
    if status:
        print("No Pools of Darkness script library found on the disks.")
    return status


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--disks", help="a folder of loose .adf images; "
                        "default: the registry's amiga entry")
    sub = parser.add_subparsers(dest="command")
    r = sub.add_parser("refs", help="walk each script for tail references")
    r.add_argument("title", choices=TITLES)
    sub.add_parser("landings", help="the overland cells Pools of Darkness' "
                   "exits write")
    parser.add_argument("--title", choices=TITLES)
    args = parser.parse_args(argv)
    if args.command == "refs":
        return refs(args)
    if args.command == "landings":
        return landings(args)
    return table(args)


if __name__ == "__main__":
    sys.exit(main())
