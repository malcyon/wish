#!/usr/bin/env python3
"""Read an Amiga Gold Box saved game through the map its own save routine writes.

`#28 (Decode an Amiga saved game, not just a character file)` found the
container's shape by reading the save and load routines out of the three
executables -- `/Curse`, `/Secret` and Pool of Radiance's `/program` -- and
this is the parser that proves the map was read right.  It walks the file
region by region in the order the game writes it, and :func:`check` compares
what it finds against things the file says independently: the signature scan
in `goldbox.amiga_later.party_in_savegame`, the `$503E` and `$5012` words in the
variable array, and the file's own length.

    tools/amigasavecheck.py --adf work/copy-of-disk.adf
    tools/amigasavecheck.py work/28/saves/curse-savgamA.dat

Each title's save routine is a straight run of `write(fd, buf, len)` calls,
so the file is the concatenation in :data:`SHAPES`.  `docs/165-amiga-savegame.md`
carries the map and the evidence; the numbers here are the code's.

Everything is read; nothing is written.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Sequence

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import amiga_later, amiga_savegame  # noqa: E402
from goldbox.amiga_adf import AmigaDisk, AmigaDiskError  # noqa: E402

#: The game-mode byte's values, from the code beside each write of it.  The
#: same enumeration on all three titles.
GAME_MODES = {2: "camp", 3: "overland", 4: "3D adventuring", 5: "combat",
              7: "ending"}
#: Pool of Radiance keeps a view type where the later titles keep the mode
#: before the current one.  **The code beside the write names 1 and 2 and the
#: engine stores 3 outdoors**: both saved games the Amiga game itself made on
#: the travel grid hold 3, which is what DOS holds in 10 of 10 outdoor
#: specimens, and 2 has never been seen in any Amiga saved game on this
#: machine (`#321 (An Amiga Pool of Radiance conversion refuses a party
#: standing on the travel grid, because no outdoor Amiga saved game has ever
#: been read)`).  2 is kept in the table so a file holding it reads as
#: something rather than as `?`.
VIEW_TYPES = {1: "3D", 2: "overland, from the code and never yet seen",
              3: "the travel grid"}

#: Variable-array words the code names, by address.
NAMED_WORDS = {
    0x49C5: "geo block id",
    0x49C6: "clock: sub-minute",
    0x49C7: "clock: minute units",
    0x49C8: "clock: minute tens",
    0x49C9: "clock: hour",
    0x49CA: "clock: day",
    0x49CB: "clock: month",
    0x49E6: "indoors",
    0x49FC: "engine byte g3d3e (low byte)",
    0x49FF: "2 x g63d1 + g63d0",
    0x5012: "container number",
    0x503E: "party size (cleared on load)",
}


def check(save: amiga_savegame.AmigaSavegame) -> list[tuple[str, bool, str]]:
    """Every way the file can contradict the map, as `(claim, ok, detail)`.

    A claim is something the file says twice, once through the map and once
    through something the map does not use.
    """
    s, out = save.container, []
    if s.header_bytes:
        out.append(("byte 0 is $5012", save.header_byte == save.word(0x5012),
                    f"{save.header_byte} against {save.word(0x5012)}"))
    out.append(("$503E is the party count", save.word(0x503E) == save.count,
                f"{save.word(0x503E)} against {save.count}"))
    if s.party == "records":
        scan = [c for c in range(len(save.data))
                if amiga_later.looks_like_amiga_record(save.data, c, s.deltas)]
        starts = [b[0] for b in save.blocks]
        out.append(("every block starts where the scan finds a record",
                    scan == starts,
                    f"scan {[hex(c) for c in scan]} against "
                    f"{[hex(c) for c in starts]}"))
        out.append(("the last block ends at the end of the file",
                    save.end == len(save.data),
                    f"{save.end} against {len(save.data)}"))
    else:
        # The loader reads `count` names and no more; slots past the count
        # hold whatever was under the buffer on the stack (`docs/141`).
        used = list(save.names[:save.count])
        out.append(("the first count slots are CHRDAT plus a letter and a "
                    "digit",
                    all(len(n) == amiga_savegame.POR_CHARACTER_TABLE_NAME
                        and n.startswith("CHRDAT")
                        and n[7].isdigit() for n in used), str(used)))
        out.append(("the count is at most the eight slots",
                    save.count <= amiga_savegame.POR_NAME_SLOTS, str(save.count)))
    if s.party == "records":
        try:
            rebuilt = amiga_savegame.rebuild(save)
        except (amiga_savegame.AmigaSaveError, amiga_savegame.AmigaRecordError) as error:
            out.append(("the party rebuilds to the bytes it was read from", False,
                        str(error)))
        else:
            out.append(("the party rebuilds to the bytes it was read from",
                        rebuilt == save.data,
                        f"{len(rebuilt)} bytes against {len(save.data)}"))
    out.append(("the party count is 1 to 6",
                1 <= save.count <= amiga_savegame.PARTY_MAX, str(save.count)))
    out.append(("facing is doubled: 0, 2, 4 or 6",
                save.square["facing"] in (0, 2, 4, 6),
                str(save.square["facing"])))
    out.append(("the mode byte is one the code writes",
                save.mode in GAME_MODES or save.mode == 0, str(save.mode)))
    for name, value in save.square.items():
        if name == "pad" or name == "wallset_entry_0":
            out.append((f"square {name} is zero", value == 0, str(value)))
    return out


def sweep(saves: Sequence[tuple[str, amiga_savegame.AmigaSavegame]]) -> str:
    """Which variable words are ever non-zero, grouped by the place.

    The writers zero every word no source save answers for, on the argument
    that nothing here holds anything there -- and that argument is only as
    wide as the places the parties in the corpus have stood.  This is what
    measures the width.  Grouping by `$5012`, the container number, is what
    makes it readable: the interesting column is what a corpus of one place
    alone would have missed, which is the size of the risk in adding a
    fourteenth area nobody has visited.

    `docs/165-amiga-savegame.md`, "Still open".
    """
    if not saves:
        return "nothing to sweep"
    words = {}                       # container -> set of non-zero addresses
    counts = {}
    for _label, save in saves:
        base = amiga_savegame.VM_BASE
        here = words.setdefault(save.word(0x5012), set())
        counts[save.word(0x5012)] = counts.get(save.word(0x5012), 0) + 1
        for address in range(base, base + amiga_savegame.VM_BYTES // 2):
            if save.word(address):
                here.add(address)
    everywhere = set().union(*words.values())
    lines = [f"{len(saves)} saved games, {len(words)} places, "
             f"{len(everywhere)} of {amiga_savegame.VM_BYTES // 2} words ever non-zero",
             "  $5012  files  non-zero  this one alone would have missed"]
    for container in sorted(words):
        lines.append(f"  {container:5d}  {counts[container]:5d}  "
                     f"{len(words[container]):8d}  "
                     f"{len(everywhere - words[container])}")
    return "\n".join(lines)


def report(save: amiga_savegame.AmigaSavegame, label: str = "") -> str:
    s = save.container
    lines = [f"{label or 'saved game'}: {s.title}, {len(save.data)} bytes"]
    if s.header_bytes:
        lines.append(f"  byte 0: container number {save.header_byte}")
    lines.append(f"  variable array at {s.vm_at}, {amiga_savegame.VM_BYTES} bytes; "
                 f"clock {save.clock}")
    for address, name in NAMED_WORDS.items():
        lines.append(f"    ${address:04X} {name}: {save.word(address)}")
    if s.ecl_bytes:
        used = len(save.ecl.rstrip(b"\0"))
        lines.append(f"  ECL buffer at {s.ecl_at:#x}, {s.ecl_bytes} bytes, "
                     f"{used} non-zero from the front")
    lines.append(f"  square block at {s.square_at:#x}, {s.square_bytes} bytes:")
    for field in s.square:
        lines.append(f"    {field.name}: {save.square[field.name]}"
                     + (f"  ({field.note})" if field.note else ""))
    first = (VIEW_TYPES if s.first_mode_byte == "view type"
             else GAME_MODES).get(save.first_mode, "?")
    lines.append(f"  {s.first_mode_byte} at {s.first_mode_at:#x}: "
                 f"{save.first_mode} ({first})")
    lines.append(f"  game mode at {s.mode_at:#x}: {save.mode} "
                 f"({GAME_MODES.get(save.mode, '?')})")
    if s.wallset_table:
        shown = ", ".join("empty" if b == 0xFFFF else f"block {b} in slot {sl}"
                          for b, sl in save.wallset)
        lines.append(f"  wallset table at {s.wallset_at:#x}: {shown}")
    lines.append(f"  party count at {s.count_at:#x}: {save.count}")
    if s.party == "records":
        for char, (at, end) in zip(save.characters, save.blocks):
            lines.append(f"    {at:#x}-{end:#x}: {char.name!r}, "
                         f"{len(char.items)} items, {len(char.effects)} "
                         f"effects")
    else:
        shown = [n if i < save.count else "(unused)"
                 for i, n in enumerate(save.names)]
        lines.append(f"  name table at {s.party_at}: " + " ".join(shown))
    for claim, ok, detail in check(save):
        lines.append(f"  [{'ok' if ok else 'FAIL'}] {claim}: {detail}")
    return "\n".join(lines)


def savegames_on(disk: AmigaDisk):
    """Every saved game on a disk, as `(path, bytes)`.

    A game disk keeps them in a `save` drawer; **a `POOLSAVE` save disk keeps
    them in the root**, which is where `goldbox.amiga_por.make_por_save_disk`
    writes them and where the Amiga game's own picker looks when the player
    answers its `PATH FOR SAVE` prompt with RETURN.  Both are read: pointing
    this at the disk a conversion just produced used to report that no image
    had been named.
    """
    for path, _entry in disk.walk():
        parts = path.strip("/").split("/")
        if not parts[-1].lower().startswith("savgam"):
            continue
        if len(parts) == 1 or (len(parts) == 2 and parts[0].lower() == "save"):
            yield path, disk.read_file(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", help="saved games, as raw files")
    parser.add_argument("--adf", action="append", default=[],
                        help="a disk image; every savgam*, in the root or in "
                             "a save drawer, is read")
    parser.add_argument("--sweep", action="store_true",
                        help="instead of a report each, one table of which "
                             "variable words are ever non-zero, by place")
    args = parser.parse_args(argv)
    todo: list[tuple[str, bytes]] = []
    for f in args.files:
        todo.append((f, pathlib.Path(f).read_bytes()))
    empty = []
    for image in args.adf:
        try:
            disk = AmigaDisk.open(image)
        except AmigaDiskError as ex:
            raise SystemExit(f"{image}: {ex}")
        on_it = list(savegames_on(disk))
        if not on_it:
            empty.append(f"{image} ({disk.volume_name})")
        todo.extend((f"{image}!{p}", d) for p, d in on_it)
    if not todo and empty:
        raise SystemExit("no saved game on " + ", ".join(empty)
                         + ": a savgam* file in the root or in a save drawer "
                           "is what this reads")
    if not todo:
        parser.error("name a saved game or an --adf image")
    failed = 0
    parsed = []
    for label, data in todo:
        try:
            save = amiga_savegame.parse(data, source=label, validate=False)
        except (amiga_savegame.AmigaSaveError, amiga_savegame.AmigaRecordError) as ex:
            print(f"{label}: {ex}")
            failed += 1
            continue
        parsed.append((label, save))
        if args.sweep:
            continue
        print(report(save, label))
        failed += sum(1 for _, ok, _ in check(save) if not ok)
    if args.sweep:
        print(sweep(parsed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
