#!/usr/bin/env python3
"""Which effect ids the engine asks a character's **trait slots** about.

`#252 (Does a C64 trait slot apply an item-granted effect id, or only the ones
its own READY routine wrote?)` is the question this answers. The ten trait
slots at record `0x0AD` are one of *two* backing stores the C64 engine keeps
for "does this character have effect N?"; the other is the 64-entry active
effect array in the save header. Two routines sit over them:

* the **array-only** predicate -- `LIBRARY $3FE4` in Pool of Radiance, with
  `$3FE1` a `LDX $6DB4` wrapper that supplies the current character. A caller
  that goes here never sees a trait slot.
* the **array-then-traits** predicate at `$4027`, three instructions long:
  `JSR $3FE4 / BCC / RTS` and then `LDX #$09 / LDA $6BAD,X / CMP <wanted>`.
  A caller that goes here treats a trait slot exactly like a running spell.

So the answer to "does a trait slot apply an id put there" is a **census of
which ids reach which predicate**, and there are two halves to it.

The **literal** half is the call sites that name the id with a `LDA #imm`,
which is what this printed on its own until `--lists`. It is the smaller
half and on its own it misleads: it reports Pool of Radiance's 61, the Ring
of Fire Resistance id, as asked about nowhere, when 61 is on two check lists.

The **data** half is `--lists`. The combat engine keeps a zero-terminated id
list per check under the I/O area and walks it, so no literal appears
anywhere and a caller arrives with the id in a register. `tools/c64/traitask.py`
read Pool of Radiance's lists out of RAM bank 1 in a running game;
`--lists` reads any title's off the disks, and reproduces that live reading
byte for byte -- `SPELLE65 +0x0570`, 20 lists, 134 ids, 92 distinct.

    tools/c64/traitquery.py pool-of-radiance
    tools/c64/traitquery.py curse-of-the-azure-bonds --sites
    tools/c64/traitquery.py secret-of-the-silver-blades --lists
    tools/c64/traitquery.py secret-of-the-silver-blades --compare \
        curse-of-the-azure-bonds
    tools/c64/traitquery.py secret-of-the-silver-blades --spells
    tools/c64/traitquery.py secret-of-the-silver-blades --handlers 60 79 90

What `--lists` came back with, on 2026-09-10, and the last column is why
`#497 (The trait picker offers a Secret of the Silver Blades character six
names, and nobody has ruled on whether it should offer Pool of Radiance's
129)` wanted it:

| title | ids in the namespace | on the lists | honoured in all | our table names |
|---|---|---|---|---|
| Pool of Radiance | 139 | 92 | 95 | 95 |
| Curse of the Azure Bonds | 146 | 115 | 120 | 106 |
| Secret of the Silver Blades | 113 | 80 | 90 | 6, and all 90 after #497 |

Nothing here needs an emulator or a save: it reads the overlays off the
player's own disks through `tools/registry/gamedisks.py`, and nothing it prints is
committed.

## Naming an id, which is what `--compare` and `--spells` are for

`--lists` says which ids matter and nothing about what any of them means.
Two more readings off the same disks do say, and #497 used both:

* **`--compare TITLE`** puts each id's check-list membership beside the same
  id's membership in another title. The walker takes a list *number*, so list
  12 is "target, saving throw" whichever title is running, and an id in the
  same numbered list in two titles is being asked the same question about the
  same thing. 46 of Silver Blades' 90 agree with Curse that way. It is
  positional agreement rather than a read of a handler, so it earns PROBABLE
  -- and `--spells` caught it wrong three times in twenty-eight.
* **`--spells`** reads the per-spell record the engine copies when a spell is
  cast and prints the effect id each spell writes, with the game's own message
  beside it. That is the game's data naming the id, so it earns CONFIRMED.
  Pool of Radiance keeps the table in `ECL65` at seven bytes a record, which
  `goldbox/effects.py` already reads for durations; Curse and Silver Blades
  keep a nine-byte version in `COMBAT2`. `SPELL_EFFECTS` below has the three
  and how each was located.
* **`--handlers`** disassembles the routine each id dispatches through the
  pair of tables the ask reads, indexed by the id itself. It is the route for
  an id no spell writes and no creature carries, and the one that finished
  Silver Blades: `docs/171-c64-trait-slots.md` has every reading.

## Finding the lists without knowing where anything runs

The lists are named by one absolute operand in a walker whose own overlay's
load address is unknown, so `--lists` follows the call chain out from the
predicate, which `find_predicate` below has already located from its bytes:

1. the **wrapper**, `LDX <current character> / JMP <predicate>`. Pool of
   Radiance keeps it in `COMBAT`, the later two in `ECL64`;
2. the **ask**, `STY <scratch> / PHA / JSR <wrapper>` -- one id against one
   combatant, and on a yes it dispatches that id's handler through a pair of
   `LDA <table>,X`. Those two operands are absolute, and the gap between them
   is **the size of the effect namespace**: 139, 146 and 113;
3. the **walker**, which reaches the ask with the id in A. The nearest
   `LDA <abs>,Y` in front of that call is the list base, and it has to come
   out at `<handler high table> + namespace + 1`. It does in all three
   titles, which is the layout checking itself;
4. the **file** holding the block, found by trying every offset in every
   file: the load address is the list address minus the offset, so a
   candidate stands or falls on whether the lists decode there and whether
   the handler table in front of them holds addresses in one overlay.

## Finding the predicate without knowing where the overlay runs

A PRG header on these disks is a family stamp (`docs/40-memory-map.md`), so the
address of a routine inside `LIBRARY` cannot be read off the file. This locates
it from the file's own absolute operands instead, which carry their targets
wherever the overlay runs:

1. find the trait scan by its bytes -- `A2 09 BD <lo> <hi> CD <e_lo> <e_hi>`,
   where `<lo,hi>` is the record base plus `0x0AD`. That gives the file offset
   `k` of the `LDX #$09`, and `<e_lo,e_hi>` is the scratch byte holding the id
   the caller asked about;
2. the entry is six bytes earlier: `20 <s_lo> <s_hi> 90 01 60`. `<s_lo,s_hi>`
   is the **address** of the array-only predicate;
3. that predicate opens `8D <e_lo> <e_hi> 8E`, storing the id into the same
   scratch. Find *that* byte string in the same file to get its **offset**.

Address minus offset is the overlay's run base, so the entry address falls out
of the file with nothing assumed. The base it derives is printed, and for Pool
of Radiance it comes to `$2C48`, which is what `docs/40-memory-map.md` has for
`LIBRARY` on independent evidence.
"""

