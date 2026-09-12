#!/usr/bin/env python3
"""Who has a spellbook, and does anything set the id the C64 mask cannot hold?

Pool of Radiance names 56 spells and its C64 record spends seven bytes on the
book of spells a character *knows* -- 56 bits, of which bit 0 is spell id 0 and
does not exist, so ids 1-55 have a bit and id 56, `RESTORATION`, does not.  DOS
spends one byte per spell for the same ids and *does* have a slot for 56, at
record `0x06A`.  So a DOS-to-C64 conversion has somewhere to lose it, and
`#411 (Nobody knows whether a converted cleric loses Restoration, because the
spellbook field is one bit short of the game's own spell list)` asks two
questions this answers off the corpus, with no emulator:

1. does any **cleric** carry a spellbook at all, or is the field the
   magic-user's alone?
2. does any record **anywhere** set id 56?

    tools/spellbookcensus.py                  all three ports
    tools/spellbookcensus.py --c64 --verbose  one port, one line per record
    tools/spellbookcensus.py --ids 56 57      ask about other ids as well

Each row is graded by where it came from -- `GRADE_MARKERS` below has the five
-- because `.claude/rules/testing.md` is clear that a record nobody watched
being written is not evidence about the game.  A `found` record with a bit set
would say the bit is *storable*; only a record the engine wrote says the engine
sets it.

The DOS half reuses `tools/dostailcensus.py`'s finder and its exclusions (an
emulator instance's staged tree, and records we wrote), widened to the
specimen tree and the played DOS directory the way `tools/neveradventured.py`
widens its roots.  The C64 half reads every save disk `tools/gamedisks.py`
finds plus the specimen tree; the Amiga half reads the records out of the disk
images through `tools/amigasaves.py` and `tools/amigarecords.py`.

Reads only.  Nothing here writes anything, on any disk.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import sys
from dataclasses import dataclass

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
# The repository root and nothing else.  Putting `tools/` on `sys.path` is
# what `#262 (Thirty-three tools still leave tools/ on sys.path, so one run
# directly can lose the wish package)` removed from every tool here, and
# `tests/test_toolshadowing.py` parametrises over all of them; the siblings
# below come through the package instead.
sys.path.insert(0, str(ROOT))

from goldbox import amiga_later, amiga_por, amiga_port, c64_port, spells  # noqa: E402
from goldbox import dos_port as dl  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.savegame import load_save  # noqa: E402
from tools import (  # noqa: E402
    amigarecords,
    amigasavegame,
    amigasaves,
    dostailcensus,
    gamedisks,
)

#: The C64 record's spellbook, both declared halves: seven bytes Pool of
#: Radiance reads and the nine the later titles continue into.  Read as one
#: sixteen-byte window here on purpose -- the question is whether anything is
#: set *past* what a title reads, so the sweep must look past it.
C64_BOOK = 0x078
C64_BOOK_BYTES = 16

#: The C64 class bitmask.  `goldbox/strength.py` calls the same offset
#: `RECORD_CLASS_BITS`.
C64_CLASS_BITS = 0x0EB

#: Which C64 titles to sweep, by the key that finds their disks.
C64_DISKS = ("pool-of-radiance", "curse-of-the-azure-bonds",
             "secret-of-the-silver-blades")

#: Where a DOS record might be, beyond `dostailcensus`' archives: the specimen
#: tree that outlives an emulator slot, this repository's `work/`, and the
#: played DOS directory.  Copied from `tools/neveradventured.py`, which had
#: already worked out that the archives are not the whole corpus.
DOS_EXTRA = ("work", "~/wish-specimens", "~/dos_por_play")

#: `(offset, slots)` of the C64 memorised-spell list, per title.  **Not the
#: `goldbox/layout.py` field**, which is declared at the 69 bytes every
#: measured title shares: each game's own `CAMP` walks its list with a
#: count-down loop whose immediate is the last index, so Pool of Radiance has
#: 81 slots at `0x020`, Curse 69 at `0x020` and Silver Blades 74 at `0x01B`.
#: All three CONFIRMED and read out of the disks by `tools/memorisedwidth.py`.
C64_MEMORISED = {"pool-of-radiance": (0x020, 81),
                 "curse-of-the-azure-bonds": (0x020, 69),
                 "secret-of-the-silver-blades": (0x01B, 74)}

#: How a record is graded, by where it was found.  A grading, never an
#: exclusion: a record we wrote can still show that a value *fits*, and it can
#: never show that the engine writes it.
#:
#: * `built` -- one of this project's writers made it (`dostailcensus.is_built`)
#: * `spec`  -- the specimen tree, which records who made each save and how
#: * `work`  -- a run's output: engine-written under our watch, or ours, and
#:   which of those is in the run's own log rather than in the bytes
#: * `edited` -- the played DOS directory, every record in which has been
#:   through Gold Box Companion's editor (`.claude/rules/testing.md`)
#: * `found` -- the archives and the game disks: nobody watched it being
#:   written, so it is not evidence about what the engine does
GRADE_MARKERS = (("/wish-specimens/", "spec"),
                 ("/dos_por_play/", "edited"),
                 ("/work/", "work"))


@dataclass
class Row:
    """One character record, and what its book of known spells holds."""

    port: str
    title: str                    # the game key
    where: str
    who: str
    klass: str
    known: tuple[int, ...] = ()   # every id set, read as wide as the container
    reach: int = 0                # the highest id this title's C64 mask holds
    last_spell: int = 0           # the highest id this title names a spell for
    grade: str = "found"
    raw_tail: bytes = b""         # the bytes past the title's own mask, C64
    #: The ids in the *memorised* list, which is a list of ids rather than a
    #: mask and so has room for every id the title names.  Swept beside the
    #: book because "the game never hands this spell out" is a claim about
    #: both fields, and only one of them is short.
    memorised: tuple[int, ...] = ()
    #: Whether `goldbox/spells.py` has a table for this title at all.  Three
    #: of the six C64 titles have none -- Champions of Krynn, Death Knights of
    #: Krynn and Gateway to the Savage Frontier -- and `spells.for_game`
    #: answers Pool of Radiance's table for any key it does not know.  Reading
    #: a Krynn book against a 55-spell ceiling reports ids "past the mask"
    #: that are simply spells in a list nobody here has read, so those rows
    #: are counted and named rather than measured.
    has_table: bool = True

    @property
    def beyond(self) -> tuple[int, ...]:
        """Ids set above what the title's C64 seven-byte mask can express."""
        if not self.has_table:
            return ()
        return tuple(i for i in self.known if i > self.reach)

    @property
    def is_cleric(self) -> bool:
        return "cleric" in self.klass

    @property
    def is_caster(self) -> bool:
        return any(w in self.klass for w in
                   ("cleric", "mage", "magic-user", "druid", "ranger",
                    "paladin"))


