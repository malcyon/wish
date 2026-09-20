#!/usr/bin/env python3
"""Read the Amiga *Pools of Darkness* saved game through its own save routine.

`/Pools of Darkness` on disk 1 writes `Save/SavGam<L>.pty` as a straight run of
`write(fd, buf, len)` calls, and its loader reads the same sequence back.  The
callbacks are at file offsets `0x270E0` (save) and `0x26904` (load), and every
region below is one of their calls:

    1024  the byte-wide ECL variable array, from `[g57ac] + 1`
       6  the square struct `g5f20`: x, y, facing, wall type, attribute, pad
       1  `g743c`, the mode the party was in before this one
       1  `g5b12`, the game mode -- 2 in every save, because a save is camped
       2  `g5f2c`, the dungeon map the loader passes to `LoadMap`
       2  `g5f2e`, that loader's second argument
       2  the party count, `u16be`
     ...  that many characters, each a `.pc` payload: a 404-byte record, its
          item nodes twenty bytes each, then its effect nodes ten bytes each
     ...  padding to a fixed 10,828 bytes, from the item template table

Nothing reads the padding, and the loader stops at the last character.

    tools/amiga/podsavegame.py                  # every slot on the player's disks
    tools/amiga/podsavegame.py --check          # exit 1 if one does not parse
    tools/amiga/podsavegame.py --vars           # variables the engine names
    tools/amiga/podsavegame.py --vault          # the `Vault<L>.DAT` beside it

The disk images are opened read-only and nothing is written anywhere.  `--vars`
needs `capstone`; the rest does not.  See `docs/124-amiga-port.md` §1.20.
"""
from __future__ import annotations

import argparse
import collections
import dataclasses
import pathlib
import re
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from goldbox import dos_savegame  # noqa: E402
from goldbox.amiga_adf import AmigaDisk, AmigaDiskError  # noqa: E402
from tools.amiga import amiga68k, amigasaves  # noqa: E402

#: Every slot is padded to this length, whatever the party costs.  The save
#: callback ends `lseek(fd, 0, 1)` and, when the position is short of it,
#: writes the difference from the item template table (`0x27234`-`0x2726E`).
SAVEGAME_SIZE = 0x2A4C

#: One byte per ECL variable, variable *N* at file offset *N* - 1 -- the same
#: numbering `goldbox.dos_savegame.pod_var` reads on DOS.  The save writes the
#: region from `[g57ac] + 1`, so an Amiga block displacement *d* is variable
#: *d* and file offset *d* - 1.
VAR_BYTES = dos_savegame.POD_VAR_COUNT

#: The square struct's six bytes, in write order.  DOS writes five of them --
#: it has no pad -- and every other name and its order is the same.
SQUARE = ("x", "y", "facing", "wall_ahead", "square_property", "pad")
SQUARE_AT = VAR_BYTES
PREVIOUS_MODE_AT = SQUARE_AT + len(SQUARE)
MODE_AT = PREVIOUS_MODE_AT + 1
MAP_AT = MODE_AT + 1
MAP_BLOCK_AT = MAP_AT + 2
COUNT_AT = MAP_BLOCK_AT + 2
PARTY_AT = COUNT_AT + 2

#: The engine's own cap on the party: the save's write loop and the loader's
#: read loop both stop at eight (`0x271CE`, `0x2720A`).
PARTY_MAX = 8

RECORD_BYTES = 0x194
ITEM_BYTES = 0x14
EFFECT_BYTES = 0x0A
#: An item whose first byte is this carries sub-items of its own -- the scroll
#: bundle.  Both the writer (`0x263C6`) and the reader (`0x258EA`) branch on
#: it and then walk `node[0x0C]` more twenty-byte nodes.
BUNDLE_ID = 0x49
BUNDLE_COUNT = 0x0C

#: Where the record keeps the item count while it is in a file.  In memory the
#: long at `0x08` is the item chain head; the writer overwrites it with the
#: count before the record goes out (`0x2635E`) and the loader takes the count
#: from it and zeroes it again (`0x25842`).
ITEM_COUNT_AT = 0x08
#: The record's effect-chain head, which is a flag in a file rather than a
#: count: non-zero means one node follows, and each node's own long at `0x06`
#: says whether another does (`0x25AB2`-`0x25B2A`).
EFFECT_HEAD_AT = 0x04
EFFECT_NEXT_AT = 0x06
NAME_AT, NAME_BYTES = 0x60, 16