from __future__ import annotations

import argparse
import collections
import os
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import c64_port, spells, traits  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from tools.c64 import d6502  # noqa: E402
from tools.c64.absrefsweep import disks, files, is_art  # noqa: E402
from tools.registry import gamedisks  # noqa: E402

#: Where `LINKER` puts an overlay it dispatches to, used only to print a call
#: site's address in the same coordinates `tools/c64/absrefsweep.py` prints.
OVERLAY_BASE = 0x0800

#: The staging record each title reads and writes a character through, and the
#: trait block's offset inside it. `tools/c64/coldread.py` carries the same pair.
STAGING = {"pool-of-radiance": 0x6B00}
STAGING_LATER = 0x7C00
TRAIT_SLOT = 0x0AD

#: How far back from a call site to look for the `LDA #imm` that set the id.
LOOKBACK = 24


def staging(game: c64_port.C64Container) -> int:
    return STAGING.get(game.key, STAGING_LATER)


class Predicate:
    """One `has this character got effect N?` routine, found in an overlay."""

    def __init__(self, file: str, base: int, entry: int, array: int,
                 scratch: int, trait_scan: int):
        self.file = file
        self.base = base            # where the overlay runs
        self.entry = entry          # array, then the ten trait slots
        self.array = array          # array only -- a trait slot is invisible
        self.scratch = scratch      # where the wanted id is parked
        self.trait_scan = trait_scan


def find_predicate(name: str, body: bytes, record: int) -> Predicate | None:
    """Locate the array-then-traits predicate in one overlay, base and all."""
    block = record + TRAIT_SLOT
    want = bytes((0xA2, 0x09, 0xBD, block & 0xFF, block >> 8, 0xCD))
    k = body.find(want)
    if k < 0 or k < 6:
        return None
    scratch = body[k + 6] | body[k + 7] << 8
    head = body[k - 6:k]
    if head[0] != 0x20 or head[3:] != bytes((0x90, 0x01, 0x60)):
        return None
    array = head[1] | head[2] << 8
    opening = bytes((0x8D, scratch & 0xFF, scratch >> 8, 0x8E))
    j = body.find(opening)
    if j < 0:
        return None
    base = array - j
    return Predicate(name, base, base + k - 6, array, scratch, base + k)


def immediate_before(body: bytes, at: int) -> set[int]:
    """Every `LDA #imm` a linear decode reaching `at` ends on, as a set.

    A 6502 has no instruction alignment, so reading backwards is a guess. This
    decodes forward from each of the `LOOKBACK` bytes before the call site and
    keeps only the runs that land **exactly** on it; the last immediate load in
    each is a candidate for the id. One value means every alignment agrees.
    """
    found: set[int] = set()
    for start in range(max(0, at - LOOKBACK), at):
        pc = start
        last: int | None = None
        while pc < at:
            op = body[pc]
            if op not in d6502.T:
                break
            mn, mode = d6502.T[op]
            size = d6502.SZ[mode]
            if mn == "LDA" and mode == d6502.M_IMM:
                last = body[pc + 1]
            elif mn in ("JSR", "JMP", "RTS", "RTI") or mode == d6502.M_REL:
                last = None                       # control left; A is not ours
            pc += size
        if pc == at and last is not None:
            found.add(last)
    return found


def call_sites(root: str, game: c64_port.C64Container, target: int):
    """`(file, offset, kind, ids)` for every `JSR`/`JMP` to one address."""
    lo, hi = target & 0xFF, target >> 8
    for _disk, name, body in files(root, game):
        if is_art(name):
            continue
        for i in range(len(body) - 2):
            if body[i + 1] != lo or body[i + 2] != hi:
                continue
            if body[i] == 0x20:
                kind = "JSR"
            elif body[i] == 0x4C:
                kind = "JMP"
            else:
                continue
            yield name, i, kind, immediate_before(body, i)


# -- the other half: the check lists a literal census cannot see -------------
#
# The combat engine never names an id in an instruction. It walks
# zero-terminated lists of ids and asks about each one, so `call_sites` above
# reports the walker as "the caller supplies it" and stops. `tools/c64/traitask.py`
# read Pool of Radiance's lists out of RAM bank 1 in a running game; the code
# below reads any title's off the disks instead, by following the call chain
# from the predicate outwards and then finding the block the walker indexes.


def bodies(root: str, game: c64_port.C64Container) -> dict[str, bytes]:
    """Every non-art file once, so a multi-pass search reads the disks once."""
    out: dict[str, bytes] = {}
    for _disk, name, body in files(root, game):
        if not is_art(name):
            out.setdefault(name, body)
    return out


def branch_targets(body: bytes) -> set[int]:
    return {body[i + 1] | body[i + 2] << 8
            for i in range(len(body) - 2) if body[i] in (0x20, 0x4C)}


