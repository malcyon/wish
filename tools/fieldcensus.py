#!/usr/bin/env python3
"""One named record field, over every character record on this machine.

`tools/thac0census.py` asks this of `thac0_base` and knows that field's table;
this asks it of **any** field by name, and knows nothing about what the answer
should be.  It is the thing that gets rewritten every time a byte's meaning is
in question: print the stored value beside the class levels, group it, and see
whether a rule fits.

    tools/fieldcensus.py c64 attack_level
    tools/fieldcensus.py dos attack_level --all-titles
    tools/fieldcensus.py monsters level --title pool-of-radiance

It settled `#527 (A DOS import combines saving throws from classes the
character does not have)`'s last open byte.  `attack_level` at C64 `0x098` is
the fighter's level in 26 of 26 C64 records that have one, and the **constant
1** in 220 of 238 DOS Pool of Radiance records -- including a party taken to
fighter 8 through the game's own schools -- so the DOS-to-C64 copy of that
byte writes a value carrying no information.  Curse and Silver Blades do
maintain it, which is why the sweep has to be per title and could not be read
off one corpus.

**Say which corpus a count is over.**  The C64 and DOS sweeps see different
records, and an earlier census of this same field was C64-only and concluded
that no engine ever writes 1.  The header line names the corpus for that
reason.

`monsters` is the third corpus and nothing else reads it: Pool of Radiance's
116 `MON<hex>` files are PRGs whose body is a character record at offset 0, so
a monster's `level` and `attack_level` are readable with the ordinary layout.
That is how the 11 creatures of under one hit die -- the ones the C64 sweep
attack is for -- were counted.

Nothing here writes anything.  The player's disks are opened read-only.
"""

from __future__ import annotations

import argparse
import collections
import glob
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import dos_codec  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.record import CharacterRecord  # noqa: E402
from goldbox.savegame import SaveGame0  # noqa: E402
from tools import gamedisks  # noqa: E402
from tools.thac0census import C64_LEVEL_FIELDS  # noqa: E402

#: Save disks carry a party; every other `.d64` on the pile is a game side.
SAVE_DISK_PREFIXES = ("PORSAVE", "NEWSAVE", "TEST_DOS")

#: The specimen tree keeps every C64 title's disks in `por-c64/`, so the
#: directory is not the title and the **filename prefix** is.  Globbing
#: `WISH-SPEC-*` there silently mixes six Curse and six Silver Blades disks
#: into a Pool of Radiance count, which is how a census grows by six records
#: that answer for another game's record layout.
C64_SPECIMEN_PREFIX = {"pool-of-radiance": "WISH-SPEC-por",
                       "curse-of-the-azure-bonds": "WISH-SPEC-curse",
                       "secret-of-the-silver-blades": "WISH-SPEC-ssb"}

#: Where the specimen tree lives, the same way every other tool asks.
def _specimen_tree() -> pathlib.Path:
    return pathlib.Path(os.environ.get("WISH_SPECIMENS",
                                       pathlib.Path.home() / "wish-specimens"))


class Row:
    """One record's answer: where it came from, who it is, what it held."""

    __slots__ = ("source", "name", "levels", "value")

    def __init__(self, source, name, levels, value):
        self.source, self.name = source, name
        self.levels, self.value = levels, value

    @property
    def fighter(self) -> int:
        return int(self.levels.get("fighter", 0) or 0)


def c64_rows(field: str, title: str = "pool-of-radiance"):
    """Every C64 record of `title`, from the player's disks and the tree."""
    paths: list[pathlib.Path] = []
    where = gamedisks.find(title)
    if where is not None:
        paths += [p for p in sorted(where.glob("*.[dD]64"))
                  if p.name.upper().startswith(SAVE_DISK_PREFIXES)]
    prefix = C64_SPECIMEN_PREFIX.get(title)
    if prefix:
        paths += sorted((_specimen_tree() / "por-c64").glob(f"{prefix}-*.[dD]64"))
    for path in paths:
        try:
            disk = D64.open(str(path))
            names = {e.name for e in disk.directory()}
        except Exception:
            continue
        records = []
        if b"SAVEDGAME0" in names:
            try:
                save = SaveGame0.from_prg(disk.read_file(b"SAVEDGAME0"))
            except Exception:
                continue
            records = [(path.name, s.record) for s in save.characters]
        else:
            for entry in disk.directory():
                if not entry.is_prg or entry.is_empty:
                    continue
                try:
                    label = f"{path.name}:{entry.name.decode('latin1').strip()}"
                    records.append((label,
                                    CharacterRecord.from_prg(disk.read_file(entry))))
                except Exception:
                    pass
        for source, record in records:
            levels = {n: record.get(f) for n, f in C64_LEVEL_FIELDS
                      if record.get(f)}
            yield Row(source, str(record.name), levels, record.get(field))


