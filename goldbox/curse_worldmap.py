"""Curse of the Azure Bonds' world map, read out of the game's own files.

On the C64 the Dalelands map is two area scripts, `ECL50` and `ECL51`, and a
display driver, `GDRIVE02`. The party stands at one of fourteen places
(`$4C9B`) and travels along the roads the scripts' neighbour table lists. This
module reads that table, the place names and the marker cells, and finds each
one by the statements that use it rather than by its contents:

* **The neighbour table** is the one the arrival routine reads into
  `$4C02`-`$4C05`: `MUL [$4C9C], #4, [i]`, then one `GETTABLE [table], [i],
  [$4C02 + k]` per slot with `ADD #1, [i], [i]` between. The multiplier is
  the row width, and the number of `GETTABLE`s must agree with it.
* **The place count and names** come from the routine `JOURNEY ON` calls
  straight after `GETTABLE [$4C02], [choice], [$4C9C]`: an `ONGOTO [$4C9C]`
  whose arms each store one packed string and return.
* **Which script owns a place.** Each script's names are right only for the
  places it handles; for the others an arm repeats a neighbour's name. The
  legs a script hands to the other script are `COMPARE [$4C9D], #leg; IF=;
  NEWECL #script`. A script owns the places reachable from those legs' start
  places without taking a leg that leaves the script.
* **The `JOURNEY ON` rows** are the vertical menus (`$15`) on each arm of the
  `ONGOTO [$4C9B]` that ends in the choice `GETTABLE`. A slot that appears in
  only some of a place's menus is a road the script offers on a condition.
* **The marker cells** are `GDRIVE02`'s two tables indexed by `LDX $4CA1`:
  `LDY abs,X` is the column and `LDA abs,X` the row, each drawn one cell
  further on (`INY`, `ADC #1`). `$4CA1` holds the place at a stop and a
  per-leg waypoint (`GETTABLE [table], [$4C9D], [$4CA1]`) on the road.

The operand counts of the few opcodes decoded here were read off Curse's
`DUNGEON` dispatch tables; the player-disk test checks them against it. Nothing
here holds a byte of the game's: every value is read from the files passed in.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

#: The script variables the world-map scripts use, in the save's address space.
NODE = 0x4C9B          # the place the party stands at
DESTINATION = 0x4C9C   # the place a leg is going to
LEG = 0x4C9D           # 4 x place + slot: which leg, an index into the tables
NEIGHBOURS = 0x4C02    # the current place's row of the neighbour table
MARKER = 0x4CA1        # the marker position GDRIVE02 draws

GOTO, GOSUB, COMPARE, ADD, MUL, SAVE = 0x01, 0x02, 0x03, 0x04, 0x07, 0x09
RETURN, BOTH_EQUAL, MENU = 0x13, 0x14, 0x15
NEWECL, ONGOTO, GETTABLE = 0x20, 0x25, 0x2A
#: `IF=` to `IF>=`: a false condition skips the next statement.
CONDITIONS = range(0x16, 0x1C)

#: Fixed operand counts for the opcodes this module decodes.
OPERANDS = {GOTO: 1, GOSUB: 1, COMPARE: 2, ADD: 3, MUL: 3, SAVE: 2,
            RETURN: 0, BOTH_EQUAL: 4, NEWECL: 1, GETTABLE: 3,
            **{op: 0 for op in CONDITIONS}}
#: Opcodes whose last fixed operand counts the operands after it.
COUNTED = {MENU: 3, ONGOTO: 2}

IMMEDIATE, STRING = 0x00, 0x80
#: A neighbour slot with no road.
NO_ROAD = 0xFF

#: 6502 opcodes in GDRIVE02's marker routine.
_JMP, _LDX_ABS, _LDA_ABS_X, _LDY_ABS_X = 0x4C, 0xAE, 0xBD, 0xBC


class WorldMapError(ValueError):
    """The files do not hold the statements this reader finds the map by."""


def unpack(payload: bytes) -> str:
    """A packed string's characters: six-bit groups, most significant bit
    first, `$01`-`$1F` OR'd with `$40`, `$00` ending the run."""
    out: list[str] = []
    accumulator = bits = 0
    for byte in payload:
        for shift in range(7, -1, -1):
            accumulator = (accumulator << 1) | ((byte >> shift) & 1)
            bits += 1
            if bits < 6:
                continue
            value, accumulator, bits = accumulator, 0, 0
            if value == 0:
                return "".join(out)
            out.append(chr(value | 0x40 if value < 0x20 else value))
    return "".join(out)


