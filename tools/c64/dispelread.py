#!/usr/bin/env python3
"""Whether each C64 title's Dispel Magic can remove an effect held in a trait slot.

    tools/c64/dispelread.py                          # all three titles
    tools/c64/dispelread.py curse-of-the-azure-bonds

A C64 character keeps an effect in two places: the 64-entry active-effect
array in the save header, and the ten trait slots at record `0x0AD`, which
never expire (`docs/171-c64-trait-slots.md`).  LIBRARY has two predicates over
them -- one asks the array only, the other the array and then the ten slots.
A trait-slot effect converted to a DOS node is dispellable there unless its
value byte is `0xFF` (`docs/230-who-reads-a-dos-effect-node.md`), so which
predicate the C64 Dispel Magic asks decides which DOS value byte is faithful.

This reads the routine each title's own spell table sends both DISPEL MAGIC
spells to, and reports:

* the **ids it tries** -- Pool of Radiance counts ids 63 down to 1 in X,
  the later titles index an id list in `COMBAT2`;
* the **predicate** it asks for each id, classified against
  `tools/c64/traitquery.py`'s own reading of LIBRARY: array only, or array
  then trait slots;
* the **level test**: a magnitude of `0xFF` is skipped, otherwise its low
  nibble is the effect's level, and the chance routine's constants give the
  percentage against the caster's level;
* the **removal** it calls, and which predicate that asks in turn;
* every **absolute reference to the trait block** in the routine, the chance
  routine and the removal routine.

Nothing here needs an emulator or writes anything: it reads the overlays off
the player's own disks through `automap/gamedisks.py`, and prints addresses
and verdicts only.
"""

from __future__ import annotations

import argparse
import dataclasses
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from goldbox import c64_port, spells  # noqa: E402
from tools.c64 import d6502, traitquery  # noqa: E402
from tools.c64.absrefsweep import files  # noqa: E402


@dataclasses.dataclass(frozen=True)
class Route:
    """Where one title keeps a per-spell routine address, and which overlay
    runs the routines it names.

    `table` is `(file, offset of spell 1's record, record size, offset of the
    routine address in a record)`.  `candidates` are the overlays that load at
    `base`; the one whose bytes at the routine address decode as a dispel is
    the file that runs it, and the report says which.
    """

    name: str
    table: tuple[str, int, int, int]
    candidates: tuple[str, ...]
    base: int


#: Pool of Radiance keeps two tables: the combat one in `SPELLE65` (nine bytes
#: a record, the routine at +7) and the camp one in `ECL65`, whose seven-byte
#: records `tools/c64/traitquery.py --spells` reads the effect id out of (the
#: routine at +5).  The later titles keep one nine-byte table in `COMBAT2`,
#: the routine at +2.  Each was located by the two DISPEL MAGIC records
#: holding the same address five records apart.
ROUTES = {
    "pool-of-radiance": (
        Route("combat", ("SPELLE65", 0x211, 9, 7),
              ("SPELLE00", "SPELLE01", "SPELLE02", "SPELLE04"), 0xA700),
        Route("camp", ("ECL65", 0, 7, 5),
              ("SPELLE00", "SPELLE01", "SPELLE02", "SPELLE04"), 0xA700),
    ),
    "curse-of-the-azure-bonds": (
        Route("combat", ("COMBAT2", 2732, 9, 2), ("COMBAT",), 0x0800),
    ),
    "secret-of-the-silver-blades": (
        Route("combat", ("COMBAT2", 2937, 9, 2), ("COMBAT",), 0x0800),
    ),
}

#: Where `COMBAT2` runs in the later titles (`goldbox/spells.py`), for the id
#: list the dispel loop indexes.
COMBAT2_BASE = 0xE000


@dataclasses.dataclass
class Insn:
    pc: int
    mnemonic: str
    mode: int
    operand: int | None     # the absolute address, immediate, or branch target
    size: int


def decode(body: bytes, base: int, pc: int) -> Insn | None:
    at = pc - base
    if not 0 <= at < len(body) or body[at] not in d6502.T:
        return None
    mnemonic, mode = d6502.T[body[at]]
    size = d6502.SZ[mode]
    raw = body[at:at + size]
    if len(raw) < size:
        return None
    operand = None
    if size == 3:
        operand = raw[1] | raw[2] << 8
    elif mode == d6502.M_REL:
        operand = (pc + 2 + (raw[1] - 256 if raw[1] > 127 else raw[1])) & 0xFFFF
    elif size == 2:
        operand = raw[1]
    return Insn(pc, mnemonic, mode, operand, size)