def _grade(path: str) -> str:
    text = pathlib.Path(path).as_posix()
    for marker, grade in GRADE_MARKERS:
        if marker in text:
            return grade
    return "found"


def _grade_over(paths) -> str:
    """The grade for one record that turned up at several paths.

    `tools/dostailcensus.py` deduplicates on the record's bytes and keeps every
    path it saw, and its roots are searched in a fixed order -- so a record
    that is both a copy in `work/` and the specimen it was copied into gets
    whichever sorted first.  The specimen tree decides when any path is in it,
    because that is the one with a `provenance.toml` behind it; the played
    directory decides next, because a record that was edited is edited
    wherever else it also sits.  `tools/carryceiling.py` hit this first, on
    THRENDER GRONE.
    """
    grades = [_grade(str(p)) for p in paths]
    for want in ("spec", "edited", "found", "work"):
        if want in grades:
            return want
    return "found"


def _class_name_c64(bits: int, game) -> str:
    names = [n for bit, n in game.class_bits if bits & bit]
    return "/".join(names) if names else f"bits ${bits:02X}"


def _class_name_dos(code) -> str:
    if isinstance(code, int) and code < len(dl.CLASS_NUMBERS):
        return dl.CLASS_NUMBERS[code]
    return f"class {code}"


def _ids_from_mask(mask: bytes, first_id: int = 0) -> tuple[int, ...]:
    """Every id set in a bitmask, bit (id & 7) of byte (id >> 3)."""
    return tuple(i for i in range(8 * len(mask))
                 if mask[i >> 3] >> (i & 7) & 1 and i >= first_id)


def _c64_memorised(raw: bytes, key: str) -> tuple[int, ...]:
    """The ids in one C64 record's memorised list, at the title's own width."""
    at, slots = C64_MEMORISED.get(key, (0x020, 69))
    return tuple(sorted(set(raw[at:at + slots]) - {0}))


def _nonzero(fields, data: bytes, _unused: int) -> tuple[int, ...]:
    """The ids in a DOS record's memorised list, which is a list of ids."""
    f = fields.get("spells_memorised")
    if f is None:                                        # pragma: no cover
        return ()
    return tuple(sorted(set(data[f.offset:f.offset + f.size]) - {0}))


# --- the C64 -----------------------------------------------------------------