# -- statements --------------------------------------------------------------

@dataclass(frozen=True)
class Operand:
    kind: int
    value: int          # the immediate, the address, or a string's length
    payload: bytes = b""

    def is_address(self, address: int | None = None) -> bool:
        if self.kind in (IMMEDIATE, STRING):
            return False
        return address is None or self.value == address

    def is_immediate(self, value: int | None = None) -> bool:
        return self.kind == IMMEDIATE and (value is None or self.value == value)


@dataclass(frozen=True)
class Statement:
    at: int
    end: int
    op: int
    operands: tuple[Operand, ...]


def _operand(body: bytes, i: int):
    if i + 1 >= len(body):
        return None
    kind = body[i]
    if kind == STRING:
        n = body[i + 1]
        if i + 2 + n > len(body):
            return None
        return Operand(kind, n, bytes(body[i + 2:i + 2 + n])), i + 2 + n
    if kind == IMMEDIATE:
        return Operand(kind, body[i + 1]), i + 2
    if i + 2 >= len(body):
        return None
    return Operand(kind, body[i + 1] | (body[i + 2] << 8)), i + 3


def decode(body: bytes, i: int) -> Statement | None:
    """The statement at offset `i`, if it is one of the opcodes read here."""
    if not 0 <= i < len(body):
        return None
    op = body[i]
    wanted = COUNTED.get(op, OPERANDS.get(op))
    if wanted is None:
        return None
    j, operands = i + 1, []
    for _ in range(wanted):
        got = _operand(body, j)
        if got is None:
            return None
        operand, j = got
        operands.append(operand)
    if op in COUNTED:
        if not operands[-1].is_immediate():
            return None
        for _ in range(operands[-1].value):
            got = _operand(body, j)
            if got is None:
                return None
            operand, j = got
            operands.append(operand)
    return Statement(i, j, op, tuple(operands))


def _statements(body: bytes):
    """Every offset that decodes as one of the statements read here.

    A byte scan, so it also finds look-alikes inside data; every caller
    matches a run of several statements and insists on exactly one match.
    """
    for i in range(len(body)):
        statement = decode(body, i)
        if statement is not None:
            yield statement


# -- one script --------------------------------------------------------------

