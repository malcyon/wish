#!/usr/bin/env python3
"""What every DOS character record on this machine holds in a chosen field.

Written for `#235 (Two unattributed DOS byte ranges in the combat tail are
dropped converting to C64, and nobody knows what they hold)`, whose two
entries in `goldbox/dos.py`'s `DROPPED` table -- `field_83_87` and
`field_10c_10f` -- rested on "the same bytes in all 24 specimens", and 24 is
one played Pool of Radiance party.  `#224 (0x0B9 and 0x0BA are documented both
as an NPC marker and as the dual-class slot)` is the standing warning: **a byte
that is constant across a corpus is constant because of what the corpus is.**
So this widens the corpus rather than re-reading the same 24 files.

What it does, and it reads only:

1. **Finds every DOS Gold Box character record** under the roots given, or
   under the player's archives and `work/` by default.  A record is a file
   whose size is one of the four `goldbox/dos_layout.py` knows -- 285 Pool of
   Radiance, 422 Curse, 439 Silver Blades, 510 Pools of Darkness -- and whose
   suffix is a record suffix (`.SAV`, `.CHA`, `.GUY`).  Anything else,
   including the 288-byte Amiga records under `work/`, is skipped.
2. **Grades each file's provenance.**  `engine` is a file the game wrote:
   everything in the archives, and everything under `work/` that does not carry
   one of the `BUILT-`/`SEED-`/`C64-` prefixes this project's own writers use.
   `built` is ours.  The distinction is the whole point of the run: our own
   `WRITE_CONSTANTS` writes `00 00 01 00 00` into `field_83_87`, so a built
   file can only ever agree with the claim under test.  `--built` includes
   them, marked, and they are never counted in the headline partition.
3. **Deduplicates on the record bytes**, per title, because the archives ship
   every save directory twice and `work/` holds resave after resave of the
   same party.  A count is a count of distinct records.
4. **Prints the value partition** for each field named with `--field`: which
   byte values occur, how many distinct records hold each, and which -- name,
   class, level, title -- so a value that varies can be correlated at once.

`--field` takes a layout field name (`field_83_87`) or a raw
`0xNN:len` window in *Pool of Radiance* offsets, which is then followed
through each title's own shape.  `--per-title` breaks the partition down by
title, which is what tells "constant everywhere" from "constant within each
title and different between them".

Nothing here is a claim about what a field *means*.  It reports what the
records hold, which is what a claim has to rest on.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from goldbox import dos as gdos  # noqa: E402
from goldbox import dos_layout as dl  # noqa: E402
from tools import gamedisks  # noqa: E402

#: Suffixes a DOS character record is stored under.  `.GUY` is Gateway's
#: export, which reads through the Curse table (`dos_layout.shape_for`).
RECORD_SUFFIXES = (".sav", ".cha", ".guy")

#: Filename prefixes this project's own writers use for records **we** made.
#: A record we wrote carries whatever `goldbox/dos.py` chose to write, so it
#: is evidence about our writer and never about the game.
BUILT_PREFIXES = ("built-", "seed-", "c64-", "conv-")

#: Directories under `work/` holding hand-assembled specimens whose names do
#: not carry a prefix.  Listed rather than guessed; add to it, do not widen
#: the prefix list, because a prefix that matches too much silently shrinks
#: the corpus and the shrink is invisible in the output.
BUILT_DIRS = ("issue191/built",)

#: An emulator instance's **staged game tree**, which is skipped entirely.
#:
#: This is the trap that cost a re-take.  `tools/dosbox.py` copies the game
#: into `work/dosbox/inst/<n>/game/<stem>/`, and a probe that tampers with a
#: record writes it there under the game's own name -- so a sweep counting
#: that directory reads **our** staged bytes as the engine's, and a run of
#: `tools/dostailprobe.py` staging `04 00 00 00` would come back as a
#: specimen holding `04 00 00 00`.  Whatever the engine wrote in there is
#: also still in whichever `work/` directory the run copied it out to, so
#: nothing is lost by skipping the tree.
SCRATCH_DIRS = ("work/dosbox/inst/", "work/dosbox/x/inst/")


def archives() -> pathlib.Path | None:
    """The player's unpacked Forgotten Realms archives, or None.

    `$FR_ARCHIVES`, then `gamedisks.toml`'s search list, then the usual
    unpack directory -- the same three steps `tools/dosbox.py` takes, so a
    machine configured for one is configured for the other.
    """
    env = os.environ.get("FR_ARCHIVES")
    if env:
        return pathlib.Path(env).expanduser()
    found = gamedisks.find("dos-archives")
    if found:
        return found
    guess = pathlib.Path.home() / "Downloads" / "fr-archives"
    return guess if guess.is_dir() else None


def is_built(path: pathlib.Path) -> bool:
    """Did this project write this record, rather than the game?"""
    if path.name.lower().startswith(BUILT_PREFIXES):
        return True
    text = path.as_posix()
    return any(d in text for d in BUILT_DIRS)


class Specimen:
    """One distinct record, with everything the partition wants to print."""

    def __init__(self, path: pathlib.Path, data: bytes) -> None:
        self.path = path
        self.data = data
        self.shape = dl.shape_for(len(data))
        self.built = is_built(path)
        self.digest = hashlib.sha256(data).hexdigest()[:12]
        self.paths = [path]
        char = gdos.DosCharacter(data, shape=self.shape)
        self.char = char
        try:
            self.name = char.name or "(unnamed)"
        except Exception:                                # pragma: no cover
            self.name = "(unreadable)"
        self.klass = _safe(char, "char_class")
        self.level = _safe(char, "level")
        self.race = _safe(char, "race")

    @property
    def who(self) -> str:
        klass = dl.CLASS_NUMBERS[self.klass] if isinstance(
            self.klass, int) and self.klass < len(dl.CLASS_NUMBERS) else "?"
        return f"{self.name} ({klass} {self.level})"


def _safe(char, name):
    try:
        return char.get(name)
    except Exception:                                    # pragma: no cover
        return None


def collect(roots, want_built: bool) -> list[Specimen]:
    """Every distinct DOS record under `roots`, deduplicated on its bytes."""
    seen: dict[str, Specimen] = {}
    for root in roots:
        if not root.exists():
            continue
        walk = sorted(root.rglob("*")) if root.is_dir() else [root]
        for path in walk:
            if not path.is_file() or path.suffix.lower() not in RECORD_SUFFIXES:
                continue
            if any(d in path.as_posix() for d in SCRATCH_DIRS):
                continue
            try:
                size = path.stat().st_size
            except OSError:                              # pragma: no cover
                continue
            if size not in dl.SHAPES_BY_SIZE:
                continue
            data = path.read_bytes()
            try:
                spec = Specimen(path, data)
            except Exception as exc:                     # pragma: no cover
                print(f"  skipped {path}: {exc}", file=sys.stderr)
                continue
            if spec.built and not want_built:
                continue
            key = f"{spec.shape.key}:{spec.digest}"
            if key in seen:
                seen[key].paths.append(path)
            else:
                seen[key] = spec
    return list(seen.values())


def window(spec: Specimen, field: str) -> bytes | None:
    """The bytes `field` names in this specimen's own title's shape."""
    if ":" in field:
        head, _, length = field.partition(":")
        start = int(head, 0)
        if spec.shape.key != "pool-of-radiance":
            # A raw window is stated in Pool of Radiance offsets; following it
            # into another title would need a per-title displacement nobody
            # has measured, so say so rather than read the wrong bytes.
            return None
        return spec.data[start:start + int(length, 0)]
    f = dl.FIELDS_BY_NAME_FOR[spec.shape.key].get(field)
    if f is None:
        return None
    return spec.data[f.offset:f.offset + f.size]


def show(specs: list[Specimen], field: str, per_title: bool,
         examples: int) -> None:
    if not per_title:
        _partition(specs, field, examples)
        return
    keyed = collections.defaultdict(list)
    for s in specs:
        keyed[s.shape.key].append(s)
    for key in sorted(keyed):
        f = dl.FIELDS_BY_NAME_FOR[key].get(field)
        where = f"0x{f.offset:03X}+{f.size}" if f else "not in this shape"
        print(f"\n  {dl.SHAPES_BY_KEY[key].title} -- {field} {where}")
        _partition(keyed[key], field, examples, indent="    ")


def _partition(specs, field, examples, indent="  ") -> None:
    groups = collections.defaultdict(list)
    for s in specs:
        groups[window(s, field)].append(s)
    for raw, group in sorted(groups.items(),
                             key=lambda kv: -len(kv[1])):
        if raw is None:
            print(f"{indent}(field absent) x{len(group)}")
            continue
        hexed = " ".join(f"{b:02X}" for b in raw)
        mark = " BUILT" if all(s.built for s in group) else ""
        print(f"{indent}{hexed}  x{len(group)}{mark}")
        for s in group[:examples]:
            flag = "*" if s.built else " "
            print(f"{indent}  {flag}{s.who:38s} "
                  f"{s.shape.key:28s} {s.path.name}")
        if len(group) > examples:
            print(f"{indent}  ... and {len(group) - examples} more")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("roots", nargs="*", type=pathlib.Path,
                    help="directories to sweep; default the archives and work/")
    ap.add_argument("--field", action="append", default=[],
                    help="layout field name, or 0xNN:len in Pool of "
                         "Radiance offsets; repeatable")
    ap.add_argument("--built", action="store_true",
                    help="include records this project wrote, marked *")
    ap.add_argument("--per-title", action="store_true",
                    help="break the partition down by title")
    ap.add_argument("--examples", type=int, default=6,
                    help="specimens to name per value (default 6)")
    ap.add_argument("--list", action="store_true",
                    help="list every distinct record found and stop")
    args = ap.parse_args(argv)

    roots = list(args.roots)
    if not roots:
        arch = archives()
        if arch:
            roots.append(arch)
        roots.append(REPO / "work")
    fields = args.field or ["field_83_87", "field_10c_10f"]

    specs = collect(roots, args.built)
    by_title = collections.Counter(s.shape.key for s in specs)
    built = sum(1 for s in specs if s.built)
    print(f"{len(specs)} distinct records "
          f"({len(specs) - built} engine-written, {built} ours) under:")
    for r in roots:
        print(f"  {r}")
    for key, n in sorted(by_title.items()):
        print(f"  {dl.SHAPES_BY_KEY[key].title:32s} {n}")

    if args.list:
        for s in sorted(specs, key=lambda s: (s.shape.key, s.name)):
            print(f"  {'*' if s.built else ' '}{s.who:38s} "
                  f"{s.shape.key:28s} {s.digest} {s.path}")
        return 0

    for field in fields:
        print(f"\n{field}:")
        show(specs, field, args.per_title, args.examples)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
