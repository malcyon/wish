#!/usr/bin/env python3
"""Who fails the encumbrance identity, on every port and title this machine has.

`money + sum(item weight x quantity)` is meant to equal the record's stored
encumbrance, and `.claude/rules/testing.md` has reasoned from a record failing
it towards that record having been edited.  `#323 (The encumbrance identity
does not survive the training fee, so failing it is not evidence of an edited
record)` is the ticket that doubts it, and this is the sweep behind the answer.

`tools/dosencumbrance.py` already prints both sides of the sum for one DOS
directory and sweeps the DOS records under the archives and `work/`.  This
tool asks the wider question the rule file rests on, and asks it of the whole
machine:

* **every port**, not DOS alone -- the Amiga's records carry the same field
  (Pool of Radiance at `0x056`, Curse at `0x18C`), and **the C64 record has
  no such field at all**, so a C64 save can never fail the identity and can
  never be judged by it.  That is printed rather than left implied.
* **every corpus** -- the archives, the played DOS directory, the specimen
  tree, `work/`, and the Amiga disk images -- each row graded by where it came
  from, because a record nobody watched being written is not evidence about
  what the engine does.
* **the direction of the miss**, because `#323`'s standing hypothesis is that
  a training fee always leaves the stored number *above* the sum and an edit
  leaves it *below*.  A count by sign is what tests that.

Three modes:

    tools/enccensus.py                    the census, every port
    tools/enccensus.py --stacks           every item stack whose cached
                                          display line disagrees with its
                                          quantity byte
    tools/enccensus.py --pair A B         two save directories, per character:
                                          money, stored encumbrance and the
                                          delta on each side

`--pair` is the training experiment: point it at two directories one game
action apart and it prints what the engine changed.  The nine rungs of
`#249 (Build a DOS party from creation and level it ourselves)`'s ladder are
the worked example.

Reads only.  Nothing here writes anything, on any disk or in any directory.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import sys
from dataclasses import dataclass, field

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from goldbox import amiga_later, amiga_por, amiga_port  # noqa: E402
from goldbox import dos_codec as gdos  # noqa: E402
from goldbox import dos_port as dl  # noqa: E402
from tools import (  # noqa: E402
    amigarecords,
    amigasavegame,
    amigasaves,
    dostailcensus,
)

#: Where a DOS record might be, beyond the archives `dostailcensus` finds:
#: this repository's `work/`, the specimen tree that outlives an emulator
#: slot, and the played DOS directory.  Copied from `tools/spellbookcensus.py`,
#: which had already worked out that the archives are not the whole corpus.
DOS_EXTRA = ("work", "~/wish-specimens", "~/dos_por_play")

#: How a record is graded, by where it was found, strongest claim first.  A
#: record found in two places takes the **worst** grade of the two: the
#: archives' `games/POOLRAD/GAME/POOLRAD/SAVE` is byte-identical to
#: `~/dos_por_play/SAVE`, every record in which has been through Gold Box
#: Companion's editor, so counting that copy as an untouched archive record
#: would launder it (`#323`).
GRADE_MARKERS = (("/dos_por_play/", "edited"),
                 ("/wish-specimens/", "spec"),
                 ("/work/", "work"))

#: Worst first.  `built` is ours and says nothing about the game; `edited` has
#: been through an editor; `found` was never watched being written; `work` and
#: `spec` name a run whose log says who wrote each file.
GRADE_ORDER = ("built", "edited", "found", "work", "spec")


@dataclass
class Row:
    """One character record and the two sides of its encumbrance identity."""

    port: str
    title: str
    where: str
    who: str
    stored: int
    coins: int
    carried: int
    items: int
    declared: int = 0
    grade: str = "found"
    paths: list[str] = field(default_factory=list)

    @property
    def delta(self) -> int:
        """Stored minus what the record's own parts add up to."""
        return self.stored - self.coins - self.carried

    @property
    def readable(self) -> bool:
        """Can the identity even be evaluated on this record?

        Only if every item the record says it owns was found.  A DOS export
        carries `item_count` and no `.ITM` beside it, and `read_character`
        gives it no items rather than failing -- so its money alone is
        compared against a stored total that includes items, and it "fails"
        by the whole weight of an inventory nobody can see.  Six Amiga `.cha`
        exports on the Curse save disk do exactly that, declaring 6 to 16
        items each; they are not evidence of anything and are counted apart.
        """
        return self.declared == self.items


