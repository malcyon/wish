#!/usr/bin/env python3
"""Read one title's per-title tables off its own disks, with no emulator.

Six C64 Gold Box titles share one engine, and everything this project knows
about the later ones was established by asking the same four questions of each:
where does `GEN` seed a character's racial traits from, what does it cap a
class at, what does it charge for a level, and where does the save keep the
running spell effects. Each answer is a table at an address that moves between
titles, so each was found the same way -- by the *instruction* that reads it,
which does not move.

    tools/coldread.py traits secret-of-the-silver-blades
    tools/coldread.py levels curse-of-the-azure-bonds
    tools/coldread.py effects secret-of-the-silver-blades
    tools/coldread.py table secret-of-the-silver-blades 0x17D0 8

Written for `#31 (Cold-read Curse and Silver Blades for the fields the editor
shows)`, whose whole point is that these answers are on disks this project
already opens. The patterns are the reusable part: run any of them against
Champions of Krynn, Death Knights of Krynn or Gateway to the Savage Frontier
and they will either find that title's tables or say plainly that they did not.

**`GEN` runs at `$0800` and its PRG header lies** -- it claims `$1000` in Pool
of Radiance, `$1220` in Curse and `$4000` in Silver Blades. `$0800` is where
`LINKER` puts an overlay it calls, and the table addresses inside the file only
land on their own bytes at that base. `--base` is there for a title where that
turns out not to hold.

Nothing here writes, and nothing it prints is committed: the tables stay on the
player's own disks.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from automap.paths import disk_globs, find_disks  # noqa: E402
from goldbox import games  # noqa: E402
from goldbox.d64 import D64  # noqa: E402

#: Where `LINKER` loads an overlay it dispatches to.
GEN_BASE = 0x0800

#: The record staging page each title reads and writes a character through.
#: Pool of Radiance's is `$6B00`; every later title moved it to `$7C00` along
#: with the save image. Every pattern below is anchored on a byte of it, which
#: is what makes the patterns survive the move.
STAGING = {"pool-of-radiance": 0x6B00}
STAGING_LATER = 0x7C00

#: Record offsets the patterns anchor on -- `goldbox/layout.py` names them all.
RACE = 0x072            # the race byte a seed table is indexed by
TRAIT_SLOT = 0x0AD      # the first of the ten trait slots
LEVEL_ARRAY = 0x0C9     # eight per-class levels, in class-bit order
FIGHTING_LEVEL = 0x098  # the best of the fighter-group levels
THAC0 = 0x071           # stored biased, `60 - THAC0`

#: The four effect arrays, as payload offsets. They are inside the save image,
#: so they follow `save_load_address` and are not per-title numbers -- which is
#: the claim `effects` below is for.
EFFECT_ARRAYS = (("id", 0x000), ("owner", 0x040),
                 ("duration", 0x080), ("magnitude", 0x280))
EFFECT_SLOTS = 0x40

#: Absolute-addressing opcodes worth naming when one lands on an array.
OPCODES = {0xAD: "LDA", 0x8D: "STA", 0xBD: "LDA ,X", 0x9D: "STA ,X",
           0xB9: "LDA ,Y", 0x99: "STA ,Y", 0xDD: "CMP ,X", 0xD9: "CMP ,Y",
           0xBE: "LDX ,Y", 0xBC: "LDY ,X", 0x1D: "ORA ,X",
           0xFE: "INC ,X", 0xDE: "DEC ,X"}


def staging(game: games.Game) -> int:
    return STAGING.get(game.key, STAGING_LATER)


# --- getting at the bytes ----------------------------------------------------

def disks(game: games.Game, root: str | None) -> list[D64]:
    """Every readable side of this title's, from `root` or wherever it lives."""
    where = pathlib.Path(root) if root else find_disks(game)
    if where is None:
        raise SystemExit(
            f"No {game.title} disks. Set $POR_DISKS or pass --disks.")
    seen: dict[str, pathlib.Path] = {}
    for pattern in disk_globs(game):
        for path in sorted(where.glob(pattern)):
            seen.setdefault(os.path.normcase(str(path)), path)
    out = []
    for path in sorted(seen.values()):
        try:
            out.append(D64.open(str(path)))
        except Exception as exc:                  # one bad side is not the end
            print(f"  ({path.name}: {exc})", file=sys.stderr)
    if not out:
        raise SystemExit(f"No readable {game.title} side under {where}.")
    return out