@dataclass(frozen=True)
class ScriptMap:
    """What one world-map script says, in its own terms."""
    script: int                          # the area id, `$50` for `ECL50`
    base: int                            # where the script runs
    width: int                           # neighbour slots per place
    names: tuple[str | None, ...]        # its name switch, one per place
    table: bytes                         # count x width, `NO_ROAD` empty
    waypoints: bytes | None              # marker position per leg
    leaving: Mapping[int, int]           # leg -> the script it hands over to
    menus: Mapping[int, tuple[tuple[str, ...], ...]]  # place -> JOURNEY ON rows

    @property
    def count(self) -> int:
        return len(self.names)

    def row(self, place: int) -> bytes:
        return self.table[place * self.width:(place + 1) * self.width]

    def owned(self) -> frozenset[int]:
        """The places this script handles: reachable from the start of each
        leg it hands over, along legs that stay inside it."""
        if not self.leaving:
            return frozenset(range(self.count))
        seen: set[int] = set()
        work = [leg // self.width for leg in self.leaving]
        while work:
            place = work.pop()
            if place in seen:
                continue
            seen.add(place)
            for slot, target in enumerate(self.row(place)):
                if target != NO_ROAD and place * self.width + slot not in self.leaving:
                    work.append(target)
        return frozenset(seen)


def _neighbour_routine(found: list[Statement], body: bytes):
    """`(offset, width, table address, index variable)` of the routine that
    fills `$4C02` onwards from the neighbour table."""
    hits = []
    for st in found:
        if not (st.op == MUL and st.operands[0].is_address(DESTINATION)
                and st.operands[1].is_immediate() and st.operands[2].is_address()):
            continue
        width, index = st.operands[1].value, st.operands[2].value
        nxt = decode(body, st.end)
        if nxt is not None and nxt.op == SAVE:
            nxt = decode(body, nxt.end)
        table, slot = None, 0
        while nxt is not None and nxt.op in (GETTABLE, ADD):
            if nxt.op == GETTABLE:
                source, at, into = nxt.operands
                if not (at.is_address(index) and into.is_address(NEIGHBOURS + slot)):
                    break
                if table not in (None, source.value):
                    break
                table, slot = source.value, slot + 1
            elif not (nxt.operands[0].is_immediate(1)
                      and nxt.operands[1].is_address(index)
                      and nxt.operands[2].is_address(index)):
                break
            nxt = decode(body, nxt.end)
        if table is not None and slot == width and nxt is not None and nxt.op == RETURN:
            hits.append((st.at, width, table, index))
    if len(hits) != 1:
        raise WorldMapError(
            f"{len(hits)} routines fill ${NEIGHBOURS:04X} from a table indexed "
            f"by [${DESTINATION:04X}] x width; expected one")
    return hits[0]


def _base(body: bytes, found: list[Statement], routine: int) -> int:
    """The page the script runs at: inside the reach of its five entry
    `GOTO`s, and the one at which something `GOSUB`s the neighbour routine."""
    targets = []
    for n in range(5):
        st = decode(body, n * 4)
        if st is None or st.op != GOTO or not st.operands[0].is_address():
            raise WorldMapError(f"entry {n} is not a GOTO")
        targets.append(st.operands[0].value)
    called = {st.operands[0].value for st in found
              if st.op == GOSUB and st.operands[0].is_address()}
    pages = [page for page in range(0, 0x10000, 0x100)
             if page <= min(targets) and max(targets) < page + len(body)
             and page + routine in called]
    if len(pages) != 1:
        raise WorldMapError(f"the script base is not pinned: {len(pages)} pages fit")
    return pages[0]


def _table(body: bytes, base: int, address: int, size: int) -> bytes:
    at = address - base
    if not 0 <= at <= len(body) - size:
        raise WorldMapError(f"table ${address:04X} is not inside the script")
    return bytes(body[at:at + size])


def _menus(body: bytes, base: int, found: list[Statement], count: int,
           choice: int, choice_at: int) -> dict[int, tuple[tuple[str, ...], ...]]:
    """Each place's JOURNEY ON rows, from the `ONGOTO [$4C9B]` whose arms
    reach the choice `GETTABLE` through a menu into `[choice]`."""
    switches = []
    for st in found:
        if not (st.op == ONGOTO and st.operands[0].is_address(NODE)
                and st.operands[1].value == count):
            continue
        menus: dict[int, tuple[tuple[str, ...], ...]] = {}
        for place, arm in enumerate(st.operands[2:]):
            got: list[tuple[str, ...]] = []
            work, seen = [(arm.value - base, None)], set()
            while work:
                at, pending = work.pop()
                if (at, pending) in seen or len(seen) > 256:
                    continue
                seen.add((at, pending))
                if at == choice_at:
                    if pending is not None and pending not in got:
                        got.append(pending)
                    continue
                here = decode(body, at)
                if here is None or here.op in (RETURN, NEWECL, ONGOTO):
                    continue
                if here.op == MENU and here.operands[0].is_address(choice):
                    pending = tuple(unpack(o.payload) for o in here.operands[3:])
                if here.op == GOTO:
                    work.append((here.operands[0].value - base, pending))
                    continue
                work.append((here.end, pending))
                if here.op in CONDITIONS:
                    skipped = decode(body, here.end)
                    if skipped is not None:
                        work.append((skipped.end, pending))
            if got:
                menus[place] = tuple(got)
        if menus:
            switches.append(menus)
    if len(switches) != 1:
        raise WorldMapError(f"{len(switches)} JOURNEY ON switches found; expected one")
    return switches[0]


def read_script(body: bytes, script: int) -> ScriptMap:
    """One world-map script's table, names, hand-overs and menus.

    `body` is the file without its two-byte load address; `script` is its
    area id, which only labels the result.
    """
    found = list(_statements(body))
    routine, width, table_at, _index = _neighbour_routine(found, body)
    base = _base(body, found, routine)

    picks = [st for st in found if st.op == GETTABLE
             and st.operands[0].is_address(NEIGHBOURS)
             and st.operands[2].is_address(DESTINATION)]
    if len(picks) != 1:
        raise WorldMapError(f"{len(picks)} choice GETTABLEs into "
                            f"${DESTINATION:04X}; expected one")
    pick = picks[0]
    choice = pick.operands[1].value
    call = decode(body, pick.end)
    if call is None or call.op != GOSUB:
        raise WorldMapError("the choice is not followed by the name routine")
    switch = decode(body, call.operands[0].value - base)
    if switch is None or switch.op != ONGOTO or not switch.operands[0].is_address(DESTINATION):
        raise WorldMapError("the name routine is not an ONGOTO on the destination")
    names: list[str | None] = []
    for arm in switch.operands[2:]:
        store = decode(body, arm.value - base)
        done = decode(body, store.end) if store is not None else None
        if (store is not None and store.op == SAVE and store.operands[0].kind == STRING
                and done is not None and done.op == RETURN):
            names.append(unpack(store.operands[0].payload))
        else:
            names.append(None)
    count = len(names)
    table = _table(body, base, table_at, count * width)

    waypoints = None
    marks = [st for st in found if st.op == GETTABLE
             and st.operands[1].is_address(LEG) and st.operands[2].is_address(MARKER)]
    if len(marks) == 1:
        waypoints = _table(body, base, marks[0].operands[0].value, count * width)

    leaving: dict[int, int] = {}
    for st in found:
        if st.op == COMPARE and st.operands[0].is_address(LEG) and st.operands[1].is_immediate():
            test = decode(body, st.end)
            jump = decode(body, test.end) if test is not None else None
            if (test is not None and test.op == 0x16 and jump is not None
                    and jump.op == NEWECL and jump.operands[0].is_immediate()):
                leaving[st.operands[1].value] = jump.operands[0].value

    menus = _menus(body, base, found, count, choice, pick.at)
    return ScriptMap(script, base, width, tuple(names), table, waypoints,
                     leaving, menus)


# -- the whole map -----------------------------------------------------------

@dataclass(frozen=True)
class Place:
    index: int
    name: str | None            # None: no script that owns it names it
    script: int | None          # the area id of the script that handles it
    rows: tuple[str, ...]       # its longest JOURNEY ON menu
    cell: tuple[int, int] | None  # (column, row) of the marker on the picture


@dataclass(frozen=True)
class Leg:
    index: int                  # source x width + slot, as `$4C9D` holds it
    source: int
    slot: int
    target: int
    conditional: bool | None    # offered only in some of the source's menus
    leaves_for: int | None      # the script that takes over, if another
    waypoint: int | None        # the marker position while on this leg


@dataclass(frozen=True)
class Road:
    a: int
    b: int
    forward: Leg | None         # a -> b
    backward: Leg | None        # b -> a

    @property
    def one_way(self) -> bool:
        return self.forward is None or self.backward is None


@dataclass(frozen=True)
class WorldMap:
    places: tuple[Place, ...]
    legs: tuple[Leg, ...]
    roads: tuple[Road, ...]
    cells: tuple[tuple[int, int], ...]   # every marker position, places first


def read_marker_cells(driver: bytes) -> tuple[tuple[int, int], ...]:
    """`GDRIVE02`'s marker cells as `(column, row)`, one per `$4CA1` value.

    `driver` is the file without its load address. The base is the page both
    entry `JMP`s at offsets 0 and 3 land inside; the header's own address is
    not it.
    """
    if len(driver) < 6 or driver[0] != _JMP or driver[3] != _JMP:
        raise WorldMapError("the driver does not open with two JMPs")
    targets = [driver[1] | (driver[2] << 8), driver[4] | (driver[5] << 8)]
    pages = [page for page in range(0, 0x10000, 0x100)
             if all(page <= t < page + len(driver) for t in targets)]
    if len(pages) != 1:
        raise WorldMapError(f"the driver base is not pinned: {len(pages)} pages fit")
    base = pages[0]
    columns = rows = None
    for i in range(len(driver) - 5):
        if driver[i] == _LDX_ABS and driver[i + 1] | (driver[i + 2] << 8) == MARKER:
            address = driver[i + 4] | (driver[i + 5] << 8)
            if driver[i + 3] == _LDY_ABS_X:
                columns = address
            elif driver[i + 3] == _LDA_ABS_X:
                rows = address
    if columns is None or rows is None:
        raise WorldMapError(f"no column and row tables indexed by ${MARKER:04X}")
    size = abs(rows - columns)
    start = [columns - base, rows - base]
    if min(start) < 0 or max(start) + size > len(driver):
        raise WorldMapError("the marker tables are not inside the driver")
    return tuple((driver[start[0] + n] + 1, driver[start[1] + n] + 1)
                 for n in range(size))


def read_world_map(scripts: Mapping[str, bytes],
                   driver: bytes | None = None) -> WorldMap:
    """The places and roads of every world-map script given, merged.

    `scripts` maps a file name (`"ECL50"`) to its body without the load
    address. All of them must carry the same neighbour table, since a leg's
    index is shared across the hand-over. `driver` is `GDRIVE02`, for cells.
    """
    if not scripts:
        raise WorldMapError("no script given")
    maps = [read_script(body, int(name[3:], 16)) for name, body in sorted(scripts.items())]
    first = maps[0]
    for other in maps[1:]:
        if (other.table, other.width) != (first.table, first.width):
            raise WorldMapError(
                f"script ${other.script:02X}'s neighbour table differs from "
                f"${first.script:02X}'s")
    owner: dict[int, ScriptMap] = {}
    for m in maps:
        for place in m.owned():
            if place in owner:
                raise WorldMapError(f"place {place} is handled by two scripts")
            owner[place] = m
    cells = read_marker_cells(driver) if driver is not None else ()

    places = []
    for n in range(first.count):
        m = owner.get(n)
        menus = m.menus.get(n, ()) if m else ()
        places.append(Place(
            n, m.names[n] if m else None, m.script if m else None,
            max(menus, key=len) if menus else (),
            cells[n] if n < len(cells) else None))

    legs = []
    for n in range(first.count):
        m = owner.get(n)
        menus = m.menus.get(n, ()) if m else ()
        for slot, target in enumerate(first.row(n)):
            if target == NO_ROAD:
                continue
            if target >= first.count:
                raise WorldMapError(f"place {n} slot {slot} names place {target}")
            index = n * first.width + slot
            way = (m or first).waypoints
            legs.append(Leg(
                index, n, slot, target,
                (any(len(rows) <= slot for rows in menus) if menus else None),
                m.leaving.get(index) if m else None,
                None if way is None or way[index] == NO_ROAD else way[index]))
        if menus and max(len(rows) for rows in menus) != sum(
                t != NO_ROAD for t in first.row(n)):
            raise WorldMapError(f"place {n}'s JOURNEY ON rows do not match its table row")

    by_pair: dict[tuple[int, int], dict[str, Leg]] = {}
    for leg in legs:
        a, b = sorted((leg.source, leg.target))
        by_pair.setdefault((a, b), {})["forward" if leg.source == a else "backward"] = leg
    roads = tuple(Road(a, b, got.get("forward"), got.get("backward"))
                  for (a, b), got in sorted(by_pair.items()))
    return WorldMap(tuple(places), tuple(legs), roads, cells)