def _grade(paths) -> str:
    """The strongest claim any of these paths makes about who wrote it.

    `GRADE_MARKERS` is in precedence order and the first marker any path
    matches wins, so a record that sits in the played DOS directory **and**
    in the archives grades `edited` rather than `found`: the archives'
    `games/POOLRAD/GAME/POOLRAD/SAVE` is byte-identical to
    `~/dos_por_play/SAVE`, and taking the archive copy's grade would launder
    it (`#323`).
    """
    texts = [pathlib.Path(p).as_posix() for p in paths]
    for marker, grade in GRADE_MARKERS:
        if any(marker in t for t in texts):
            return grade
    return "found"


def _carried(items) -> int:
    """The item half of the identity: sum(weight x quantity or 1).

    A quantity of zero means one -- the field counts *extra* copies for
    anything that does not stack, which is `goldbox.dos.expected_encumbrance`'s
    own rule and the only one the identity balances under.
    """
    return sum(it.get("weight") * (it.get("quantity") or 1) for it in items)


# --- DOS ---------------------------------------------------------------------

def dos_roots() -> list[pathlib.Path]:
    out = []
    archives = dostailcensus.archives()
    if archives is not None:
        out.append(archives)
    for name in DOS_EXTRA:
        p = pathlib.Path(name).expanduser()
        out.append(p if p.is_absolute() else ROOT / name)
    return out


def dos_rows(roots=None, want_built: bool = True):
    """Every distinct DOS record, read **with its item file**.

    `tools/dostailcensus.py`'s finder deduplicates on the record bytes alone,
    which is right for a field census and wrong here: the identity's other
    term is a sibling file, so two records with the same bytes and different
    `.ITM` files are two specimens.  So this walks the same roots with the
    same exclusions -- the scratch trees an emulator instance stages into, the
    Gateway and Treasures titles whose records are the same size as ones read
    here -- and keys on the record and its items together.
    """
    seen: dict[bytes, Row] = {}
    skipped: collections.Counter = collections.Counter()
    for root in roots if roots is not None else dos_roots():
        if not root.exists():
            continue
        walk = sorted(root.rglob("*")) if root.is_dir() else [root]
        for path in walk:
            if (not path.is_file()
                    or path.suffix.lower() not in dostailcensus.RECORD_SUFFIXES):
                continue
            if any(d in path.as_posix() for d in dostailcensus.SCRATCH_DIRS):
                continue
            try:
                if path.stat().st_size not in dl.DELTAS_BY_SIZE:
                    continue
            except OSError:                              # pragma: no cover
                continue
            other = dostailcensus.foreign_title(path)
            if other:
                skipped[other] += 1
                continue
            built = dostailcensus.is_built(path)
            if built and not want_built:
                continue
            try:
                char = gdos.read_character(path)
            except (gdos.DosRecordError, OSError, ValueError) as exc:
                skipped[f"unreadable: {exc}"] += 1
                continue
            key = bytes(char) + b"".join(bytes(i) for i in char.items)
            row = seen.get(key)
            if row is None:
                row = Row(port="dos", title=char.shape.key, where=path.name,
                          who=char.name or "(unnamed)",
                          stored=char.get("encumbrance"),
                          coins=sum(char.money.values()),
                          carried=_carried(char.items),
                          items=len(char.items),
                          declared=char.get("item_count"),
                          grade="built" if built else "found")
                seen[key] = row
            row.paths.append(str(path))
            if row.grade != "built":
                row.grade = _grade(row.paths)
    return list(seen.values()), skipped