def bases(body: bytes) -> list[tuple[int, int, int]]:
    """`(good - bad, good, base)` for every load address that resolves this
    file's own `JSR`/`JMP` targets, best first.

    `tools/icons/portraitdraw.py`'s `base_of` returns only the winner, and for a
    file with few branches of its own that winner is a coin toss: Pool of
    Radiance's `SQRPACI01` has six and an unrelated base resolves all six,
    beating the true `$0400`, which resolves four. So this returns the whole
    ranking and `entry_point` below applies a second constraint.
    """
    targets = branch_targets(body)
    out: list[tuple[int, int, int]] = []
    for base in range(0x0400, 0x10000 - len(body), 2):
        good = bad = 0
        for a in targets:
            if not base <= a < base + len(body):
                continue
            if body[a - base] in d6502.T:
                good += 1
            else:
                bad += 1
        if good:
            out.append((good - bad, good, base))
    out.sort(reverse=True)
    return out


def entry_point(body: bytes, offset: int, called: set[int],
                ok=None) -> int | None:
    """Where `offset` runs, given that something in the title calls it.

    A routine reached by `JSR` has its address in some other file's operand,
    so the base to believe is the best-scoring one that puts `offset` on an
    address the title actually names. That is what separates `SQRPACI01`'s
    `$0400` from the base its own six branches prefer -- and being *named* is
    not always enough on its own, since a 1024-byte file has a thousand
    offsets and the title names thousands of addresses, so `ok` lets the
    caller add what it knows about the routine it is looking for.
    """
    for _score, _good, base in bases(body):
        if base + offset in called and (ok is None or ok(base + offset)):
            return base
    return None


def find_wrapper(body_map: dict[str, bytes], entry: int):
    """`LDX <current character> / JMP <entry>` -- how the tables ask.

    The id arrives in A from a list, so the sites that matter name no id at
    all and a literal census sees nothing. Pool of Radiance keeps this in
    `COMBAT`, Curse and Silver Blades in `ECL64`.
    """
    want = bytes((0x4C, entry & 0xFF, entry >> 8))
    for name, body in sorted(body_map.items()):
        i = body.find(want)
        while i >= 0:
            if i >= 3 and body[i - 3] == 0xAE:
                return name, i - 3
            i = body.find(want, i + 1)
    return None


def find_ask(body_map: dict[str, bytes], wrapper: int):
    """`STY <scratch> / PHA / JSR <wrapper>` -- one id against one combatant.

    This is the routine that dispatches the id's handler when the answer is
    yes, so finding it also finds the two handler tables.
    """
    want = bytes((0x20, wrapper & 0xFF, wrapper >> 8))
    for name, body in sorted(body_map.items()):
        i = body.find(want)
        while i >= 0:
            if i >= 4 and body[i - 1] == 0x48 and body[i - 4] == 0x8C:
                return name, i - 4
            i = body.find(want, i + 1)
    return None


def handler_tables(body: bytes, at: int, limit: int = 48):
    """The two `LDA <table>,X` operands the ask dispatches through."""
    found = []
    for i in range(at, min(at + limit, len(body) - 2)):
        if body[i] == 0xBD:
            found.append(body[i + 1] | body[i + 2] << 8)
            if len(found) == 2:
                return found[0], found[1]
    return None


def find_walker(body_map: dict[str, bytes], ask: int, back: int = 96,
                same: str | None = None, avoid: int | None = None):
    """The routine that skips X zero-terminated lists and asks about each id.

    Its list base is the nearest `LDA <abs>,Y` in front of its call to the
    ask, which is the instruction that reads a list byte. All three measured
    titles keep the walker in the same file as the ask, and `same` says so,
    which is what stops a two-byte coincidence in an unrelated overlay
    answering. `avoid` is the ask's own offset: a wrong load address for the
    file can make the ask's own `JSR <wrapper>` read as a call to itself, and
    that is what put Pool of Radiance's `SQRPACI01` at `$252E` instead of
    `$0400` until this rejected a match four bytes into the ask.
    """
    want = bytes((0x20, ask & 0xFF, ask >> 8))
    for name, body in sorted(body_map.items()):
        if same is not None and name != same:
            continue
        i = body.find(want)
        while i >= 0:
            if avoid is not None and abs(i - avoid) <= 8:
                i = body.find(want, i + 1)
                continue
            for k in range(i - 1, max(0, i - back), -1):
                if body[k] == 0xB9:
                    return name, i, body[k + 1] | body[k + 2] << 8
            i = body.find(want, i + 1)
    return None


def read_lists(body: bytes, at: int, namespace: int):
    """`(lists, end)` decoding zero-terminated id lists from `at`, or None.

    Two things end the block and both are the next table starting: a pair of
    zero bytes, which is what Curse and Silver Blades have, and a byte too
    large to be an id, which is what Pool of Radiance has -- its lists are
    followed by a per-id flags table whose entries have bit 7 set.
    """
    lists: list[list[int]] = []
    cur: list[int] = []
    while at < len(body):
        value = body[at]
        if value >= namespace:
            return (lists, at) if not cur else None
        at += 1
        if value == 0:
            lists.append(cur)
            cur = []
            if body[at:at + 2] == b"\0\0":
                return lists, at
        else:
            cur.append(value)
    return None


def band(values: bytes) -> int:
    """How many of these bytes fall in one 16-page window.

    A handler table holds addresses of routines in one overlay, so its high
    bytes cluster; a run of text or of map data does not.
    """
    counts = collections.Counter(values)
    return max((sum(n for v, n in counts.items() if x <= v <= x + 15)
                for x in set(values)), default=0)


