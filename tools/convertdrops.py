#!/usr/bin/env python3
"""What every registered `File ▸ Convert…` direction actually reports as
dropped, run against every specimen on this machine.

`#52 (File ▸ Import and File ▸ Export for every direction the library
supports)`'s condition 8 -- every registered direction perfect, its drop list
empty -- is a claim about what a conversion *reports*, not about what a
writer's `DROPPED` tuple declares.  The two are not the same thing:
`goldbox.neutral.Writer.finish` composes a line only for a field the neutral
record actually carries, so a declared entry no source can reach never fires.

Until 2026-09-09 `goldbox.dos.WRITE_UNREPORTED_DROPS` also silenced two
entries that a real C64 source does reach -- `turn_power` and `infravision`
-- so the count this tool's `sweep` reports could look emptier than the
conversion actually was.  `#483 (The Convert flag could come off while two
fields are still lost, because a silencing list keeps them out of the count
that decides it)` removed the silencing list: both names, plus `encumbrance`,
are on `goldbox.dos.WRITE_NO_SUCH_FIELD` or `WRITE_DERIVED` now, genuinely
consumed by `write` rather than faked as taken after the fact, so `sweep`'s
count needs no code change here to read honestly.

Two modes:

* the default **sweep** runs `Direction.rehearse` -- the same call
  `editor.convert.ConvertDialog._rehearse_and_report` makes, including the
  source title's own combat-icon tables (`#383`, `#422`) -- for every
  specimen `Source.detect` accepts, and tallies `report.dropped` per
  direction, naming which specimens reached each line;
* `--reach` crosses each direction's **reader** (the neutral fields it sets,
  over every specimen) against its **writer**'s declared drop list, and says
  which declared entries are reachable at all.  An entry no source carries
  cannot gate the flag, however long the list looks.

Inputs come from `$WISH_SPECIMENS` (default `~/wish-specimens`,
`tools/specimens.py`), the C64 game disks `tools/gamedisks.py` finds and the
DOS archives `tools/dosbox.find_game` finds.  Nothing is written outside a
temporary directory, and no specimen is opened for writing.

    tools/convertdrops.py
    tools/convertdrops.py --reach
"""

from __future__ import annotations

import argparse
import collections
import os
import pathlib
import re
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from editor import convert, dosimport  # noqa: E402
from goldbox import c64_codec, dos, games  # noqa: E402
from goldbox.d64 import load_payload  # noqa: E402
from goldbox.iconparts import IconParts  # noqa: E402
from goldbox.portraits import PortraitError, tables_from_disks  # noqa: E402
from tools import dosbox, gamedisks  # noqa: E402


def specimen_root() -> pathlib.Path:
    return pathlib.Path(os.environ.get("WISH_SPECIMENS")
                        or pathlib.Path.home() / "wish-specimens")


#: Each destination port's writer, and the list it declares.  All three Amiga
#: rows go through `goldbox.amiga.write_por`, which copies `goldbox.dos.write`'s
#: own report verbatim, so its declared list is the DOS writer's.
WRITER_DROPS = {
    "c64": ("goldbox.c64_codec.DROPPED", c64_codec.DROPPED),
    "dos": ("goldbox.dos.WRITE_DROPPED", dos.WRITE_DROPPED),
    "amiga": ("goldbox.dos.WRITE_DROPPED, via goldbox.amiga.write_por",
              dos.WRITE_DROPPED),
}

#: The DOS archive directory stem per title, for `tools/dosbox.find_game`.
DOS_DIRS = {
    "pool-of-radiance": "POOLRAD",
    "curse-of-the-azure-bonds": "CURSE",
    "secret-of-the-silver-blades": "SECRET",
}

_GAME_FILES: dict[str, object] = {}


def game_files(game):
    """The icon tables, `ANIMATE00` and portrait menu off `game`'s own C64
    disks -- `editor.window.EditorBinding.game_files_for`'s own search, and
    `None` when this machine has no disks for the title."""
    if game.key in _GAME_FILES:
        return _GAME_FILES[game.key]
    where = gamedisks.find(game.key)
    out = None
    if where is not None:
        icon = animate = None
        for disk in sorted(pathlib.Path(where).glob("*.[dD]64")):
            if icon is None:
                try:
                    icon = IconParts.load(str(disk))
                except Exception:
                    pass
            if animate is None:
                try:
                    animate = load_payload(str(disk), dos.ANIMATE_FILE)
                except Exception:
                    pass
        if icon is not None and animate is not None:
            portraits = None
            if game.key == games.POOL_OF_RADIANCE.key:
                try:
                    portraits = tables_from_disks(where)
                except (PortraitError, OSError):
                    portraits = None
            out = dosimport.GameFiles(icon=icon, animate=animate,
                                      portraits=portraits)
    _GAME_FILES[game.key] = out
    return out


def sources(root: pathlib.Path):
    """Every specimen path `editor.convert.Source.detect` accepts."""
    out = []
    for folder in sorted(root.glob("*-dos/WISH-SPEC-*")):
        if folder.is_dir():
            out.extend(sorted(folder.glob("SAVGAM?.DAT")))
    out.extend(sorted(root.glob("*-c64/WISH-SPEC-*.[dD]64")))
    out.extend(sorted(root.glob("*-amiga/WISH-SPEC-*/*.adf")))
    return out