# --- the Amiga ---------------------------------------------------------------

def amiga_rows():
    """Pool of Radiance's 288-byte records, then Curse's and Silver Blades'.

    Deduplicated on the record bytes together with its items', because several
    rips of the same disk are on this machine.
    """
    rows: list[Row] = []
    seen: set[bytes] = set()
    for label, volume, name, files in amigasaves.specimens():
        record = files.get("") or next(iter(files.values()))
        itm = files.get(".itm", b"")
        key = record + itm
        if key in seen:
            continue
        seen.add(key)
        try:
            char = amiga_por.por_character(record, itm, b"", source=label)
        except Exception:                                # pragma: no cover
            continue
        rows.append(Row(port="amiga", title="pool-of-radiance",
                        where=f"{volume}:{name}", who=char.name,
                        stored=char.get("encumbrance"),
                        coins=sum(char.money.values()),
                        carried=_carried(getattr(char, "items", ()) or ()),
                        items=len(getattr(char, "items", ()) or ()),
                        declared=char.get("item_count"),
                        grade="found", paths=[label]))
    for label, volume, name, data, what in amigarecords.specimens():
        for char in _amiga_later_characters(data, what, label):
            key = char.raw + b"".join(i.raw for i in (char.items or ()))
            if key in seen:
                continue
            seen.add(key)
            rows.append(Row(port="amiga", title=_amiga_key(char.shape),
                            where=f"{volume}:{name}", who=char.name,
                            stored=char.get("encumbrance"),
                            coins=sum(char.money.values()),
                            carried=_carried(char.items or ()),
                            items=len(char.items or ()),
                            declared=char.get("item_count"),
                            grade="found", paths=[label]))
    return rows


def _amiga_key(shape) -> str:
    return getattr(shape, "key", getattr(shape, "title", "?"))


def _amiga_later_characters(data: bytes, what: str, label: str):
    """The characters in one Curse or Silver Blades file, at its own shape.

    A saved game's shape comes from `amigasavegame.detect`, never from trying
    each shape in turn: the signature `party_in_savegame` scans for sits at
    the same offsets in both titles, so a Silver Blades save handed the Curse
    shape yields six characters read through the wrong table -- plausible
    rubbish rather than an error.  Copied from `tools/spellbookcensus.py`.
    """
    if what == "record":
        shape = amiga_port.AMIGA_DELTAS_BY_SIZE.get(len(data))
        if shape is None:                                # pragma: no cover
            for candidate in amiga_port.AMIGA_DELTAS:
                if amiga_later.looks_like_amiga_record(data, 0, candidate):
                    shape = candidate
                    break
        if shape is None:                                # pragma: no cover
            return
        yield amiga_later.AmigaCharacter.from_bytes(data[:shape.record_size], shape,
                                              source=label)
        return
    try:
        save = amigasavegame.parse(data, source=label)
    except Exception:                                    # pragma: no cover
        return
    yield from save.characters


# --- stacks ------------------------------------------------------------------

@dataclass
class Stack:
    """One item whose cached display line leads with a number."""

    port: str
    title: str
    where: str
    who: str
    line: str
    shown: int
    quantity: int
    weight: int

    @property
    def agrees(self) -> bool:
        return self.shown == self.quantity


def leading_number(text: str) -> int | None:
    """The count a cached inventory line opens with, or None.

    The game writes the line when it last recomputed the character, so the
    number in it and the quantity byte are two readings of the same thing
    taken at different times.  `37 Darts` over a quantity byte of 50 is the
    disagreement `docs/125-bug-notes.md` N19 is about.
    """
    head = text.strip().split(" ", 1)[0]
    return int(head) if head.isdigit() else None