#: `Vault<L>.DAT`: twelve bytes of header, the marker `$FFFF`, a `u16be` item
#: count, then a fixed two hundred twenty-byte item nodes, the unused ones
#: padded from the same item template table (`0x3DA86`).  12 + 4 + 200 * 20 =
#: 4016, which is what every one of them measures.
VAULT_HEADER = 12
VAULT_MARKER = 0xFFFF
VAULT_ITEMS = 0xC8
VAULT_SIZE = VAULT_HEADER + 4 + VAULT_ITEMS * ITEM_BYTES

#: The executable, on disk 1.
EXECUTABLE = "Pools of Darkness"
#: The small-data global holding the variable block's base pointer, as a
#: displacement off `a4`.  `movea.l -$2852(a4), aN` is how every access to a
#: variable opens.
VAR_POINTER = 0x57AC


class PodSaveError(ValueError):
    """A buffer that is not an Amiga Pools of Darkness saved game."""


@dataclasses.dataclass(frozen=True)
class PodCharacter:
    """One character's block: the record, then its items, then its effects."""

    name: str
    at: int
    items: int
    bundled: int
    effects: int

    @property
    def size(self) -> int:
        return (RECORD_BYTES + ITEM_BYTES * (self.items + self.bundled)
                + EFFECT_BYTES * self.effects)


@dataclasses.dataclass(frozen=True)
class PodSavegame:
    data: bytes
    square: dict[str, int]
    previous_mode: int
    mode: int
    dungeon_map: int
    map_block: int
    count: int
    characters: tuple[PodCharacter, ...]
    #: Where the party region ends, which is where the padding begins.
    end: int

    def var(self, index: int) -> int:
        """Variable *index*, one-based, the way `pod_var` reads it on DOS."""
        if not 1 <= index <= VAR_BYTES:
            raise PodSaveError(f"variable {index} is outside the array")
        return self.data[index - 1]

    @property
    def clock(self) -> tuple[int, ...]:
        first = dos_savegame.POD_CLOCK
        return tuple(self.var(first + i)
                     for i in range(dos_savegame.POD_CLOCK_DIGITS))

    @property
    def clock_legal(self) -> bool:
        return all(digit < radix for digit, radix
                   in zip(self.clock, dos_savegame.POD_CLOCK_RADIX))

    @property
    def pad(self) -> bytes:
        return self.data[self.end:]


def _u16(data: bytes, at: int) -> int:
    return struct.unpack_from(">H", data, at)[0]


def _u32(data: bytes, at: int) -> int:
    return struct.unpack_from(">I", data, at)[0]


def parse(data: bytes) -> PodSavegame:
    """One saved game, walked the way the loader walks it.

    Every boundary comes from the file rather than from a table of widths:
    the party count says how many records follow, each record's own item
    count says how many twenty-byte nodes come after it, and the effect
    chain ends at the first node whose `next` is zero.  So a parse that
    lands every name in printable ASCII is evidence the walk is right.
    """
    if len(data) < PARTY_AT:
        raise PodSaveError(f"{len(data)} bytes is shorter than the header")
    count = _u16(data, COUNT_AT)
    if not 1 <= count <= PARTY_MAX:
        raise PodSaveError(f"a party count of {count} is not 1 to {PARTY_MAX}")
    at = PARTY_AT
    characters = []
    for _ in range(count):
        start = at
        record = data[at:at + RECORD_BYTES]
        if len(record) < RECORD_BYTES:
            raise PodSaveError(f"the record at {start} runs off the end")
        at += RECORD_BYTES
        items = _u32(record, ITEM_COUNT_AT)
        if items > 0xFF:
            raise PodSaveError(f"an item count of {items} at {start}")
        bundled = 0
        for _item in range(items):
            node = data[at:at + ITEM_BYTES]
            if len(node) < ITEM_BYTES:
                raise PodSaveError(f"an item node at {at} runs off the end")
            at += ITEM_BYTES
            if node[0] == BUNDLE_ID:
                extra = node[BUNDLE_COUNT]
                bundled += extra
                at += ITEM_BYTES * extra
        effects = 0
        more = _u32(record, EFFECT_HEAD_AT)
        while more:
            node = data[at:at + EFFECT_BYTES]
            if len(node) < EFFECT_BYTES:
                raise PodSaveError(f"an effect node at {at} runs off the end")
            at += EFFECT_BYTES
            more = _u32(node, EFFECT_NEXT_AT)
            effects += 1
        name = record[NAME_AT:NAME_AT + NAME_BYTES].split(b"\x00")[0]
        characters.append(PodCharacter(
            name.decode("latin1"), start, items, bundled, effects))
    if at > len(data):
        raise PodSaveError(f"the party ends at {at}, past {len(data)}")
    square = {name: data[SQUARE_AT + i] for i, name in enumerate(SQUARE)}
    return PodSavegame(
        data=data, square=square, previous_mode=data[PREVIOUS_MODE_AT],
        mode=data[MODE_AT], dungeon_map=_u16(data, MAP_AT),
        map_block=_u16(data, MAP_BLOCK_AT), count=count,
        characters=tuple(characters), end=at)