def find_block(body_map: dict[str, bytes], lists_at: int, high_at: int,
               namespace: int, slack: int = 15):
    """Which file holds the tables, and where that puts its load address.

    The walker's operand is an absolute address and the file is a run of
    bytes, so the load address falls out of any offset that decodes: this
    tries every offset in every file and keeps the ones where the lists
    decode *and* the handler table's high bytes cluster.

    Two things rank a candidate and which one decides depends on the file.
    **A file with code in it has its load address decided by that code**, so
    a candidate that resolves ten or more of the file's own `JSR`/`JMP`
    targets with none left undecodable wins outright -- that is what puts
    Curse's `COMBAT2` at `$E000` rather than thirteen bytes later, where the
    lists still decode and pick up the tail of the handler table as a
    thirteen-id list 0. **A file of pure data has no such evidence**: Pool of
    Radiance's `SPELLE65` resolves nothing at any base, and there the block's
    own shape decides -- distinct ids first, which is what separates it from
    the run of map data in `GEO1A` that also decodes (27 lists over 10
    distinct values against the block's 20 over 92), then list count.
    """
    best = None
    for name, body in sorted(body_map.items()):
        targets = branch_targets(body)
        for offset in range(len(body)):
            base = lists_at - offset
            if base < 0x0400 or base + len(body) > 0x10000:
                continue
            high = high_at - base
            if high < 0 or high + namespace > len(body):
                continue
            decoded = read_lists(body, offset, namespace)
            if decoded is None:
                continue
            lists, _end = decoded
            if not 12 <= len(lists) <= 32:
                continue
            distinct = len({v for one in lists for v in one})
            if distinct < 40:
                continue
            clustered = band(body[high:high + namespace])
            if clustered < namespace - slack:
                continue
            good = bad = 0
            for a in targets:
                if not base <= a < base + len(body):
                    continue
                if body[a - base] in d6502.T:
                    good += 1
                else:
                    bad += 1
            code = good if good >= 10 and not bad else 0
            row = (code, distinct, len(lists), clustered,
                   name, offset, base, lists)
            if best is None or row[:4] > best[:4]:
                best = row
    return best


def flags_tail(lists: list[list[int]]) -> bool:
    """Whether the last decoded list is really the next table's first bytes.

    Curse and Silver Blades end the block with `00 00`, and what sits in
    front of that pair is the opening of the per-id flags table rather than a
    check list: the same eight bytes in both titles, and the same eight in
    Pool of Radiance with bit 7 set, where they are outside the id namespace
    and end the decode by themselves.
    """
    return bool(lists) and len(set(lists[-1])) <= 2 and len(lists[-1]) >= 6


class Dispatch:
    """Where one title asks about an id and dispatches its handler.

    Every field is either an absolute operand read off the disks (`wrapper`,
    `ask`, `low_at`, `high_at`, `lists_at`) or a file-and-offset pair a reader
    can check by hand. `ask_base` is scored rather than read, and it is the
    one thing here that says where `COMBAT` runs -- which is what puts a
    handler address onto a file offset.
    """

    def __init__(self, body_map, called, literal, wrap_file, wrap_off,
                 wrapper, ask_file, ask_off, ask_base, low_at, high_at,
                 walk_file, walk_off, lists_at):
        self.body_map = body_map
        self.called = called
        self.literal = literal
        self.wrap_file, self.wrap_off, self.wrapper = (wrap_file, wrap_off,
                                                       wrapper)
        self.ask_file, self.ask_off, self.ask_base = (ask_file, ask_off,
                                                      ask_base)
        self.low_at, self.high_at = low_at, high_at
        self.walk_file, self.walk_off, self.lists_at = (walk_file, walk_off,
                                                        lists_at)

    @property
    def ask(self) -> int:
        return self.ask_base + self.ask_off

    @property
    def namespace(self) -> int:
        return self.high_at - self.low_at


def find_dispatch(root: str, game: c64_port.C64Container, entry: int,
                  literal: set[int]):
    """Follow the chain from the predicate out to the handler tables.

    Returns a `Dispatch`, or a string saying which link was missing. `literal`
    is widened in place with any id named at a call through the wrapper,
    which `call_sites` cannot see because it only looks at the predicate.
    """
    body_map = bodies(root, game)
    called = set()
    for body in body_map.values():
        called |= branch_targets(body)

    found = find_wrapper(body_map, entry)
    if found is None:
        return "  no LDX/JMP wrapper around the predicate; nothing to walk"
    wrap_file, wrap_off = found
    wrap_base = entry_point(body_map[wrap_file], wrap_off, called)
    if wrap_base is None:
        return (f"  {wrap_file} has the wrapper at +{wrap_off:#06x} and "
                f"nothing calls it at any load address")
    wrapper = wrap_base + wrap_off

    # Silver Blades has one caller through the wrapper that names its id:
    # `COMBAT $25D5 LDA #$18 / JSR $928F`.
    want = bytes((wrapper & 0xFF, wrapper >> 8))
    for body in body_map.values():
        i = body.find(want)
        while i >= 0:
            if i >= 1 and body[i - 1] in (0x20, 0x4C):
                ids = immediate_before(body, i - 1)
                if len(ids) == 1:
                    literal |= ids
            i = body.find(want, i + 1)

    found = find_ask(body_map, wrapper)
    if found is None:
        return f"  nothing calls ${wrapper:04X} the way the tables do"
    ask_file, ask_off = found
    tables = handler_tables(body_map[ask_file], ask_off)
    if tables is None:
        return f"  {ask_file} +{ask_off:#06x} dispatches through no table pair"
    low_at, high_at = tables
    namespace = high_at - low_at

    # The layout is its own check, and it is what pins the ask's load
    # address: the two handler tables are `namespace` bytes each and the
    # lists follow one spare byte later, so a base that puts the walker's
    # operand anywhere else has put the ask somewhere it is not.
    def lands_right(address: int) -> bool:
        walk = find_walker(body_map, address, same=ask_file,
                           avoid=ask_off)
        return walk is not None and walk[2] == high_at + namespace + 1

    ask_base = entry_point(body_map[ask_file], ask_off, called, lands_right)
    if ask_base is None:
        return (f"  {ask_file} +{ask_off:#06x} has no load address that both "
                f"puts it where something calls it and puts its walker's "
                f"list base at ${high_at + namespace + 1:04X}")
    walk_file, walk_off, lists_at = find_walker(
        body_map, ask_base + ask_off, same=ask_file, avoid=ask_off)
    return Dispatch(body_map, called, literal, wrap_file, wrap_off, wrapper,
                    ask_file, ask_off, ask_base, low_at, high_at,
                    walk_file, walk_off, lists_at)