def routine(body: bytes, base: int, entry: int, limit: int = 160) -> list[Insn]:
    """Linear decode from `entry` to the first `RTS` no earlier branch jumps past."""
    out: list[Insn] = []
    reach = entry
    pc = entry
    for _ in range(limit):
        insn = decode(body, base, pc)
        if insn is None:
            break
        out.append(insn)
        if insn.mode == d6502.M_REL and insn.operand > reach:
            reach = insn.operand
        if insn.mnemonic in ("RTS", "JMP") and pc >= reach:
            break
        pc += insn.size
    return out


@dataclasses.dataclass
class Dispel:
    title: str
    route: str
    spells: dict                  # spell id -> name, every DISPEL MAGIC
    file: str
    entry: int
    ids: list                     # the effect ids the loop asks about
    skipped_index_zero: int | None  # the list's index 0, which the loop never reads
    predicate: int
    predicate_kind: str           # "array only" | "array then trait slots"
    magnitude: int                # the array the level test reads
    skip: int                     # the magnitude value passed over
    level_mask: int
    chance: int
    chance_base: int
    per_level_above: int
    per_level_below: int
    caster_level: int             # where the caster's level is read from
    removal: int
    removal_asks: list            # (address, kind) of each predicate the removal calls
    trait_refs: list              # addresses in the three routines naming the trait block


def _bodies(root: str, game: c64_port.C64Container) -> dict[str, bytes]:
    return {name: body for _disk, name, body in files(root, game)}


def dispel_spells(root: str, game: c64_port.C64Container) -> dict[int, str]:
    table = spells.for_game(game.key)
    disk = next(p for p in traitquery.disks(root, game)
                if traitquery._holds(p, table.file))
    text = spells.load_spell_names(disk, game=game.key)
    return {s: text[s] for s in range(1, table.last_spell + 1)
            if text.get(s, "").strip().upper() == "DISPEL MAGIC"}


def _kind(address: int, pred: traitquery.Predicate, body: bytes,
          base: int) -> str:
    """Name a predicate call target against LIBRARY's two routines.

    A target three bytes before either is its `LDX <character> / ...` wrapper
    if those three bytes are an absolute `LDX`.
    """
    for target, kind in ((pred.array, "array only"),
                         (pred.entry, "array then trait slots")):
        if address == target:
            return kind
        at = address - base
        if address == target - 3 and 0 <= at < len(body) and body[at] == 0xAE:
            return kind
    return "other"


def read_route(root: str, game: c64_port.C64Container, route: Route,
               bodies: dict[str, bytes] | None = None) -> Dispel:
    bodies = _bodies(root, game) if bodies is None else bodies
    pred = traitquery.predicate_for(root, game)
    library = bodies[pred.file]
    names = dispel_spells(root, game)
    tfile, first, size, at = route.table
    tbody = bodies[tfile]
    entries = {s: tbody[first + size * (s - 1) + at]
               | tbody[first + size * (s - 1) + at + 1] << 8 for s in names}
    if len(set(entries.values())) != 1:
        raise ValueError(f"{game.title} {route.name}: the DISPEL MAGIC spells "
                         f"name different routines {entries}")
    entry = next(iter(entries.values()))

    found = [d for d in (_read_routine(game, route, c, bodies[c], entry, pred,
                                       library, bodies)
                         for c in route.candidates if c in bodies) if d is not None]
    if len(found) != 1:
        raise ValueError(f"{game.title} {route.name}: {len(found)} overlays in "
                         f"{route.candidates} decode a dispel at ${entry:04X}")
    found[0].spells = names
    return found[0]


