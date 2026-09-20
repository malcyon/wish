#!/usr/bin/env python3
"""Read the Amiga *Pools of Darkness* saved game through its own save routine.

`/Pools of Darkness` on disk 1 writes `Save/SavGam<L>.pty` as a straight run of
`write(fd, buf, len)` calls, and its loader reads the same sequence back.  The
callbacks are at file offsets `0x270E0` (save) and `0x26904` (load), and every
region below is one of their calls:

    1024  the byte-wide ECL variable array, from `[g57ac] + 1`
       6  the square struct `g5f20`: x, y, facing, wall type, attribute, pad
       1  `g743c`, the mode the party was in before this one
       1  `g5b12`, the game mode -- 2 in every save the game wrote, because a
          save is camped; a party never taken into the world leaves 0
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
import pathlib
import re
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from goldbox import amiga_savegame, dos_savegame  # noqa: E402
from goldbox.amiga_adf import AmigaDisk, AmigaDiskError  # noqa: E402
from tools.amiga import amiga68k, amigasaves  # noqa: E402

# The container map lives in `goldbox.amiga_savegame` under `POD_*` names; these
# aliases drop the prefix, which is the spelling the tool's functions and its
# tests use, so the tests can also reach the map through this module.
SAVEGAME_SIZE = amiga_savegame.POD_SAVEGAME_SIZE
VAR_BYTES = amiga_savegame.POD_VAR_BYTES
SQUARE = amiga_savegame.POD_SQUARE
SQUARE_AT = amiga_savegame.POD_SQUARE_AT
PREVIOUS_MODE_AT = amiga_savegame.POD_PREVIOUS_MODE_AT
MODE_AT = amiga_savegame.POD_MODE_AT
MAP_AT = amiga_savegame.POD_MAP_AT
MAP_BLOCK_AT = amiga_savegame.POD_MAP_BLOCK_AT
COUNT_AT = amiga_savegame.POD_COUNT_AT
PARTY_AT = amiga_savegame.POD_PARTY_AT
PARTY_MAX = amiga_savegame.POD_PARTY_MAX
RECORD_BYTES = amiga_savegame.POD_RECORD_BYTES
ITEM_BYTES = amiga_savegame.POD_ITEM_BYTES
EFFECT_BYTES = amiga_savegame.POD_EFFECT_BYTES
BUNDLE_ID = amiga_savegame.POD_BUNDLE_ID
BUNDLE_COUNT = amiga_savegame.POD_BUNDLE_COUNT
ITEM_COUNT_AT = amiga_savegame.POD_ITEM_COUNT_AT
EFFECT_HEAD_AT = amiga_savegame.POD_EFFECT_HEAD_AT
EFFECT_NEXT_AT = amiga_savegame.POD_EFFECT_NEXT_AT
NAME_AT, NAME_BYTES = amiga_savegame.POD_NAME_AT, amiga_savegame.POD_NAME_BYTES
PodSaveError = amiga_savegame.PodSaveError
PodCharacter = amiga_savegame.PodCharacterBlock
PodSavegame = amiga_savegame.PodSavegame
parse = amiga_savegame.pod_parse
rebuild = amiga_savegame.pod_rebuild


def _u16(data: bytes, at: int) -> int:
    return struct.unpack_from(">H", data, at)[0]


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
            if path.rsplit("/", 1)[-1] != EXECUTABLE:
                continue
            try:
                blob = disk.read_file(path)
            except AmigaDiskError:
                continue
            seen.setdefault(blob, []).append(label)
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
                label = f"{name}{'' if not index else f'#{index}'}"
                if len(blob) < VAULT_HEADER + 4:
                    print(f"{label}  {len(blob)}  <- too short to hold a "
                          "vault header")
                    clean = False
                    continue
                marker = _u16(blob, VAULT_HEADER)
                count = _u16(blob, VAULT_HEADER + 2)
                ok = (len(blob) == VAULT_SIZE and marker == VAULT_MARKER
                      and count <= VAULT_ITEMS)
                print(f"{label}  {len(blob)}"
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