def c64_disks(extra_disks=()) -> list[pathlib.Path]:
    """Every C64 disk image to look in, deduplicated on its resolved path.

    The registry's three title directories **and their parents**: Champions of
    Krynn, Death Knights of Krynn and Gateway to the Savage Frontier are three
    of Wish's six C64 titles and none has a `gamedisks.toml` entry, so a sweep
    of the registry alone covers half the titles and says nothing about it.
    On this machine the other three sit beside the registered ones under
    `/mnt/media/roms/c64`.  An image with no saved game costs one read and is
    skipped; a title `goldbox/c64_save.py` has no container for is skipped the
    same way, which is why the report says how many images were unreadable.
    Copied from `tools/carryceiling.py`, which worked this out first.
    """
    paths: list[pathlib.Path] = []
    for key in C64_DISKS:
        where = gamedisks.find(key)
        if where:
            where = pathlib.Path(where)
            paths += sorted(where.glob("*.[dD]64"))
            paths += sorted(where.parent.rglob("*.[dD]64"))
    root = _specimen_root()
    if root is not None:
        paths += sorted(root.glob("*/WISH-SPEC-*.[dD]64"))
        paths += sorted(root.glob("*/WISH-SPEC-*.d64"))
    paths += sorted((ROOT / "work").rglob("*.[dD]64"))
    paths += [pathlib.Path(p) for p in extra_disks]
    out: dict[str, pathlib.Path] = {}
    for path in paths:
        out.setdefault(str(path.resolve()), path)
    return list(out.values())


def c64_rows(extra_disks=(), unreadable: list[str] | None = None):
    """Every C64 character record this machine can reach."""
    seen: set[tuple[str, bytes]] = set()
    for path in c64_disks(extra_disks):
        try:
            disk = D64.open(str(path))
            game, sg0, _sg1 = load_save(disk)
        except Exception as exc:
            if unreadable is not None and "no save" not in str(exc).lower():
                unreadable.append(f"{path.name}: {exc}")
            continue                     # not every image carries a save
        table = spells.for_game(game)
        known = game.key in spells.BY_KEY
        for slot in sg0.slots:
            record = slot.record
            if record is None:
                continue
            raw = record.to_bytes()
            key = (game.key, raw)
            if key in seen:
                continue
            seen.add(key)
            book = raw[C64_BOOK:C64_BOOK + C64_BOOK_BYTES]
            yield Row(port="c64", title=game.key, where=f"{path.name}:{slot.index}",
                      who=record.name or "(unnamed)",
                      klass=_class_name_c64(raw[C64_CLASS_BITS], game),
                      known=_ids_from_mask(book, first_id=1),
                      reach=table.last_spellbook_spell,
                      last_spell=table.last_spell,
                      grade=_grade(str(path)),
                      raw_tail=book[table.spellbook_size:] if known else b"",
                      memorised=_c64_memorised(raw, game.key),
                      has_table=known)


def _specimen_root():
    try:
        from tools import specimens
    except Exception:                                    # pragma: no cover
        return None
    root = specimens.tree_root()
    return pathlib.Path(root) if root and pathlib.Path(root).is_dir() else None


# --- DOS ---------------------------------------------------------------------

def dos_roots() -> list[pathlib.Path]:
    repo = pathlib.Path(__file__).resolve().parent.parent
    out = []
    archives = dostailcensus.archives()
    if archives is not None:
        out.append(archives)
    for name in DOS_EXTRA:
        p = pathlib.Path(name).expanduser()
        out.append(p if p.is_absolute() else repo / name)
    return out


def dos_rows(want_built: bool = True):
    """Every distinct DOS record, deduplicated on its bytes by the finder."""
    specs, skipped = dostailcensus.collect(dos_roots(), want_built)
    for spec in specs:
        f = dl.FIELDS_BY_NAME_FOR[spec.shape.key].get("spellbook")
        if f is None:                                    # pragma: no cover
            continue
        raw = spec.data[f.offset:f.offset + f.size]
        table = _table_for_key(spec.shape.key)
        yield Row(port="dos", title=spec.shape.key, where=spec.path.name,
                  who=spec.name,
                  klass=_class_name_dos(spec.klass),
                  known=tuple(i + dl.SPELLBOOK_FIRST_ID
                              for i, v in enumerate(raw) if v),
                  reach=table.last_spellbook_spell if table else f.size,
                  last_spell=table.last_spell if table else f.size,
                  grade="built" if spec.built else _grade_over(spec.paths),
                  memorised=_nonzero(dl.FIELDS_BY_NAME_FOR[spec.shape.key],
                                     spec.data, 0))
    for other, n in sorted(skipped.items()):
        print(f"  skipped {n} DOS record(s) under {other}: the same record "
              f"size as a title read here, and not the same id space")