def rebuild(save: PodSavegame) -> bytes:
    """The file again, region by region, from what :func:`parse` named.

    The padding is kept as it was read: nothing in the engine reads it, so
    there is nothing to derive it from, and a round trip that regenerated it
    would be proving its own arithmetic instead of the map.
    """
    out = bytearray(save.data[:VAR_BYTES])
    out += bytes(save.square[name] for name in SQUARE)
    out += bytes((save.previous_mode, save.mode))
    out += struct.pack(">HHH", save.dungeon_map, save.map_block, save.count)
    for character in save.characters:
        out += save.data[character.at:character.at + character.size]
    out += save.pad
    return bytes(out)


def files(pattern: str) -> dict[str, list[tuple[str, bytes]]]:
    """Every matching file in a `Save` drawer of the player's Amiga disks.

    Keyed by file name, with one entry per distinct copy, because the disk
    images on a machine are several rips of the same release and they do not
    all agree: a run that silently took one of them would look like a finding
    about the game.
    """
    found: dict[str, dict[bytes, list[str]]] = collections.defaultdict(dict)
    for label, data in amigasaves.images():
        try:
            disk = AmigaDisk(data)
            entries = list(disk.walk())
        except (AmigaDiskError, ValueError):
            continue
        for path, _entry in entries:
            name = path.rsplit("/", 1)[-1]
            if not re.fullmatch(pattern, name, re.IGNORECASE):
                continue
            try:
                blob = disk.read_file(path)
            except AmigaDiskError:
                continue
            found[name].setdefault(blob, []).append(label)
    return {name: [(labels[0], blob) for blob, labels in sorted(
                copies.items(), key=lambda kv: (-len(kv[1]), kv[1][0]))]
            for name, copies in sorted(found.items())}


def slots() -> dict[str, list[tuple[str, bytes]]]:
    return files(r"SavGam.\.pty")


def vaults() -> dict[str, list[tuple[str, bytes]]]:
    return files(r"Vault.\.dat")


def executable(quiet: bool = False) -> bytes:
    """The build the most disk-1 images agree on, and the counts."""
    seen: dict[bytes, list[str]] = {}
    for label, data in amigasaves.images():
        try:
            disk = AmigaDisk(data)
            entries = list(disk.walk())
        except (AmigaDiskError, ValueError):
            continue
        for path, _entry in entries:
            if path.rsplit("/", 1)[-1] == EXECUTABLE:
                seen.setdefault(disk.read_file(path), []).append(label)
    if not seen:
        raise SystemExit(f"no Amiga {EXECUTABLE!r} on any disk image here")
    blob = max(seen, key=lambda b: (len(seen[b]), len(b)))
    if not quiet:
        print(f"{EXECUTABLE}: {len(blob)} bytes, on {len(seen[blob])} of "
              f"{sum(len(v) for v in seen.values())} disk images that hold one",
              file=sys.stderr)
    return blob


def variable_sites(data: bytes) -> dict[int, list[int]]:
    """Which ECL variables the engine's own code names, and where.

    Every access opens `movea.l -$2852(a4), aN`, so the displacements that
    follow one of those -- before the register is loaded again -- are the
    variables the engine owns.  This is the Amiga counterpart of
    `tools/dos/dosptrfields.py`, which read the same census off `GAME.OVR`,
    and a displacement is variable *d*: the DOS pointer is one byte lower.

    A linear sweep through a hunk that also holds strings will occasionally
    decode one as an instruction, so a displacement past the array's end is
    dropped rather than reported.
    """
    md = amiga68k._capstone()
    exe = amiga68k.Executable.parse(data)
    code = next(h for h in exe.hunks if h.kind == "CODE")
    lo, hi = code.file_offset, code.file_offset + code.size
    pointer = struct.pack(">h", VAR_POINTER - amiga68k.SMALL_DATA_BIAS)
    sites: dict[int, list[int]] = collections.defaultdict(list)
    for register in range(8):
        name = f"a{register}"
        opcode = struct.pack(">H", 0x206C | (register << 9)) + pointer
        kill = re.compile(rf",\s*{name}$")
        reach = re.compile(rf"\$([0-9a-f]+)\({name}\b")
        for match in re.finditer(re.escape(opcode), data[lo:hi]):
            at = lo + match.start() + len(opcode)
            for insn in md.disasm(data[at:at + 64], at):
                text = f"{insn.mnemonic} {insn.op_str}"
                for found in reach.finditer(text):
                    index = int(found.group(1), 16)
                    if 1 <= index <= VAR_BYTES:
                        sites[index].append(insn.address)
                if insn.mnemonic in ("rts", "rte", "jmp", "bra"):
                    break
                if kill.search(text):
                    break
    return {index: sorted(set(where)) for index, where in sorted(sites.items())}