def report_lists(root: str, game: c64_port.C64Container, entry: int,
                 literal: set[int], show: bool = True):
    """Print the check lists, and the ids they add to the literal census.

    Returns `(status, lists, honoured)` so `--compare` can take the same
    measurement without printing it: `lists` is the decoded block, one list of
    ids per check, and `honoured` is every id a trait slot can do anything
    with -- the lists plus the literal census. `show=False` silences the
    whole of it and nothing else changes.
    """
    say = print if show else (lambda *a, **k: None)
    d = find_dispatch(root, game, entry, literal)
    if isinstance(d, str):
        say(d)
        return 1, [], set()
    body_map, namespace = d.body_map, d.namespace
    low_at, high_at, lists_at = d.low_at, d.high_at, d.lists_at

    # The three addresses below are absolute operands and carry their targets
    # wherever the overlays run; the file-and-offset pairs are what a reader
    # can check by hand. Where an overlay's own load address is printed it is
    # scored rather than read, and nothing the measurement rests on uses it.
    say(f"\n  {d.wrap_file} +{d.wrap_off:#06x}: LDX <character> / JMP "
        f"${entry:04X}, the wrapper the lists ask through")
    say(f"  {d.ask_file} +{d.ask_off:#06x}: one id, one combatant, then that "
        f"id's handler")
    say(f"  {d.walk_file} +{d.walk_off:#06x}: where the walker calls it, "
        f"having\n      skipped X zero-terminated lists at ${lists_at:04X}")
    say(f"  ${low_at:04X}/${high_at:04X}: handler address per id, so the "
        f"namespace is {namespace} ids")
    if lists_at != high_at + namespace + 1:
        say(f"  ** ${lists_at:04X} is not ${high_at:04X} + {namespace} + 1; "
            f"the block is not laid out as expected")

    block = find_block(body_map, lists_at, high_at, namespace)
    if block is None:
        say("  no file holds a block that decodes at that address")
        return 1, [], set()
    (_code, _distinct, _count, clustered,
     name, offset, base, lists) = block
    say(f"  {name} +{offset:#06x} holds it, which puts that file at "
        f"${base:04X} ({clustered} of {namespace} handler pages clustered)")

    if flags_tail(lists):
        say(f"  the last decoded list is the flags table that follows: "
            f"{len(lists[-1])} bytes over {len(set(lists[-1]))} values")
        lists = lists[:-1]

    say()
    for i, one in enumerate(lists):
        shown = " ".join(f"{v:3d}" for v in one) or "(empty)"
        say(f"    list {i:>2}  {shown}")
    ids = {v for one in lists for v in one}
    total = sum(len(one) for one in lists)
    say(f"\n  {len(lists)} lists, {total} ids, {len(ids)} distinct")

    extra = sorted(literal - ids)
    both = ids | literal
    say(f"  the literal census adds {len(extra)}: "
        + ", ".join(str(v) for v in extra))
    say(f"  {len(both)} ids reach the trait slots in all")
    table = traits.for_game(game.key)
    named = sorted(v for v in both if v in table)
    say(f"  {len(named)} of them have a name in this title's own table: "
        + ", ".join(str(v) for v in named))
    return 0, lists, both


def describe(game: c64_port.C64Container, code: int) -> str:
    return traits.describe(code, game.key)


# ---------------------------------------------------------------------------
# Route 1: the same id in the same numbered check list in two titles
# ---------------------------------------------------------------------------
# The walker takes a list *number*, so list 12 is "target, saving throw" in
# whichever title is running and an id on it is being asked the same question
# about the same thing. That makes an id sitting in the same numbered list in
# two titles evidence that it means the same thing in both, which is what
# `--compare` counts. It is **positional agreement and not a read of the
# handler**, so what it earns is PROBABLE.
#
# `#497` measured how far that carries, and the answer is per id rather than
# per title: 29 of the 32 ids below 64 that are on a list in both Pool of
# Radiance and Silver Blades sit in the same numbered list, and 0 of the 7
# above 100 do.


def title_named(name: str) -> c64_port.C64Container:
    game = next((g for g in c64_port.GAMES
                 if g.key == name or g.title == name), None)
    if game is None:
        raise SystemExit(f"No such title: {name}")
    return game


def disks_for(game: c64_port.C64Container, given: str | None = None) -> str:
    root = given or str(gamedisks.find(game.key) or "")
    if not root or not os.path.isdir(root):
        raise SystemExit(f"No disks for {game.title}; pass --disks.")
    return root


def predicate_for(root: str, game: c64_port.C64Container,
                  overlay: str = "LIBRARY") -> Predicate:
    record = staging(game)
    for _disk, name, body in files(root, game):
        if overlay and name != overlay:
            continue
        found = find_predicate(name, body, record)
        if found is not None:
            return found
    raise SystemExit(
        f"traitquery.py: no array-then-traits predicate in "
        f"{overlay} for {game.title}; try --overlay.")


def literal_ids(root: str, game: c64_port.C64Container,
                predicate: Predicate) -> set[int]:
    """Every id an instruction names at the array-then-traits entry.

    The same census `main` prints, with 0 and the fill byte dropped, so a
    caller that only wants the numbers does not have to print the rows.
    """
    out: set[int] = set()
    for _name, _off, _kind, ids in call_sites(root, game, predicate.entry):
        if len(ids) == 1:
            out |= ids
    out.discard(0)
    return {v for v in out if v != 0xFF}


def membership(lists: list[list[int]]) -> dict[int, set[int]]:
    """Which numbered lists each id is on."""
    out: dict[int, set[int]] = collections.defaultdict(set)
    for number, one in enumerate(lists):
        for value in one:
            out[value].add(number)
    return out