def overlay(game: games.Game, name: bytes, root: str | None) -> bytes:
    """One overlay's payload, longest copy across the sides.

    Longest because the sides disagree: a truncated demo copy of a file is a
    real thing on these disks and taking the first match gets it.
    """
    best = None
    for image in disks(game, root):
        entry = image.find(name)
        if entry is None:
            continue
        try:
            data = image.read_file(entry)
        except Exception:
            continue                              # a broken chain is not a copy
        if best is None or len(data) > len(best):
            best = data
    if best is None:
        raise SystemExit(f"No {name.decode()} on any {game.title} side.")
    return best[2:]


def every_file(game: games.Game, root: str | None) -> dict[str, bytes]:
    """Every distinct file on the title's sides, by name, payload only."""
    out: dict[str, bytes] = {}
    for image in disks(game, root):
        for entry in image.directory():
            name = bytes(entry.name).decode("latin1").rstrip()
            if name in out:
                continue
            try:
                out[name] = image.read_file(entry)[2:]
            except Exception:
                continue
    return out


def sites(body: bytes, pattern: bytes, base: int) -> list[int]:
    """Every run-time address at which `pattern` appears."""
    out, at = [], body.find(pattern)
    while at >= 0:
        out.append(at + base)
        at = body.find(pattern, at + 1)
    return out


def word(body: bytes, base: int, address: int) -> int:
    at = address - base
    return body[at] | body[at + 1] << 8


def table(body: bytes, base: int, address: int, count: int) -> list[int]:
    at = address - base
    if not 0 <= at <= len(body) - count:
        raise SystemExit(f"${address:04X} is outside a {len(body)}-byte "
                         f"overlay at ${base:04X}.")
    return list(body[at:at + count])


# --- the four questions ------------------------------------------------------

def trait_seeds(gen: bytes, game: games.Game, base: int
                ) -> tuple[int | None, list[int]]:
    """Where `GEN` seeds the trait slots from, found by the read that does it.

    The shape is the same in all three measured titles and the *number of
    seeded slots is not*: `LDX <record race> / LDA <table>,X / STA <slot>` once
    in Pool of Radiance, three times in Curse, twice in Silver Blades. So the
    tables are counted rather than assumed, which is the whole reason this is a
    pattern and not a constant.

    Returns `(the address of the LDX, one table address per seeded slot)`.
    """
    page = staging(game) >> 8
    anchor = bytes([0xAE, RACE, page])            # LDX <staging>+0x072
    found = sites(gen, anchor, base)
    for start in found:
        at, tables = start - base + 3, []
        while (gen[at] == 0xBD and gen[at + 3] == 0x8D
               and gen[at + 5] == page
               and gen[at + 4] == (TRAIT_SLOT + len(tables)) & 0xFF):
            tables.append(gen[at + 1] | gen[at + 2] << 8)
            at += 6
        if tables:
            return start, tables
    return None, []


def class_seeds(gen: bytes, game: games.Game, base: int) -> list[tuple[str, int]]:
    """The trait a paladin or a ranger is given for its class.

    `LDA <paladin level> / BEQ over / … / LDA #code / …` -- the code is an
    immediate operand, so it reads straight out without a table. What follows
    it differs: Curse stores it into a slot the previous call found
    (`STA <staging>+0x0AD,X`) and Silver Blades passes it to a subroutine that
    finds the slot itself, so the immediate is taken as **the last one inside
    the branch's own reach** rather than by matching what comes after it.

    The branch's displacement is the window, which is why nothing here needs a
    guessed byte count: the code between `BEQ` and its target is exactly the
    code that runs when the character has that class.
    """
    page = staging(game) >> 8
    out = []
    for name, offset in (("paladin", 0x0CF), ("ranger", 0x0D0)):
        for at in sites(gen, bytes([0xAD, offset, page]), base):
            head = at - base
            if gen[head + 3] != 0xF0:             # BEQ: no class, no trait
                continue
            window = gen[head + 5:head + 5 + gen[head + 4]]
            found = [window[i + 1] for i in range(len(window) - 1)
                     if window[i] == 0xA9]
            if found and found[-1]:
                out.append((name, found[-1]))
                break
    return out