def dos_rows(field: str, title: str | None = "pool-of-radiance"):
    """Every DOS record the machine holds, of `title` or of all four."""
    from tools import dosbox

    tree = _specimen_tree()
    folders = [str(p) for p in sorted(tree.glob("*/WISH-SPEC-*")) if p.is_dir()]
    files: list[str] = []
    for folder in folders:
        files += glob.glob(folder + "/CHRDAT*.SAV") + glob.glob(folder + "/*.CHA")
    if dosbox.ARCHIVES.is_dir():
        files += glob.glob(str(dosbox.ARCHIVES) + "/**/*.SAV", recursive=True)
        files += glob.glob(str(dosbox.ARCHIVES) + "/**/*.CHA", recursive=True)
    for path in sorted(set(files)):
        try:
            char = dos_codec.read_character(path)
        except Exception:
            continue
        if title is not None and char.shape.key != title:
            continue
        if field not in char.fields:
            continue
        parent = pathlib.Path(path).parent.name
        yield Row(f"{parent}/{pathlib.Path(path).name}", str(char.name),
                  dict(char.class_levels or {}), char.get(field))


def monster_rows(field: str, title: str = "pool-of-radiance"):
    """Every `MON<hex>` template on the game sides, read as a record.

    The file is a PRG whose body is a character record at offset 0, so a
    field's offset indexes the body directly.  Shorter than a player's record,
    so a field past the end is skipped rather than guessed at.
    """
    from goldbox import layout

    # The field name is checked before the disks are looked for, so a typo is
    # refused on a machine that has no game files rather than answering with
    # an empty census.
    declared = layout.FIELDS_BY_NAME.get(field)
    if declared is None:
        raise SystemExit(f"no C64 field called {field}")
    where = gamedisks.find(title)
    if where is None:
        return
    seen: dict[str, bytes] = {}
    for path in sorted(where.glob("*.[dD]64")):
        try:
            disk = D64.open(str(path))
        except Exception:
            continue
        for entry in disk.directory():
            name = entry.name.decode("latin1").rstrip("\xa0 ")
            if not name.startswith("MON") or name in seen:
                continue
            try:
                seen[name] = disk.read_file(entry.name)[2:]
            except Exception:
                pass
    for name, body in sorted(seen.items()):
        end = declared.offset + declared.size
        if len(body) < end:
            continue
        text = bytes(c & 0x7F for c in body[:16]).split(b"\x00")[0]
        value = body[declared.offset] if declared.size == 1 else \
            body[declared.offset:end]
        yield Row(name, text.decode("latin1", "replace").strip(),
                  {}, value)


def report(rows: list[Row], field: str, corpus: str, verbose: bool) -> None:
    print(f"{len(rows)} {corpus} records, {field}")
    if verbose:
        print(f"  {'source':46} {'name':16} {'value':>6}  classes")
        for r in rows:
            classes = ",".join(f"{k}{v}" for k, v in sorted(r.levels.items()))
            print(f"  {r.source[:46]:46} {r.name[:16]:16} "
                  f"{str(r.value):>6}  {classes}")
    counts = collections.Counter(str(r.value) for r in rows)
    print(f"\n  {'value':>8} {'records':>8}")
    for value, n in sorted(counts.items(), key=lambda kv: (len(kv[0]), kv[0])):
        print(f"  {value:>8} {n:>8}")
    pairs = collections.Counter((r.fighter, str(r.value)) for r in rows)
    if len(pairs) > 1 and any(r.levels for r in rows):
        print(f"\n  {'fighter':>8} {'value':>8} {'records':>8}")
        for (fighter, value), n in sorted(pairs.items()):
            print(f"  {fighter:>8} {value:>8} {n:>8}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("corpus", choices=("c64", "dos", "monsters"))
    parser.add_argument("field", help="the field's name in the record layout")
    parser.add_argument("--title", default="pool-of-radiance")
    parser.add_argument("--all-titles", action="store_true",
                        help="DOS only: every title, not just --title")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="one line a record before the tallies")
    args = parser.parse_args(argv)

    if args.corpus == "c64":
        rows = list(c64_rows(args.field, args.title))
        report(rows, args.field, f"C64 {args.title}", args.verbose)
    elif args.corpus == "monsters":
        rows = list(monster_rows(args.field, args.title))
        report(rows, args.field, f"{args.title} MON* template", args.verbose)
    elif args.all_titles:
        from goldbox import dos_port

        for deltas in dos_port.DELTAS:
            got = list(dos_rows(args.field, deltas.key))
            if got:
                report(got, args.field, f"DOS {deltas.key}", args.verbose)
                print()
    else:
        rows = list(dos_rows(args.field, args.title))
        report(rows, args.field, f"DOS {args.title}", args.verbose)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