def measure(root: str, game: c64_port.C64Container, overlay: str = "LIBRARY"):
    """`(lists, honoured)` for one title, with nothing printed."""
    predicate = predicate_for(root, game, overlay)
    literal = literal_ids(root, game, predicate)
    status, lists, both = report_lists(root, game, predicate.entry, literal,
                                       show=False)
    if status:
        raise SystemExit(f"traitquery.py: could not read {game.title}'s "
                         f"check lists; run it with --lists to see why.")
    return lists, both


def report_compare(game: c64_port.C64Container, root: str,
                   other: c64_port.C64Container, other_root: str,
                   overlay: str = "LIBRARY") -> int:
    """One row per id the first title honours, and where the second puts it."""
    lists, honoured = measure(root, game, overlay)
    other_lists, other_honoured = measure(other_root, other, overlay)
    mine, theirs = membership(lists), membership(other_lists)
    table = traits.for_game(other.key)

    agree: list[int] = []
    contradict = absent = 0
    print(f"{game.title} against {other.title}: {len(honoured)} ids honoured "
          f"here, {len(other_honoured)} there\n")
    print(f"{'id':>4}  {'here':<14} {'there':<14} {'':<12} "
          f"the other table's name")
    for value in sorted(honoured):
        here, there = sorted(mine.get(value, ())), sorted(theirs.get(value, ()))
        name = table.get(value, ("", ""))[0]
        if set(here) & set(there):
            verdict = "same list"
            agree.append(value)
        elif there:
            verdict = "MOVED"
            contradict += 1
        else:
            verdict, name = "not there", ""
            absent += 1
        print(f"{value:>4}  {str(here):<14} {str(there):<14} {verdict:<12} "
              f"{name[:44]}")
    named = [v for v in agree if v in table]
    print(f"\n  {len(agree)} of {len(honoured)} sit in the same numbered list "
          f"in both, {contradict} sit in a different one, {absent} are on no "
          f"list in the other title")
    print(f"  {len(named)} of the agreeing ids have a name in the other "
          f"title's table: " + ", ".join(str(v) for v in named))
    return 0


# ---------------------------------------------------------------------------
# Route 2: the spell that writes the id
# ---------------------------------------------------------------------------
#: Where each title keeps the per-spell record `CAMP` copies when a spell is
#: cast, as `(file, payload offset, record size, effect byte, message byte)`.
#:
#: Pool of Radiance's is already documented -- `goldbox/effects.py` reads the
#: same 469 bytes for their durations, and `docs/50-experiments.md` has
#: `CAMP $1429` computing `$9900 + (id - 1) * 7`. **Its effect byte carries a
#: flag in bit 7** (set on every cleric spell: 1-8, 22-28, 36-44 and 56), so
#: it is masked; the later titles' is a full byte, which they need because
#: their namespaces run past 127.
#:
#: The later two were found by scoring every offset in every file against Pool
#: of Radiance's own sequence of effect ids for the first thirty spells:
#: `COMBAT2 +2732` scores 26 of 30 in Curse and `COMBAT2 +2937` scores 25 of
#: 30 in Silver Blades, and nothing else in either title scores above 18.
SPELL_EFFECTS = {
    "pool-of-radiance": ("ECL65", 0, 7, 3, 4, 0x7F),
    "curse-of-the-azure-bonds": ("COMBAT2", 2732, 9, 0, 1, 0xFF),
    "secret-of-the-silver-blades": ("COMBAT2", 2937, 9, 0, 1, 0xFF),
}


def spell_effects(root: str, game: c64_port.C64Container):
    """`{spell id: (spell name, effect id, the message it prints)}`.

    The message is what pins the record's fields: index 59 is `IS BLESSED` in
    all three titles, and it is reached at `last spell + 1 + index` in the
    same name table `goldbox/spells.py` reads -- 57, 101 and 118, which are
    exactly the three "spells run to" boundaries that module already carries.
    """
    where = SPELL_EFFECTS.get(game.key)
    if where is None:
        raise SystemExit(f"traitquery.py: no spell-effect table is known for "
                         f"{game.title}.")
    name, at, size, effect_at, message_at, mask = where
    body = next((b for _d, n, b in files(root, game) if n == name), None)
    if body is None:
        raise SystemExit(f"traitquery.py: {game.title} ships no {name}.")

    table = spells.for_game(game.key)
    disk = next((p for p in disks(root, game)
                 if _holds(p, table.file)), None)
    if disk is None:
        raise SystemExit(f"traitquery.py: no side carries "
                         f"{table.file.decode()} for {game.title}.")
    text = spells.load_spell_names(disk, game=game.key)

    out = {}
    for spell in range(1, table.last_spell + 1):
        record = at + size * (spell - 1)
        if record + size > len(body):
            break
        effect = body[record + effect_at] & mask
        message = body[record + message_at]
        out[spell] = (text.get(spell, "?"), effect,
                      text.get(table.last_spell + 1 + message, f"msg {message}"))
    return out


def _holds(path: str, name: bytes) -> bool:
    try:
        image = D64.open(path)
    except Exception:
        return False
    return any(entry.name.decode("latin1").rstrip("\xa0 ") == name.decode()
               for entry in image.iter_directory())


def report_spells(root: str, game: c64_port.C64Container,
                  overlay: str = "LIBRARY") -> int:
    """Every effect id one of this title's own spells writes, and which."""
    _lists, honoured = measure(root, game, overlay)
    where = SPELL_EFFECTS[game.key]
    table = spells.for_game(game.key)
    print(f"{game.title}: {where[0]} +{where[1]}, {where[2]} bytes a record, "
          f"{table.last_spell} spells")
    print(f"{'id':>4} {'honoured':<9} spells that write it        message\n")
    by_id: dict[int, list[tuple[str, str]]] = collections.defaultdict(list)
    for _spell, (name, effect, message) in sorted(spell_effects(root,
                                                               game).items()):
        if effect:
            by_id[effect].append((name, message))
    for effect in sorted(by_id):
        rows = by_id[effect]
        names = "; ".join(n for n, _m in rows)
        messages = ", ".join(sorted({m for _n, m in rows}))
        mark = "yes" if effect in honoured else "no"
        print(f"{effect:>4} {mark:<9} {names[:44]:<44} {messages[:30]}")
    print(f"\n  {len(by_id)} ids are written by a spell; "
          f"{len([e for e in by_id if e in honoured])} of them are honoured "
          f"in a trait slot")
    return 0