def ecl_disk(scratch: pathlib.Path):
    """A path to an Amiga image carrying `/ecl.dax` -- Pool of Radiance disk
    2, the `POOLDATA` volume, which both Amiga destinations need."""
    from goldbox.amiga_adf import AmigaDisk
    from tools import amigasaves
    for _label, data in amigasaves.images():
        try:
            AmigaDisk(bytearray(data)).read_file("/ecl.dax")
        except Exception:
            continue
        path = scratch / "amiga-disk-2.adf"
        path.write_bytes(data)
        return path
    return None


def generalise(line: str) -> str:
    """A drop line with the character's own art id taken out, so the same
    loss on six characters counts as one line."""
    return re.sub(r"\b(HEAD|BODY)[0-9A-F]{2}\b", r"\1nn", line).strip()


def sweep() -> int:
    root = specimen_root()
    tally: dict = collections.defaultdict(lambda: collections.defaultdict(set))
    ran: collections.Counter = collections.Counter()
    failed: dict = collections.defaultdict(list)

    with tempfile.TemporaryDirectory(prefix="convertdrops-") as tmp:
        scratch = pathlib.Path(tmp)
        disk2 = ecl_disk(scratch)
        for path in sources(root):
            try:
                source = convert.Source.detect(path)
            except Exception as exc:
                failed["Source.detect"].append(f"{path.name}: {exc}")
                continue
            for direction in convert.destinations_for(source):
                label = f"{type(direction).__name__} {direction.source_key}"
                # `ConvertDialog._rehearse_and_report`'s own choice of slot
                # and options for each destination port, copied rather than
                # guessed at.
                if direction.destination_port == "c64":
                    slot = source.slot
                    options = game_files(direction.destination_game)
                elif direction.destination_port == "amiga":
                    slot, options = source.slot or "A", disk2
                else:
                    slot = "A"
                    stem = DOS_DIRS.get(direction.destination_game.key)
                    try:
                        options = dosbox.find_game(stem) if stem else None
                    except FileNotFoundError:
                        options = None
                if options is None or not slot:
                    failed[label].append(
                        f"{path.name}: no game disks, DOS archives or Amiga "
                        f"disk 2 for this direction")
                    continue
                try:
                    if (direction.source_port == "c64"
                            and direction.destination_port in ("dos", "amiga")):
                        files = game_files(direction.title)
                        rehearsal = direction.rehearse(
                            source, slot, options,
                            icon_parts=files.icon if files else None)
                    else:
                        rehearsal = direction.rehearse(source, slot, options)
                except Exception as exc:
                    failed[label].append(
                        f"{path.name}: {type(exc).__name__}: {exc}")
                    continue
                ran[label] += 1
                for line in rehearsal.report.dropped:
                    tally[label][generalise(line)].add(path.name)

    print("Specimens run, per direction")
    for label in sorted(ran):
        print(f"  {ran[label]:3d}  {label}")
    print("\nDropped, per direction")
    for label in sorted(ran):
        lines = tally.get(label, {})
        print(f"\n  {label}  ({ran[label]} specimens)")
        if not lines:
            print("      nothing dropped on any specimen")
        for line, where in sorted(lines.items()):
            print(f"      [{len(where)}/{ran[label]}] {line}")
            print(f"          {', '.join(sorted(where))}")
    if failed:
        print("\nCould not run")
        for label in sorted(failed):
            print(f"\n  {label}")
            for line in failed[label][:12]:
                print(f"      {line}")
            if len(failed[label]) > 12:
                print(f"      ... and {len(failed[label]) - 12} more")
    return 0


def reach() -> int:
    """Which declared drop-list entry any registered direction can reach."""
    from goldbox import amiga
    from goldbox.amiga_adf import AmigaDisk

    root = specimen_root()
    carried: dict = collections.defaultdict(set)

    def fields(source):
        if source.port == "dos":
            party = [dos.to_neutral(c)
                     for c in dos.read_party(source.path, source.slot)]
        elif source.port == "c64":
            party, _icons = dos.c64_party(source.save0, source.save1,
                                          game=games.by_key(source.key))
        else:
            raw, _savgam = amiga.read_por_slot(
                AmigaDisk.open(str(source.path)), source.slot)
            party = [dos.to_neutral(c) for c in raw]
        out: set = set()
        for char in party:
            out |= set(char.keys())
        return out

    for path in sources(root):
        try:
            source = convert.Source.detect(path)
            carried[(source.port, source.key)] |= fields(source)
        except Exception:
            continue

    print("Neutral fields each source port and title was measured to set:")
    for key in sorted(carried):
        print(f"  {key[0]:6} {key[1]:30} {len(carried[key])} fields")
    print()
    derived = {n for n, _ in dos.WRITE_NO_SUCH_FIELD} | {n for n, _ in
                                                         dos.WRITE_DERIVED}
    for direction in convert.DIRECTIONS:
        label, drops = WRITER_DROPS[direction.destination_port]
        have = carried.get((direction.source_port, direction.source_key), set())
        can = [n for n, _ in drops if n in have]
        print(f"{type(direction).__name__} {direction.source_key} -> "
              f"{direction.destination_port}   ({label})")
        print(f"   reachable:    {can or 'none'}")
        print(f"   of those the destination derives, so `write` consumes "
              f"and reports neither (WRITE_NO_SUCH_FIELD/WRITE_DERIVED): "
              f"{[n for n in have if n in derived] or 'none'}")
        print(f"   no source carries: "
              f"{[n for n, _ in drops if n not in have]}")
        print()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--reach", action="store_true",
                    help="cross each direction's reader against its writer's "
                         "declared drop list instead of running conversions")
    args = ap.parse_args(argv)
    return reach() if args.reach else sweep()


if __name__ == "__main__":
    raise SystemExit(main())