def stacks(rows_source=None) -> list[Stack]:
    """Every item on this machine whose display line carries a count."""
    out: list[Stack] = []
    specs, _skipped = dos_rows()
    seen: set[str] = set()
    for row in specs:
        char = gdos.read_character(pathlib.Path(row.paths[0]))
        for it in char.items:
            shown = leading_number(it.display_line)
            if shown is None:
                continue
            key = f"{row.who}:{it.display_line}:{it.get('quantity')}"
            if key in seen:
                continue
            seen.add(key)
            out.append(Stack(port="dos", title=row.title, where=row.where,
                             who=row.who, line=it.display_line.strip(),
                             shown=shown, quantity=it.get("quantity"),
                             weight=it.get("weight")))
    for label, volume, name, files in amigasaves.specimens():
        record = files.get("") or next(iter(files.values()))
        itm = files.get(".itm", b"")
        if not itm:
            continue
        try:
            char = amiga_por.por_character(record, itm, b"", source=label)
        except Exception:                                # pragma: no cover
            continue
        for it in getattr(char, "items", ()) or ():
            shown = leading_number(it.display_line)
            if shown is None:
                continue
            key = f"amiga:{char.name}:{it.display_line}:{it.get('quantity')}"
            if key in seen:
                continue
            seen.add(key)
            out.append(Stack(port="amiga", title="pool-of-radiance",
                             where=f"{volume}:{name}", who=char.name,
                             line=it.display_line.strip(), shown=shown,
                             quantity=it.get("quantity"),
                             weight=it.get("weight")))
    return out


# --- reporting ---------------------------------------------------------------

C64_NOTE = (
    "c64: the C64 character record has no encumbrance field -- "
    "`goldbox/c64_codec.py`'s DROPPED table calls it derived, and the engine "
    "recomputes what it needs. No C64 save can fail this identity, so no C64 "
    "save can be judged by it."
)


def report(rows: list[Row], verbose: bool = False) -> None:
    unreadable = [r for r in rows if not r.readable]
    rows = [r for r in rows if r.readable]
    by: dict[tuple[str, str], list[Row]] = collections.defaultdict(list)
    for row in rows:
        by[(row.port, row.title)].append(row)
    print(f"{len(rows)} distinct records the identity can be evaluated on, "
          f"{len(by)} port/title pairs")
    print(f"{len(unreadable)} set apart: the record declares items whose "
          f"file is not beside it, so neither side of the sum is known\n")
    header = (f"{'port':6s} {'title':28s} {'recs':>5s} {'exact':>6s} "
              f"{'above':>6s} {'below':>6s} {'worst +':>8s} {'worst -':>8s}")
    print(header)
    print("-" * len(header))
    for (port, title), group in sorted(by.items()):
        above = [r for r in group if r.delta > 0]
        below = [r for r in group if r.delta < 0]
        print(f"{port:6s} {title:28s} {len(group):5d} "
              f"{len(group) - len(above) - len(below):6d} "
              f"{len(above):6d} {len(below):6d} "
              f"{max((r.delta for r in above), default=0):8d} "
              f"{min((r.delta for r in below), default=0):8d}")
    print(f"\n{C64_NOTE}\n")

    print("by provenance:")
    grades: dict[str, list[Row]] = collections.defaultdict(list)
    for row in rows:
        grades[row.grade].append(row)
    for grade in GRADE_ORDER:
        group = grades.get(grade)
        if not group:
            continue
        miss = [r for r in group if r.delta]
        print(f"  {grade:7s} {len(group):4d} records, {len(miss)} miss "
              f"({len([r for r in miss if r.delta > 0])} above, "
              f"{len([r for r in miss if r.delta < 0])} below)")
    print()
    misses = sorted((r for r in rows if r.delta), key=lambda r: -abs(r.delta))
    print(f"{len(misses)} record(s) miss:")
    for row in misses if verbose else misses[:60]:
        print(f"  {row.delta:+7d}  {row.grade:7s} {row.port:6s} "
              f"{row.title:22s} {row.who:16s} stored={row.stored:6d} "
              f"coins={row.coins:6d} items={row.carried:5d} n={row.items} "
              f"{row.where}")
    if not verbose and len(misses) > 60:
        print(f"  ... {len(misses) - 60} more; --verbose for all")
    if unreadable:
        print(f"\nset apart, {len(unreadable)} record(s) whose items are not "
              f"on this machine:")
        for row in sorted(unreadable, key=lambda r: -r.declared):
            print(f"  declares {row.declared:3d} items, {row.items} found  "
                  f"{row.grade:7s} {row.port:6s} {row.title:22s} "
                  f"{row.who:16s} stored={row.stored:6d} coins={row.coins:6d} "
                  f"{row.where}")