def _read_routine(game, route, name, body, entry, pred, library, bodies):
    base = route.base
    ins = routine(body, base, entry)
    # the level test: JSR pred / BCC / LDA mag,X / CMP #$FF / BEQ / AND #$0F / JSR chance
    for k in range(len(ins) - 6):
        a, b, c, d, e, f, g = ins[k:k + 7]
        if (a.mnemonic, b.mnemonic, c.mnemonic, d.mnemonic, e.mnemonic,
                f.mnemonic, g.mnemonic) == ("JSR", "BCC", "LDA", "CMP", "BEQ",
                                            "AND", "JSR") \
                and c.mode == d6502.M_ABX and d.mode == d6502.M_IMM \
                and f.mode == d6502.M_IMM:
            break
    else:
        return None
    predicate, magnitude, skip, mask, chance = (a.operand, c.operand, d.operand,
                                                f.operand, g.operand)
    # the loop head: LDX #n, then either TXA (the id is X) or LDA list,X
    ids: list[int] = []
    index_zero = None
    head = ins[:k]
    count = next((i.operand for i in reversed(head) if i.mnemonic == "LDX"
                  and i.mode == d6502.M_IMM), None)
    source = next((i for i in reversed(head) if i.mnemonic in ("TXA", "LDA")),
                  None)
    if count is None or source is None:
        return None
    if source.mnemonic == "TXA":
        ids = list(range(count, 0, -1))
    elif source.mode == d6502.M_ABX:
        lst = bodies["COMBAT2"]
        off = source.operand - COMBAT2_BASE
        ids = [lst[off + x] for x in range(count, 0, -1)]
        index_zero = lst[off]
    else:
        return None

    cins = routine(body, base, chance)
    sbc = next(i for i in cins if i.mnemonic == "SBC" and i.mode == d6502.M_ABS)
    lda = next(i for i in cins if i.mnemonic == "LDA" and i.mode == d6502.M_IMM)
    adc = next(i for i in cins if i.mnemonic == "ADC" and i.mode == d6502.M_IMM)
    sub = next(i for i in cins if i.mnemonic == "SBC" and i.mode == d6502.M_IMM)

    # the removal: the next JSR after the chance test
    tail = ins[k + 7:]
    removal = next(i.operand for i in tail if i.mnemonic == "JSR")
    rins = routine(body, base, removal) if base <= removal < base + len(body) \
        else []
    asks = [(i.operand, _kind(i.operand, pred, library, pred.base))
            for i in rins if i.mnemonic in ("JSR", "JMP")
            and _kind(i.operand, pred, library, pred.base) != "other"]
    if not rins:
        # Pool of Radiance's camp form hands the array index the predicate
        # left to the expiry routine itself; it has no search of its own.
        asks = [(predicate, "the index the loop's own predicate returned")]

    block = traitquery.staging(game) + traitquery.TRAIT_SLOT
    window = range(block, block + 10)
    refs = sorted({i.pc for i in ins + cins + rins
                   if i.size == 3 and i.mnemonic not in ("JSR", "JMP")
                   and i.operand in window})
    return Dispel(game.key, route.name, {}, name, entry, ids, index_zero,
                  predicate, _kind(predicate, pred, library, pred.base),
                  magnitude, skip, mask, chance, lda.operand, adc.operand,
                  sub.operand, sbc.operand, removal, asks, refs)


def read(root: str, game: c64_port.C64Container) -> list[Dispel]:
    bodies = _bodies(root, game)
    return [read_route(root, game, r, bodies) for r in ROUTES[game.key]]


def report(d: Dispel) -> str:
    spells_text = ", ".join(f"{s} {n}" for s, n in sorted(d.spells.items()))
    ids = (f"ids {d.ids[0]} down to {d.ids[-1]}" if d.ids == list(
        range(d.ids[0], 0, -1)) else f"{len(d.ids)} ids {sorted(d.ids)}")
    lines = [
        f"  {d.route}: {spells_text} -> {d.file} ${d.entry:04X}",
        f"    tries {ids}"
        + (f"; the list's index 0 ({d.skipped_index_zero}) is never read"
           if d.skipped_index_zero is not None else ""),
        f"    asks ${d.predicate:04X}: {d.predicate_kind}",
        f"    skips magnitude ${d.skip:02X} at ${d.magnitude:04X},X; level = "
        f"magnitude & ${d.level_mask:02X}",
        f"    chance ${d.chance:04X}: {d.chance_base}% + {d.per_level_above}% "
        f"a level the caster (${d.caster_level:04X}) is above, - "
        f"{d.per_level_below}% a level below",
        f"    removes through ${d.removal:04X}, which asks "
        + (", ".join(f"${a:04X} ({k})" for a, k in d.removal_asks) or "nothing"),
        "    references to the trait block: "
        + (", ".join(f"${a:04X}" for a in d.trait_refs) or "none"),
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("title", nargs="*", default=list(ROUTES))
    parser.add_argument("--disks", help="where that title's sides are")
    args = parser.parse_args(argv)
    for key in args.title:
        game = traitquery.title_named(key)
        root = traitquery.disks_for(game, args.disks)
        print(f"{game.title}:")
        for d in read(root, game):
            print(report(d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