# ---------------------------------------------------------------------------
# Route 3: the handler the id dispatches
# ---------------------------------------------------------------------------
# The ask dispatches a matched id through the pair of tables `find_dispatch`
# found -- `LDX <scratch> / LDA <low>,X / LDA <high>,X`, so **the table index
# is the id itself** -- and the address it lands on is a routine in the same
# file as the ask, which is `COMBAT` in all three titles. Reading that routine
# is what names an id no spell writes and no creature carries, and it is the
# route `#497` finished Silver Blades with: `docs/171-c64-trait-slots.md` has
# every reading and the anchors (`$A904` is the damage type, `$945F` the
# damage, `$A903` the saving-throw roll, `$7C00` the staged record).
#
# `--handlers` prints each id's address, its file and offset, and the routine
# decoded linearly until a return or jump that no forward branch reaches past.
# A 6502 has no instruction alignment, so the extent is a reading aid rather
# than a proof; `d6502.py`'s own docstring has the caveat.


def dispatch_for(root: str, game: c64_port.C64Container,
                 overlay: str = "LIBRARY") -> Dispatch:
    """The chain from predicate to handler tables, or `SystemExit` saying
    which link is missing."""
    predicate = predicate_for(root, game, overlay)
    literal = literal_ids(root, game, predicate)
    d = find_dispatch(root, game, predicate.entry, literal)
    if isinstance(d, str):
        raise SystemExit(f"traitquery.py: {game.title}:\n{d}")
    return d


def handler_addresses(root: str, game: c64_port.C64Container,
                      overlay: str = "LIBRARY",
                      dispatch: Dispatch | None = None) -> dict[int, int]:
    """`{id: handler address}` for every id in the title's namespace.

    Index 0 is whatever the byte before each table holds and is not an id.
    """
    d = dispatch or dispatch_for(root, game, overlay)
    block = find_block(d.body_map, d.lists_at, d.high_at, d.namespace)
    if block is None:
        raise SystemExit(f"traitquery.py: no file holds {game.title}'s "
                         f"handler tables at ${d.low_at:04X}")
    name, _offset, base = block[4], block[5], block[6]
    body = d.body_map[name]
    low, high = d.low_at - base, d.high_at - base
    return {i: body[low + i] | body[high + i] << 8
            for i in range(d.namespace)}


def handler_extent(root: str, game: c64_port.C64Container, address: int,
                   overlay: str = "LIBRARY", dispatch: Dispatch | None = None,
                   limit: int = 60):
    """`(file, offset, lines)` for the routine at `address`, or None when it
    falls outside the file the ask runs in.

    Decodes forward until an `RTS`, `RTI` or `JMP` that sits past every
    forward branch target seen so far, which is how a handler that skips
    over its own tail with a `BNE` is still read whole.
    """
    d = dispatch or dispatch_for(root, game, overlay)
    where = handler_file(d, address, root, game, overlay)
    if where is None:
        return None
    name, base = where
    body = d.body_map[name]
    out = []
    pc = far = address
    for _ in range(limit):
        i = pc - base
        if i >= len(body):
            break
        op = body[i]
        if op not in d6502.T:
            out.append(f"${pc:04X}  {op:02X}           .byte ${op:02X}")
            pc += 1
            continue
        mn, mode = d6502.T[op]
        size = d6502.SZ[mode]
        raw = body[i:i + size]
        out.append(f"${pc:04X}  {' '.join(f'{x:02X}' for x in raw):<9s}  "
                   f"{d6502.fmt(pc, mn, mode, raw)}")
        if mode == d6502.M_REL:
            step = raw[1] - 256 if raw[1] > 127 else raw[1]
            far = max(far, pc + 2 + step)
        pc += size
        if mn in ("RTS", "RTI", "JMP") and pc > far:
            break
    return name, address - base, out


def handler_file(d: Dispatch, address: int, root: str,
                 game: c64_port.C64Container, overlay: str = "LIBRARY"):
    """`(file, base)` for the overlay a handler address falls in, or None.

    Curse and Silver Blades keep the handlers in the ask's own file, so that
    is tried first. Pool of Radiance keeps them in `SPELLE01` at `$A700`
    (`docs/171-c64-trait-slots.md`), which the ask's file cannot answer for,
    and `SPELLE04` loads at `$A700` as well -- so when more than one other
    file's best-scoring load address covers the table equally well this
    answers None rather than guessing, and `--handlers` prints the
    candidates. `handler_candidates` is the ranking behind that.
    """
    body, base = d.body_map[d.ask_file], d.ask_base
    if base <= address < base + len(body):
        return d.ask_file, base
    covering = [row for row in handler_candidates(d, root, game, overlay)
                if row[3] <= address < row[3] + len(d.body_map[row[2]])]
    if len(covering) == 1 or (
            len(covering) > 1 and covering[0][0] > covering[1][0]):
        return covering[0][2], covering[0][3]
    return None


def handler_candidates(d: Dispatch, root: str, game: c64_port.C64Container,
                       overlay: str = "LIBRARY"):
    """`(covered, score, file, base)` for every file and load address that
    puts at least a quarter of the handler table inside the file, best
    first. Cached on the dispatch, since it costs a scan of every file."""
    cache = getattr(d, "_handler_files", None)
    if cache is None:
        cache = d._handler_files = []
        table = handler_addresses(root, game, overlay, d)
        addresses = {a for c, a in table.items() if c}
        for name, other in sorted(d.body_map.items()):
            if name == d.ask_file:
                continue
            for score, _good, candidate in bases(other)[:3]:
                covered = sum(1 for a in addresses
                              if candidate <= a < candidate + len(other))
                if covered >= len(addresses) // 4:
                    cache.append((covered, score, name, candidate))
        cache.sort(reverse=True)
    return cache