def _table_for_key(key: str):
    try:
        return spells.for_game(c64_port.by_key(key))
    except Exception:
        return None


# --- the Amiga ---------------------------------------------------------------

def amiga_rows():
    """Pool of Radiance's 288-byte records, then Curse's and Silver Blades'.

    Deduplicated on the record bytes, because several rips of the same disk
    are on this machine and `tools/amigasaves.py` proves their save drawers
    byte-identical: counting them twice would inflate every number here.
    """
    por = spells.POOL_OF_RADIANCE
    book = dl.FIELDS_BY_NAME["spellbook"]
    seen: set[bytes] = set()
    for label, volume, name, files in amigasaves.specimens():
        record = next(iter(files.values()))
        if record in seen:
            continue
        seen.add(record)
        char = amiga_por.AmigaPorCharacter.from_bytes(record, source=label)
        raw = char.get("spellbook")
        yield Row(port="amiga", title="pool-of-radiance",
                  where=f"{volume}:{name}", who=char.name,
                  klass=_class_name_dos(char.get("char_class")),
                  known=tuple(i + dl.SPELLBOOK_FIRST_ID
                              for i, v in enumerate(raw) if v),
                  reach=por.last_spellbook_spell, last_spell=por.last_spell,
                  grade="found",
                  memorised=tuple(sorted(set(char.get("spells_memorised"))
                                         - {0})))
        assert book.offset == 0x033                      # the shift is zero here
    for label, volume, name, data, what in amigarecords.specimens():
        for char in _amiga_later_characters(data, what, label):
            if char.raw in seen:
                continue
            seen.add(char.raw)
            table = _table_for_key(_amiga_key(char.shape))
            yield Row(port="amiga", title=_amiga_key(char.shape),
                      where=f"{volume}:{name}", who=char.name,
                      klass=_class_name_dos(char.get("char_class")),
                      known=tuple(char.spellbook),
                      reach=table.last_spellbook_spell if table else 0,
                      last_spell=table.last_spell if table else 0,
                      grade="found",
                      memorised=tuple(sorted(
                          set(char.get("spells_memorised")) - {0})))


def _amiga_key(shape) -> str:
    return getattr(shape, "key", getattr(shape, "title", "?"))


def _amiga_later_characters(data: bytes, what: str, label: str):
    """The characters in one Curse or Silver Blades file, at its own shape.

    A saved game's shape comes from `amigasavegame.detect`, never from trying
    `party_in_savegame` with each shape in turn: the record signature it scans
    for is the name and the ability pairs, which sit at the same offsets in
    both titles, so a Silver Blades save handed the Curse shape yields six
    characters read through the wrong table -- plausible rubbish rather than
    an error.  A `.guy`-style record file is named by its size, which is
    distinct between the two.
    """
    if what == "record":
        shape = amiga_port.AMIGA_DELTAS_BY_SIZE.get(len(data))
        if shape is None:
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


# --- the unfiltered control -------------------------------------------------

def control_sweep(roots=None) -> tuple[int, list[tuple[pathlib.Path, str]]]:
    """Every DOS record file on the machine, raw: no dedup, no exclusions.

    The census above deduplicates, skips an emulator instance's staged tree
    and skips titles it has no layout for, and each of those is a way for a
    counterexample to be excluded rather than absent.  This reads every file
    whose size is one of the four record sizes and asks one question of it --
    is the byte for spell id 56 set? -- so a "nothing anywhere has it" claim
    does not rest on the census's own filters.  `tools/carryceiling.py` is
    where the practice comes from.

    Returns a count of files read per title and every hit as `(path, title)`.
    """
    read: collections.Counter = collections.Counter()
    hits: list[tuple[pathlib.Path, str]] = []
    for root in (roots if roots is not None else dos_roots()):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if (not path.is_file()
                    or path.suffix.lower() not in dostailcensus.RECORD_SUFFIXES):
                continue
            try:
                size = path.stat().st_size
            except OSError:                              # pragma: no cover
                continue
            shape = dl.DELTAS_BY_SIZE.get(size)
            if shape is None:
                continue
            book = dl.FIELDS_BY_NAME_FOR[shape.key].get("spellbook")
            if book is None:                             # pragma: no cover
                continue
            data = path.read_bytes()
            read[shape.key] += 1
            at = book.offset + (56 - dl.SPELLBOOK_FIRST_ID)
            if at < book.offset + book.size and data[at]:
                hits.append((path, shape.key))
    return read, hits