def report_stacks(found: list[Stack]) -> None:
    bad = [s for s in found if not s.agrees]
    print(f"{len(found)} item stack(s) whose display line carries a count; "
          f"{len(bad)} disagree with the quantity byte\n")
    for s in sorted(found, key=lambda s: (s.agrees, s.port, s.who)):
        mark = "  " if s.agrees else "!!"
        print(f"{mark} {s.port:6s} {s.who:16s} shown={s.shown:4d} "
              f"quantity={s.quantity:4d} weight={s.weight:4d} "
              f"gap={(s.quantity - s.shown) * s.weight:+6d}  "
              f"{s.line!r}  {s.where}")


def report_pair(left: pathlib.Path, right: pathlib.Path) -> None:
    """Two save directories, per character, on both sides of the identity."""
    def read(folder):
        out = {}
        for path in sorted(folder.glob("*")):
            if path.suffix.lower() not in dostailcensus.RECORD_SUFFIXES:
                continue
            try:
                char = gdos.read_character(path)
            except (gdos.DosRecordError, OSError, ValueError):
                continue
            out[char.name] = char
        return out

    a, b = read(left), read(right)
    print(f"{left}\n{right}\n")
    header = (f"{'who':16s} {'money':>8s} {'->':>8s} {'stored':>8s} {'->':>8s} "
              f"{'d money':>8s} {'d stored':>9s} {'delta':>7s} {'->':>7s}")
    print(header)
    print("-" * len(header))
    for who in sorted(set(a) & set(b)):
        ca, cb = a[who], b[who]
        ma, mb = sum(ca.money.values()), sum(cb.money.values())
        ia, ib = _carried(ca.items), _carried(cb.items)
        sa, sb = ca.get("encumbrance"), cb.get("encumbrance")
        print(f"{who:16s} {ma:8d} {mb:8d} {sa:8d} {sb:8d} "
              f"{mb - ma:+8d} {sb - sa:+9d} {sa - ma - ia:+7d} "
              f"{sb - mb - ib:+7d}")
    only = sorted(set(a) ^ set(b))
    if only:
        print("\nin one side only: " + ", ".join(only))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stacks", action="store_true",
                    help="every item stack whose display line carries a count")
    ap.add_argument("--pair", nargs=2, metavar=("BEFORE", "AFTER"),
                    type=pathlib.Path,
                    help="two save directories, one game action apart")
    ap.add_argument("--dos-only", action="store_true")
    ap.add_argument("--amiga-only", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="list every miss, not the largest sixty")
    args = ap.parse_args(argv)

    if args.pair:
        report_pair(*args.pair)
        return 0
    if args.stacks:
        report_stacks(stacks())
        return 0

    rows: list[Row] = []
    if not args.amiga_only:
        dos, skipped = dos_rows()
        rows += dos
        for other, n in sorted(skipped.items()):
            print(f"  skipped {n}: {other}")
    if not args.dos_only:
        rows += amiga_rows()
    report(rows, verbose=args.verbose)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