def handler_bytes(root: str, game: c64_port.C64Container, code: int,
                  count: int, overlay: str = "LIBRARY",
                  dispatch: Dispatch | None = None) -> bytes:
    """The first `count` bytes of one id's handler, for a test to pin."""
    d = dispatch or dispatch_for(root, game, overlay)
    address = handler_addresses(root, game, overlay, d)[code]
    body, base = d.body_map[d.ask_file], d.ask_base
    return bytes(body[address - base:address - base + count])


def report_handlers(root: str, game: c64_port.C64Container, codes,
                    overlay: str = "LIBRARY") -> int:
    """One block per id: where its handler is, and what the bytes decode to."""
    d = dispatch_for(root, game, overlay)
    table = handler_addresses(root, game, overlay, d)
    _lists, honoured = measure(root, game, overlay)
    print(f"{game.title}: handler tables ${d.low_at:04X}/${d.high_at:04X}, "
          f"indexed by the id itself; {d.ask_file} runs at ${d.ask_base:04X}")
    wanted = sorted(codes) if codes else sorted(honoured)
    names = traits.for_game(game.key)
    for code in wanted:
        if code not in table:
            print(f"\n{code}: outside the {d.namespace}-id namespace")
            continue
        address = table[code]
        shared = sorted(c for c, a in table.items() if a == address and c)
        head = f"\n{code} -> ${address:04X}"
        if len(shared) > 1:
            head += f"  (shared with {', '.join(str(c) for c in shared if c != code)})"
        if code in names:
            head += f"  {names[code][0]} ({names[code][1]})"
        print(head)
        found = handler_extent(root, game, address, overlay, d)
        if found is None:
            rows = [f"{n} at ${b:04X} ({c} of the table inside)"
                    for c, _s, n, b in handler_candidates(d, root, game,
                                                          overlay)
                    if b <= address < b + len(d.body_map[n])]
            print(f"   outside {d.ask_file}; " + (
                "no other file covers it" if not rows else
                "the files that could hold it score alike: "
                + "; ".join(rows)))
            continue
        name, offset, lines = found
        print(f"   {name} +{offset:#06x}")
        for line in lines:
            print("   " + line)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("title")
    parser.add_argument("--disks", help="where that title's sides are")
    parser.add_argument("--overlay", default="LIBRARY",
                        help="which file to look for the predicate in")
    parser.add_argument("--sites", action="store_true",
                        help="one row per call site, not one per id")
    parser.add_argument("--lists", action="store_true",
                        help="also read the combat check lists off the disks")
    parser.add_argument("--compare", metavar="TITLE",
                        help="which numbered check list each id is on here "
                             "and in TITLE")
    parser.add_argument("--compare-disks",
                        help="where TITLE's sides are")
    parser.add_argument("--spells", action="store_true",
                        help="which effect id each of this title's spells "
                             "writes, read off its own spell-effect table")
    parser.add_argument("--handlers", nargs="*", type=int, metavar="ID",
                        help="disassemble the handler each id dispatches "
                             "(every honoured id when none are given)")
    args = parser.parse_args(argv)

    game = title_named(args.title)
    root = disks_for(game, args.disks)

    if args.compare:
        other = title_named(args.compare)
        return report_compare(game, root, other,
                              disks_for(other, args.compare_disks),
                              args.overlay)
    if args.spells:
        return report_spells(root, game, args.overlay)
    if args.handlers is not None:
        return report_handlers(root, game, args.handlers, args.overlay)

    predicate = predicate_for(root, game, args.overlay)
    record = staging(game)

    print(f"{game.title}: record ${record:04X}, trait block "
          f"${record + TRAIT_SLOT:04X}")
    print(f"  {predicate.file} runs at ${predicate.base:04X} "
          f"(derived, not from the header)")
    print(f"  ${predicate.entry:04X}  array, then the ten trait slots")
    print(f"  ${predicate.array:04X}  array only -- a trait slot is invisible "
          f"here")
    print(f"  ${predicate.trait_scan:04X}  the LDX #$09 scan itself")

    literal: set[int] = set()
    for label, target in (("honours a trait slot", predicate.entry),
                          ("array only", predicate.array),
                          ("array only, current character",
                           predicate.array - 3)):
        sites = list(call_sites(root, game, target))
        if target == predicate.entry:
            for _name, _off, _kind, ids in sites:
                if len(ids) == 1:
                    literal |= ids
        print(f"\n  ${target:04X}, {label}: {len(sites)} call sites")
        if not sites:
            continue
        if args.sites:
            for name, off, kind, ids in sorted(sites):
                shown = ", ".join(str(i) for i in sorted(ids)) or "?"
                print(f"    {name:<10} ${OVERLAY_BASE + off:04X}  {kind}  "
                      f"id {shown}")
            continue
        per: dict[str, list[str]] = collections.defaultdict(list)
        for name, off, _kind, ids in sites:
            key = str(sorted(ids)[0]) if len(ids) == 1 else "?"
            per[key].append(f"{name} ${OVERLAY_BASE + off:04X}")
        for key in sorted(per, key=lambda v: (v == "?", int(v) if v != "?"
                                              else 0)):
            if key == "?":
                print(f"    {'?':>4}  {'(the caller supplies it)':<48} "
                      + ", ".join(sorted(per[key])))
                continue
            print(f"    {key:>4}  {describe(game, int(key))[:48]:<48} "
                  + ", ".join(sorted(per[key])))

    if args.lists:
        literal.discard(0)
        literal = {v for v in literal if v != 0xFF}
        print(f"\n{game.title}: the combat check lists")
        return report_lists(root, game, predicate.entry, literal)[0]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