def class_ceilings(gen: bytes, game: games.Game, base: int) -> int | None:
    """The per-class level cap, found beside the array it caps.

    `LDA <record 0x0C9>,X / CMP <table>,X` ties the table to the exact eight
    bytes an editor would write. Pool of Radiance does not use this shape and
    is answered None rather than guessed at.

    **`BCS` is the discriminator and it is not decoration.** Three sites in
    Silver Blades' `GEN` compare the level array against a table and only one
    of them is the ceiling: the other two band the level for an attacks-per-
    round lookup and branch `BCC`. Taking the first match reads
    `[99, 99, 99, 7, 7, 99, 7, 8]` -- the attack bands -- as class ceilings,
    which is a plausible-looking answer and a wrong one.
    """
    page = staging(game) >> 8
    anchor = bytes([0xBD, LEVEL_ARRAY, page, 0xDD])
    for at in sites(gen, anchor, base):
        if gen[at - base + 6] == 0xB0:            # BCS: at the cap, refuse
            return word(gen, base, at + 4)
    return None


def racial_limits(gen: bytes, game: games.Game, base: int
                  ) -> tuple[int | None, int | None]:
    """The per-race class limit rows, eight bytes a race, and how many rows.

    `LDX <record race> / DEX / TXA / ASL / ASL / ASL` is the `(race - 1) * 8`
    that makes the row; the table is the first `LDA abs,X` after it.

    The row count comes from the routine's own guard -- `LDA <record race> /
    CMP #n / BCS` a few instructions earlier, which is how a title says "this
    race has no limit and does not index the table". Curse guards at 7 and
    Silver Blades at 6, and in each the table stops one row short of it. Past
    that the bytes are whatever follows, and reading them as a race's limits is
    exactly the wrong-data-that-looks-right this whole file exists to avoid.
    """
    page = staging(game) >> 8
    anchor = bytes([0xAE, RACE, page, 0xCA, 0x8A, 0x0A, 0x0A, 0x0A])
    for at in sites(gen, anchor, base):
        window = gen[at - base:at - base + 24]
        for i in range(8, len(window) - 2):
            if window[i] == 0xBD:
                return window[i + 1] | window[i + 2] << 8, _guard(gen, game,
                                                                  base)
    return None, None


def _guard(gen: bytes, game: games.Game, base: int) -> int | None:
    """The race the limit check gives up at: `LDA <race> / CMP #n / BCS`."""
    page = staging(game) >> 8
    for at in sites(gen, bytes([0xAD, RACE, page, 0xC9]), base):
        if gen[at - base + 5] == 0xB0:
            return gen[at - base + 4]
    return None


def fighter_thac0_is_computed(gen: bytes, game: games.Game, base: int) -> bool:
    """Does this title compute the fighter group's THAC0 instead of tabulating?

    `LDA <fighting level> / CLC / ADC #$27 / STA <THAC0>` is `THAC0 = 21 -
    level`, since the byte is stored `60 - THAC0`.
    """
    page = staging(game) >> 8
    return bool(sites(gen, bytes([0xAD, FIGHTING_LEVEL, page, 0x18, 0x69, 0x27,
                                  0x8D, THAC0, page]), base))


def effect_users(game: games.Game, root: str | None) -> dict[str, list[str]]:
    """Which overlays touch each effect array, at this title's own base.

    The array addresses are `save_load_address` plus a payload offset, so this
    says whether the later titles keep the arrays where Pool of Radiance does
    -- and it says it from the game's own instructions rather than from a save
    full of zeroes, which is all a shipped party can offer.

    **A hit in a data file is a coincidence, not a reference.** This is a byte
    scan: any file holding the array's two address bytes after a byte that
    happens to be an opcode is reported, and Silver Blades' `ITEM37` is exactly
    that. The evidence is the overlays -- `CAMP`, `COMBAT`, `DUNGEON`,
    `LIBRARY`, `POST.COM` -- appearing on the same array in every title.
    """
    files = every_file(game, root)
    out: dict[str, list[str]] = {}
    for label, offset in EFFECT_ARRAYS:
        address = game.save_load_address + offset
        want = bytes([address & 0xFF, address >> 8])
        hits = []
        for name, body in sorted(files.items()):
            at, seen = body.find(want), set()
            while at >= 0:
                if at and body[at - 1] in OPCODES:
                    seen.add(OPCODES[body[at - 1]])
                at = body.find(want, at + 1)
            if seen:
                hits.append(f"{name} ({', '.join(sorted(seen))})")
        out[f"{label} ${address:04X}"] = hits
    return out