# --- reporting ---------------------------------------------------------------

def report(rows: list[Row], ids: list[int], verbose: bool = False) -> None:
    by = collections.defaultdict(list)
    for row in rows:
        by[(row.port, row.title)].append(row)
    print(f"{len(rows)} records, {len(by)} port/title pairs\n")
    header = (f"{'port':5s} {'title':28s} {'recs':>5s} {'clerics':>8s} "
              f"{'w/book':>7s} {'cleric w/book':>13s} {'past mask':>10s} "
              f"{'top id':>7s} {'top memo':>9s}")
    print(header)
    print("-" * len(header))
    for (port, title), group in sorted(by.items()):
        clerics = [r for r in group if r.is_cleric]
        with_book = [r for r in group if r.known]
        cleric_book = [r for r in clerics if r.known]
        past = [r for r in group if r.beyond]
        top = max((max(r.known) for r in with_book), default=0)
        untabled = "  (no spell table for this title)" if not group[0].has_table else ""
        memo = max((max(r.memorised) for r in group if r.memorised), default=0)
        print(f"{port:5s} {title:28s} {len(group):5d} {len(clerics):8d} "
              f"{len(with_book):7d} {len(cleric_book):13d} {len(past):10d} "
              f"{top:7d} {memo:9d}{untabled}")
    print("\n`top id` is the highest id any book in the group sets and "
          "`top memo` the highest\nid any memorised list holds -- the whole "
          "question is whether either reaches 56.\n")
    for spell in ids:
        memorised = [r for r in rows if spell in r.memorised]
        print(f"spell id {spell}: memorised in {len(memorised)} of "
              f"{len(rows)} records")
        for row in memorised:
            print(f"    memo  {row.grade:6s} {row.port:5s} {row.title:28s} "
                  f"{row.who:16s} {row.klass:20s} {row.where}")
        hits = [r for r in rows if spell in r.known]
        print(f"spell id {spell}: known in {len(hits)} of {len(rows)} records")
        for row in hits:
            print(f"    {row.grade:5s} {row.port:5s} {row.title:28s} "
                  f"{row.who:16s} {row.klass:20s} {row.where}")
    print()
    grades = collections.Counter(r.grade for r in rows)
    print("provenance:", dict(sorted(grades.items())),
          "-- `found` is a record nobody watched being written")
    tails = [r for r in rows if r.port == "c64" and any(r.raw_tail)]
    print(f"C64 records with a non-zero byte past their own mask: {len(tails)}")
    for row in tails:
        print(f"    {row.who:16s} {row.title:28s} {row.where} "
              f"{row.raw_tail.hex(' ')}")
    if verbose:
        print()
        for row in sorted(rows, key=lambda r: (r.port, r.title, r.who)):
            ids_text = ",".join(str(i) for i in row.known) or "-"
            print(f"{row.grade:5s} {row.port:5s} {row.title:28s} "
                  f"{row.who:16s} {row.klass:22s} {len(row.known):3d}  "
                  f"{ids_text}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--c64", action="store_true", help="the C64 half only")
    ap.add_argument("--dos", action="store_true", help="the DOS half only")
    ap.add_argument("--amiga", action="store_true", help="the Amiga half only")
    ap.add_argument("--disk", action="append", default=[],
                    help="another C64 disk image to include; repeatable")
    ap.add_argument("--ids", type=int, nargs="*", default=[56],
                    help="which spell ids to ask about (default 56)")
    ap.add_argument("--no-built", action="store_true",
                    help="leave out the DOS records this project wrote")
    ap.add_argument("--verbose", action="store_true",
                    help="one line per record")
    ap.add_argument("--control", action="store_true",
                    help="also read every DOS record file raw, with no "
                         "deduplication and no exclusions")
    args = ap.parse_args(argv)
    want = (args.c64, args.dos, args.amiga)
    if not any(want):
        want = (True, True, True)
    rows: list[Row] = []
    if want[0]:
        rows += list(c64_rows(args.disk))
    if want[1]:
        rows += list(dos_rows(not args.no_built))
    if want[2]:
        rows += list(amiga_rows())
    report(rows, args.ids, args.verbose)
    if args.control:
        read, hits = control_sweep()
        print(f"\nunfiltered control: {sum(read.values())} DOS record files "
              f"read raw, {len(hits)} with the id-56 byte set")
        for title, n in sorted(read.items()):
            print(f"    {title:28s} {n:5d} files")
        for path, title in hits:
            print(f"    {title:28s} {path}")
    return 0


if __name__ == "__main__":                               # pragma: no cover
    raise SystemExit(main())