#: What DOS's own census of the same array found: file offsets 0-58 and
#: 195-197 off `[DS:0x87F8]`, which are variables 1-59 and 196-198.  Recorded
#: as a range rather than the exact set because the two ports are being
#: compared on which *region* the engine owns.
DOS_ENGINE_VARS = tuple(range(1, dos_savegame.POD_ENGINE_VARS + 1)) + (196, 197, 198)


def _report(name: str, blob: bytes) -> tuple[bool, str]:
    try:
        save = parse(blob)
    except PodSaveError as bad:
        return False, f"{name}  {len(blob)}  DOES NOT PARSE: {bad}"
    problems = []
    if len(blob) != SAVEGAME_SIZE:
        problems.append(f"length {len(blob)} not {SAVEGAME_SIZE}")
    if rebuild(save) != blob:
        problems.append("does not round-trip")
    if not save.clock_legal:
        problems.append(f"clock {save.clock} is not legal")
    if save.count != save.var(dos_savegame.POD_PARTY_COUNT):
        problems.append(f"count {save.count} against variable "
                        f"{dos_savegame.POD_PARTY_COUNT} "
                        f"{save.var(dos_savegame.POD_PARTY_COUNT)}")
    square = " ".join(f"{k}={save.square[k]}" for k in SQUARE)
    line = (f"{name}  {len(blob)}  {square}  prev={save.previous_mode} "
            f"mode={save.mode} map={save.dungeon_map},{save.map_block}  "
            f"n={save.count} party={PARTY_AT}-{save.end} pad={len(save.pad)}  "
            f"clock={'.'.join(str(d) for d in save.clock)}")
    if problems:
        return False, line + "  <- " + "; ".join(problems)
    return True, line


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if a slot does not parse and round-trip")
    ap.add_argument("--vars", action="store_true",
                    help="the ECL variables the engine's own code names")
    ap.add_argument("--vault", action="store_true",
                    help="the Vault<L>.DAT files, against their own writer")
    args = ap.parse_args(argv)

    clean = True
    if args.vars:
        sites = variable_sites(executable())
        named = sorted(sites)
        print(f"{len(named)} variables named off the block pointer, "
              f"{sum(len(v) for v in sites.values())} sites")
        print("  in DOS's engine range 1-%d: %s"
              % (dos_savegame.POD_ENGINE_VARS,
                 ", ".join(str(v) for v in named
                           if v <= dos_savegame.POD_ENGINE_VARS)))
        print("  above it: %s" % ", ".join(
            f"{v} ({'also DOS' if v in DOS_ENGINE_VARS else 'not in DOS'})"
            for v in named if v > dos_savegame.POD_ENGINE_VARS))
        if not args.check and not args.vault:
            return 0

    if args.vault:
        found = vaults()
        if not found:
            print("no Vault<L>.DAT on any disk image here", file=sys.stderr)
            return 2
        for name, copies in found.items():
            for index, (_label, blob) in enumerate(copies):
                marker = _u16(blob, VAULT_HEADER)
                count = _u16(blob, VAULT_HEADER + 2)
                ok = (len(blob) == VAULT_SIZE and marker == VAULT_MARKER
                      and count <= VAULT_ITEMS)
                print(f"{name}{'' if not index else f'#{index}'}  {len(blob)}"
                      f"  marker=${marker:04X}  items={count}"
                      f"{'' if ok else '  <- not the measured vault'}")
                clean &= ok
        return 0 if clean or not args.check else 1

    found = slots()
    if not found:
        print("no Amiga Pools of Darkness saved game on any disk image here; "
              "set $AMIGA_DISKS", file=sys.stderr)
        return 2
    total = 0
    for name, copies in found.items():
        for index, (_label, blob) in enumerate(copies):
            total += 1
            ok, line = _report(
                f"{name}{'' if not index else f'#{index}'}", blob)
            clean &= ok
            print(line)
    print(f"{total} saved game(s), {'all clean' if clean else 'SEE ABOVE'}")
    return 0 if clean or not args.check else 1


if __name__ == "__main__":
    raise SystemExit(main())