# --- printing ----------------------------------------------------------------

def show_traits(game, gen, base, root) -> None:
    where, tables = trait_seeds(gen, game, base)
    if where is None:
        print(f"{game.title}: no race-indexed trait seed found in GEN.")
        return
    print(f"{game.title}: GEN ${where:04X} seeds {len(tables)} trait slot"
          f"{'' if len(tables) == 1 else 's'} from "
          + ", ".join(f"${a:04X}" for a in tables))
    names = dict(game.races or ())
    for code in sorted(names):
        row = [table(gen, base, a, code + 1)[code] for a in tables]
        if any(row):
            print(f"   race {code} {names[code]:10s} -> "
                  + " ".join(str(v) for v in row if v))
    for name, code in class_seeds(gen, game, base):
        print(f"   class {name:10s} -> {code}")


def show_levels(game, gen, base, root) -> None:
    caps = class_ceilings(gen, game, base)
    limits, guard = racial_limits(gen, game, base)
    print(f"{game.title}:")
    if caps is None:
        print("   class ceilings: not found by the read beside the level array")
    else:
        print(f"   class ceilings  ${caps:04X}  {table(gen, base, caps, 8)}")
    if limits is None:
        print("   racial limits: not found by the (race - 1) * 8 index")
    else:
        names = dict(game.races or ())
        print(f"   racial limits   ${limits:04X}, rows for races 1-"
              f"{guard - 1 if guard else '?'} "
              f"(race {guard} and above skip the check)")
        for code in sorted(names):
            if guard is not None and not 1 <= code < guard:
                continue
            print(f"      race {code} {names[code]:10s} "
                  f"{table(gen, base, limits + (code - 1) * 8, 8)}")
    print("   fighter THAC0 computed as 21 - fighting level: "
          f"{fighter_thac0_is_computed(gen, game, base)}")


def show_effects(game, gen, base, root) -> None:
    print(f"{game.title}: the four effect arrays, {EFFECT_SLOTS} slots each, "
          f"at ${game.save_load_address:04X} + offset")
    for label, users in effect_users(game, root).items():
        print(f"   {label}: " + (", ".join(users) if users else "nothing"))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Read a title's own tables off its own disks.")
    ap.add_argument("what", choices=("traits", "levels", "effects", "table"))
    ap.add_argument("title", help="a key from goldbox.games, e.g. "
                                  "curse-of-the-azure-bonds")
    ap.add_argument("address", nargs="?", help="table: the run-time address")
    ap.add_argument("count", nargs="?", type=int, default=8,
                    help="table: how many bytes (default: %(default)s)")
    ap.add_argument("--base", default=hex(GEN_BASE), metavar="ADDR",
                    help="where GEN runs (default: %(default)s -- its PRG "
                         "header claims three different things and is wrong "
                         "in all three titles)")
    ap.add_argument("--disks", default=None, metavar="DIR",
                    help="where this title's disks are")
    args = ap.parse_args(argv[1:])

    game = games.by_key(args.title)
    base = int(args.base, 0)
    gen = overlay(game, b"GEN", args.disks)

    if args.what == "table":
        if args.address is None:
            print("table wants an address.", file=sys.stderr)
            return 2
        at = int(args.address, 0)
        print(f"${at:04X}: " + " ".join(str(v) for v in
                                        table(gen, base, at, args.count)))
        return 0

    {"traits": show_traits, "levels": show_levels,
     "effects": show_effects}[args.what](game, gen, base, args.disks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
