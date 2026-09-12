#!/usr/bin/env python3
"""How close any real character comes to the C64's item and trait ceilings (#399).

`.claude/rules/conversions.md`: where a limit is genuinely the destination
platform's design, the converter says what will not fit and lets the player
choose what to keep -- **and that chooser is not built until a measurement
says it is reachable**.  `#399 (A conversion that runs out of item or trait
slots tells the player nothing, because the pane never shows a warning)` then
asked the same question one step earlier, of the *sentence*: Donald,
2026-09-07, *"why does your scenario have a DOS save with 20 items on a
character if it is not been measured. Put in the ticket to measure it."*

Two ceilings, both in the C64 character record:

* **sixteen item slots** -- one `$100` item page per character at sixteen
  bytes an item (`goldbox/items.py`'s `ITEM_BLOCK_STRIDE // ITEM_SIZE`, and
  `goldbox/c64_save.py`'s `Container.items`).  A DOS or Amiga character keeps
  its items in a sibling file with a one-byte count, so the *format* there
  allows up to 255.
* **ten trait slots** at record `0x0AD`-`0x0B6` (`goldbox/traits.py`'s
  `SLOTS`, `docs/171-c64-trait-slots.md`), shared between racial effects and
  item grants.  Racial ids run 0 to 4 by race (`#84 (Roll a gnome in DOS and
  read the two innate effect ids nobody has seen)`), so overflowing needs a
  dwarf or a gnome carrying seven or more effect-granting items readied.

    tools/carryceiling.py                 the whole census
    tools/carryceiling.py --items         the item census only
    tools/carryceiling.py --grants        the effect-granting templates only
    tools/carryceiling.py --census        the per-port census only
    tools/carryceiling.py --json FILE     one JSON row per character found

**What it counts and what it does not.**  It counts what is on the disks:
item entries and trait bytes in a C64 saved game, `item_count` and `.SPC`
records beside a DOS one, item nodes and effect nodes in an Amiga one.  It
does not watch the running game refuse a pickup -- an engine's own ceiling is
a comparison in an overlay -- so where a census reaches a ceiling it says the
population reached it and not that the engine allows it.

**Provenance is part of every count.**  `.claude/rules/testing.md`: a save
found on a disk has no chain of custody, and a record this project's own
writers produced carries what we already believe.  Every row is graded
`engine` (a specimen made by driving the game and not edited afterwards),
`edited` (a specimen whose `provenance.toml` says `edited_afterwards`, or
Donald's own play directory), `ours` (something a Wish writer produced), or
`found` (a disk or an archive nobody watched being written).  The headline
maxima are reported per grade, never pooled.

Nothing here prints an item name of the game's; the output is counts, ids and
byte values.
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import json
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import c64_port, dos_codec, dos_port  # noqa: E402
from goldbox import items as c64items  # noqa: E402
from goldbox.d64 import D64, split_load_address  # noqa: E402
from tools import gamedisks  # noqa: E402

#: Item record byte `+15`, bit 7: "readying this dispatches a power handler".
#: `CAMP $10B5` is `LDA $6D8B / BPL`, so an item without it is refused with
#: `NOT HERE` and grants nothing (`docs/125-bug-notes.md` U4).
GRANT_FLAG_AT, GRANT_FLAG_BIT = 15, 0x80
#: Byte `+14`, the effect id the grant writes into a free trait slot.
GRANT_ID_AT = 14

#: The C64 titles with a disk glob in the registry, and their registry keys.
C64_TITLES = (
    (c64_port.POOL_OF_RADIANCE, "pool-of-radiance"),
    (c64_port.CURSE_OF_THE_AZURE_BONDS, "curse-of-the-azure-bonds"),
    (c64_port.SECRET_OF_THE_SILVER_BLADES, "secret-of-the-silver-blades"),
)


def grant_templates(disks: pathlib.Path, game) -> dict[bytes, int]:
    """Every distinct item template on a title's sides that sets the bit.

    Keyed by the sixteen raw bytes so two identical templates on two sides
    count once, valued by the effect id at `+14`.
    """
    out: dict[bytes, int] = {}
    for path in sorted(disks.glob(game.disk_glob)):
        try:
            img = D64.open(str(path))
        except Exception:
            continue
        for entry in img.directory():
            if not c64items.is_item_list(entry.name):
                continue
            try:
                _, payload = split_load_address(img.read_file(entry))
            except Exception:
                continue
            for i in range(len(payload) // c64items.ITEM_SIZE):
                raw = bytes(payload[i * c64items.ITEM_SIZE:
                                    (i + 1) * c64items.ITEM_SIZE])
                if not any(raw):
                    continue
                if raw[GRANT_FLAG_AT] & GRANT_FLAG_BIT:
                    out[raw] = raw[GRANT_ID_AT]
    return out


def all_templates(disks: pathlib.Path, game) -> int:
    """How many distinct templates the sides carry at all, for the ratio."""
    seen: set[bytes] = set()
    for path in sorted(disks.glob(game.disk_glob)):
        try:
            img = D64.open(str(path))
        except Exception:
            continue
        for entry in img.directory():
            if not c64items.is_item_list(entry.name):
                continue
            try:
                _, payload = split_load_address(img.read_file(entry))
            except Exception:
                continue
            for i in range(len(payload) // c64items.ITEM_SIZE):
                raw = bytes(payload[i * c64items.ITEM_SIZE:
                                    (i + 1) * c64items.ITEM_SIZE])
                if any(raw):
                    seen.add(raw)
    return len(seen)




# ---------------------------------------------------------------------------
# The census: how much any real character actually carries
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Carried:
    """One character, and how much of each ceiling it would take up."""

    port: str                      # c64 | dos | amiga
    title: str                     # the registry key
    grade: str                     # engine | edited | ours | found
    where: str                     # disk or file the record came from
    who: str                       # the character's name
    items: int                     # items carried
    #: The C64 record's own occupied trait slots.  `None` off the C64, where
    #: the two halves below are counted separately instead.
    traits: int | None = None
    #: A `.SPC`/effect-chain id this title's own innate set names, and one it
    #: does not that never expires -- an item's grant.  Together they are what
    #: `goldbox/c64_codec.py`'s `write` tries to fit into the ten slots.
    innate: int = 0
    granted: int = 0
    #: Records that are neither: a spell counting down, which never crosses
    #: and is never reported (`goldbox/dos.py`, Donald 2026-08-27).
    running: int = 0
    #: Every path this record's bytes were found at, for `--json`.  The table
    #: prints `where`; a claim about provenance needs the whole path.
    sources: tuple[str, ...] = ()

    @property
    def trait_demand(self) -> int:
        """How many of the ten C64 trait slots this character wants."""
        return self.traits if self.traits is not None else self.innate + self.granted


#: Where a DOS or Amiga record might be, beyond the archives: the specimen
#: tree that outlives an emulator slot, this repository's `work/`, and the
#: played DOS directory.  Copied from `tools/spellbookcensus.py`, which had
#: already worked out that the archives are not the whole corpus.
DOS_EXTRA = ("work", "~/wish-specimens", "~/dos_por_play")

#: Every character record in here has been edited with Gold Box Companion --
#: Donald, 2026-09-04: *"Assume all character records in
#: /home/donald/dos_por_play/SAVE/ were edited."*  Graded, not excluded: an
#: edited record still shows what a container will hold.
EDITED_DIRS = ("/dos_por_play/",)

#: A specimen whose provenance says one of these made it holds an inventory
#: **this project** chose, so it can never say what a player carries.  Matched
#: against the specimen's name and its `made_by` line together.
OURS_MARKS = ("converted", "our own writer", "this project's own writer",
              "goldbox.dos.new_dos_save", "goldbox.dos.write", "splicechar")


def _specimen_grades() -> dict[str, str]:
    """Every specimen file's path, mapped to `engine`, `edited` or `ours`.

    `.claude/rules/testing.md`: a specimen made by driving the game and never
    opened afterwards is the only kind that is evidence about the game, so the
    three are never pooled.  `edited_afterwards` is the specimen tree's own
    field; `OURS_MARKS` is read off `made_by` and the name.
    """
    out: dict[str, str] = {}
    try:
        from tools import specimens
    except Exception:                                    # pragma: no cover
        return out
    try:
        entries = specimens.list_specimens()
    except Exception:                                    # pragma: no cover
        return out
    for entry in entries:
        text = f"{entry.get('name', '')} {entry.get('made_by', '')}".lower()
        if any(mark in text for mark in OURS_MARKS):
            grade = "ours"
        elif entry.get("edited_afterwards"):
            grade = "edited"
        else:
            grade = "engine"
        for path in entry.get("_files", ()):
            out[pathlib.Path(path).as_posix()] = grade
    return out


def _grade(path, specimen_grades: dict[str, str]) -> str:
    """How much a record found at `path` is allowed to prove."""
    text = pathlib.Path(path).as_posix()
    known = specimen_grades.get(text)
    if known:
        return known
    if any(mark in text for mark in EDITED_DIRS):
        return "edited"
    if "/wish-specimens/" in text:
        return "engine"          # a specimen with no provenance row read
    if "/work/" in text or text.startswith("work/"):
        return "ours"
    return "found"


def _grade_over(paths, specimen_grades: dict[str, str]) -> str:
    """The grade for one record that turned up at several paths.

    `tools/dostailcensus.py` deduplicates on the record's bytes, so the same
    record is routinely a copy in `work/` **and** the specimen it was copied
    into.  Grading the first path found would call an engine-written specimen
    `ours`, purely because a run directory sorted first -- which is how
    THRENDER GRONE, the one record on this machine wanting five trait slots,
    was mis-graded on the first sweep.  A path with provenance in the specimen
    tree decides; only when no path has any does the directory decide.
    """
    texts = [pathlib.Path(p).as_posix() for p in paths]
    for text in texts:
        known = specimen_grades.get(text)
        if known:
            return known
    for text in texts:
        if any(mark in text for mark in EDITED_DIRS):
            return "edited"
    return min((_grade(t, specimen_grades) for t in texts),
               key=lambda g: ("engine", "edited", "found", "ours").index(g))


# --- the C64 -----------------------------------------------------------------

def c64_disks(extra_disks=()) -> list[pathlib.Path]:
    """Every C64 disk image to look in, deduplicated on its resolved path.

    The registry's three title directories, **and their parents** -- Champions
    of Krynn, Death Knights of Krynn and Gateway to the Savage Frontier are
    three of Wish's six C64 titles and none of them has a `gamedisks.toml`
    entry, so a sweep of the registry alone silently covers half the titles.
    The parent of `/.../c64/Pool of Radiance Disks` is where the other three
    sit on this machine, and an image with no saved game costs one read and is
    skipped.
    """
    paths: list[pathlib.Path] = []
    for _game, key in C64_TITLES:
        where = gamedisks.find(key)
        if where:
            where = pathlib.Path(where)
            paths += sorted(where.glob("*.[dD]64"))
            paths += sorted(where.parent.rglob("*.[dD]64"))
    root = _specimen_root()
    if root is not None:
        paths += sorted(root.glob("*/WISH-SPEC-*.[dD]64"))
    paths += sorted((ROOT / "work").rglob("*.[dD]64"))
    paths += [pathlib.Path(p) for p in extra_disks]
    out: dict[str, pathlib.Path] = {}
    for path in paths:
        out.setdefault(str(path.resolve()), path)
    return list(out.values())


def c64_rows(specimen_grades: dict[str, str], problems: list[str],
             extra_disks=()):
    """Every C64 character on every save disk and specimen this machine has.

    The C64 is the *destination*, so neither count here can exceed its
    ceiling: sixteen items and ten trait slots is all the record has room
    for.  What it says is whether the game itself fills them.
    """
    from goldbox import c64_save, savegame, traits
    seen: set[tuple[str, bytes]] = set()
    for path in c64_disks(extra_disks):
        try:
            disk = D64.open(str(path))
            game, sg0, _sg1 = savegame.load_save(disk)
        except Exception as exc:
            if path.name.upper().startswith(("PORSAVE", "NEWSAVE", "CURSE_SAVE",
                                             "WISH-SPEC")):
                problems.append(f"{path.name}: {type(exc).__name__}: {exc}")
            continue                     # not every image carries a save
        try:
            container = c64_save.container_for(game)
        except KeyError:
            # Champions of Krynn, Death Knights of Krynn and Gateway to the
            # Savage Frontier are three of Wish's six C64 titles and no save
            # of any of them has been decoded, so this project does not know
            # where their item pages are.  Counted and named rather than
            # dropped: an uncovered title is the answer to a different
            # question, and a census that hides it looks complete.
            problems.append(
                f"{path.name}: {len(sg0.characters)} {game.title} "
                f"character(s) not counted -- goldbox/c64_save.py has no "
                f"container for that title, so nothing says where its item "
                f"pages or its trait block are")
            continue
        payload = sg0.to_bytes()
        for slot in sg0.characters:
            record = slot.record
            if record is None:           # pragma: no cover
                continue
            window = bytes(slot.window)
            base = container.items(slot.index)
            page = payload[base:base + c64items.ITEMS_PER_CHARACTER
                           * c64items.ITEM_SIZE]
            carried = sum(
                1 for n in range(c64items.ITEMS_PER_CHARACTER)
                if any(page[n * c64items.ITEM_SIZE:
                            (n + 1) * c64items.ITEM_SIZE]))
            key = (game.key, window + page)
            if key in seen:
                continue
            seen.add(key)
            yield Carried(
                port="c64", title=game.key,
                grade=_grade(path, specimen_grades),
                where=f"{path.name}:{slot.index}",
                who=record.name or "(unnamed)",
                items=carried,
                traits=len(traits.traits(window[traits.FIRST:
                                                traits.FIRST + traits.SLOTS])),
                sources=(str(path),))


def _specimen_root():
    try:
        from tools import specimens
    except Exception:                                    # pragma: no cover
        return None
    root = specimens.tree_root()
    return pathlib.Path(root) if root and pathlib.Path(root).is_dir() else None


# --- DOS ---------------------------------------------------------------------

def _dos_roots() -> list[pathlib.Path]:
    from tools import dostailcensus
    out = []
    archives = dostailcensus.archives()
    if archives is not None:
        out.append(archives)
    for name in DOS_EXTRA:
        p = pathlib.Path(name).expanduser()
        out.append(p if p.is_absolute() else ROOT / name)
    return out


def dos_rows(specimen_grades: dict[str, str], problems: list[str]):
    """Every distinct DOS record, with its sibling effect file counted.

    `tools/dostailcensus.py` finds and deduplicates them, and its exclusions
    come with it: an emulator instance's staged tree, records whose names say
    this project built them, and the three titles whose record is the same
    size as one we have a layout for.
    """
    from tools import dostailcensus
    specs, skipped = dostailcensus.collect(_dos_roots(), want_built=True)
    for other, n in sorted(skipped.items()):
        problems.append(f"{n} DOS record(s) skipped under {other}: the same "
                        f"record size as a title read here, and not the same "
                        f"id space (#400)")
    for spec in specs:
        innate_ids = dos_codec._innate_effects(spec.shape.key)
        count = spec.data[dos_port.FIELDS_BY_NAME_FOR[
            spec.shape.key]["item_count"].offset]
        # The same record's copies can differ in what sits *beside* them: a
        # `.SAV` copied into a report directory without its `.SPC` reads as a
        # character with no effects at all.  The widest sibling any copy has
        # is the one that describes the character.
        splits = []
        for path in spec.paths:
            try:
                char = dos_codec.read_character(path)
            except Exception as exc:
                problems.append(f"{path.name}: {type(exc).__name__}: {exc}")
                continue
            splits.append(_split_effects([bytes(e) for e in char.effects],
                                         innate_ids))
        innate, granted, running = max(splits, key=sum) if splits else (0, 0, 0)
        grade = ("ours" if spec.built
                 else _grade_over(spec.paths, specimen_grades))
        yield Carried(port="dos", title=spec.shape.key, grade=grade,
                      where=spec.paths[0].name, who=spec.name, items=count,
                      innate=innate, granted=granted, running=running,
                      sources=tuple(str(p) for p in spec.paths))


# --- the Amiga ---------------------------------------------------------------

def amiga_rows(specimen_grades: dict[str, str], problems: list[str]):
    """Pool of Radiance's 288-byte records, then Curse's and Silver Blades'.

    The later titles keep their items and effects **inside** the record's own
    block -- `record, then item_count item nodes, then the effect chain` --
    so an Amiga Curse character's inventory is counted from the block rather
    than from a sibling file.
    """
    from goldbox import amiga_por
    from tools import amigarecords, amigasaves
    seen: set[bytes] = set()
    for label, volume, name, files in amigasaves.specimens():
        record = files.get("") or next(iter(files.values()))
        if record in seen:
            continue
        seen.add(record)
        try:
            char = amiga_por.por_character(record, files.get(".itm", b""),
                                       files.get(".spc", b""), source=label)
        except Exception as exc:
            problems.append(f"{volume}:{name}: {type(exc).__name__}: {exc}")
            continue
        innate, granted, running = _split_effects(
            [bytes(node) for node in char.effects],
            dos_codec.INNATE_EFFECTS, pad=1)
        yield Carried(port="amiga", title="pool-of-radiance", grade="found",
                      where=f"{volume}:{name}", who=char.name,
                      items=char.get("item_count"), innate=innate,
                      granted=granted, running=running,
                      sources=(f"{label}!{volume}:{name}",))
    for label, volume, name, data, what in amigarecords.specimens():
        for char in _amiga_later_characters(data, what, label, problems):
            key = _amiga_key(char.deltas)
            innate, granted, running = _split_effects(
                [bytes(node) for node in char.effects],
                dos_codec._innate_effects(key), pad=1)
            yield Carried(port="amiga", title=key, grade="found",
                          where=f"{volume}:{name}", who=char.name,
                          items=len(char.items), innate=innate,
                          granted=granted, running=running,
                          sources=(f"{label}!{volume}:{name}",))
    root = _specimen_root()
    if root is not None:
        for path in sorted(root.glob("*-amiga/*/*")):
            if path.suffix.lower() not in (".sav", ".dat", ".pc", ".cha",
                                           ".guy"):
                continue
            yield from _amiga_specimen(path, specimen_grades, problems)


def _amiga_specimen(path, specimen_grades, problems):
    """One Amiga file out of the specimen tree, whatever shape it is."""
    from goldbox import amiga_later, amiga_por
    from tools import amigasavegame
    data = path.read_bytes()
    grade = _grade(path, specimen_grades)
    if len(data) == amiga_por.AMIGA_POR_RECORD_SIZE:
        char = amiga_por.por_character(
            data, _sibling(path, ".itm"), _sibling(path, ".spc"),
            source=str(path))
        innate, granted, running = _split_effects(
            [bytes(n) for n in char.effects], dos_codec.INNATE_EFFECTS, pad=1)
        yield Carried(port="amiga", title="pool-of-radiance", grade=grade,
                      where=path.name, who=char.name,
                      items=char.get("item_count"), innate=innate,
                      granted=granted, running=running, sources=(str(path),))
        return
    try:
        shape = amigasavegame.detect(data)
    except Exception:
        return                            # not a saved game: nothing to read
    if shape.record_shape is None:
        return                            # Pool of Radiance: party is filenames
    try:
        party = amiga_later.party_in_savegame(data, shape.record_shape)
    except Exception as exc:
        problems.append(f"{path.name}: {type(exc).__name__}: {exc}")
        return
    key = _amiga_key(shape.record_shape)
    for char in party:
        innate, granted, running = _split_effects(
            [bytes(n) for n in char.effects], dos_codec._innate_effects(key), pad=1)
        yield Carried(port="amiga", title=key, grade=grade, where=path.name,
                      who=char.name, items=len(char.items), innate=innate,
                      granted=granted, running=running, sources=(str(path),))


def _sibling(path, suffix: str) -> bytes:
    for candidate in (path.with_suffix(suffix), path.with_suffix(suffix.upper())):
        if candidate.exists() and candidate != path:
            return candidate.read_bytes()
    return b""


def _split_effects(nodes, innate_ids, pad: int = 0):
    """`(innate, granted, running)` over a list of effect nodes.

    The Amiga node is DOS's nine bytes with one pad inserted at offset 1
    (`goldbox/amiga.py`'s `effect_size`), so the duration word that decides
    "granted or counting down" sits at `1 + pad`.
    """
    innate = granted = running = 0
    for node in nodes:
        if node[0] in innate_ids:
            innate += 1
        elif int.from_bytes(node[1 + pad:3 + pad], "big" if pad else "little"):
            running += 1
        else:
            granted += 1
    return innate, granted, running


def _amiga_key(shape) -> str:
    return getattr(shape, "key", getattr(shape, "title", "?"))


def _amiga_later_characters(data: bytes, what: str, label: str, problems):
    """The characters in a `.guy` file or a saved game, through its own shape.

    **A saved game's title comes from `tools/amigasavegame.py`'s `detect`,
    never from trying each shape until one parses.**  `party_in_savegame`
    trusts whatever shape it is handed, and Curse's 428-byte record signature
    matches inside a Silver Blades saved game -- which read Silver Blades'
    savgamA.sav as two Curse characters, with an `item_count` taken from the
    wrong offset, on the first run of this sweep.  `detect` tells them apart by
    where the header ends: 12825 bytes for Curse, 5143 for Silver Blades.
    """
    from goldbox import amiga_later, amiga_port
    from tools import amigasavegame
    if what != "record":
        try:
            shape = amigasavegame.detect(data).record_shape
        except Exception as exc:
            problems.append(f"{label}: {type(exc).__name__}: {exc}")
            return
        if shape is None:                # Pool of Radiance: party is filenames
            return
        try:
            yield from amiga_later.party_in_savegame(data, shape)
        except Exception as exc:                         # pragma: no cover
            problems.append(f"{label}: {type(exc).__name__}: {exc}")
        return
    for shape in amiga_port.AMIGA_DELTAS:
        if len(data) < shape.record_size:
            continue
        if not amiga_later.looks_like_amiga_record(data, 0, shape):
            continue
        try:
            char, end = amiga_later._amiga_block(data, 0, shape, label)
        except Exception:
            continue                     # the tail does not fit this shape
        if end == len(data):             # only this shape accounts for it all
            yield char
            return
    problems.append(f"{label}: {len(data)} bytes match no Amiga record shape "
                    f"with a tail that accounts for the whole file")


# --- reporting ---------------------------------------------------------------

#: The two ceilings, and where each is written down.
CEILINGS = (
    ("items", c64items.ITEMS_PER_CHARACTER,
     "goldbox/items.py ITEM_BLOCK_STRIDE // ITEM_SIZE -- one $100 item page "
     "per character at sixteen bytes an item"),
    ("trait slots", 10,
     "goldbox/traits.py SLOTS, record 0x0AD-0x0B6 -- three overlays loop "
     "LDX #$09 (docs/171-c64-trait-slots.md)"),
)


def report(rows: list[Carried], problems: list[str]) -> None:
    from goldbox import traits as c64traits
    item_ceiling = c64items.ITEMS_PER_CHARACTER
    trait_ceiling = c64traits.SLOTS
    print(f"{len(rows)} distinct characters over three ports\n")
    print("The ceilings, both in the C64 character record:")
    for name, value, why in CEILINGS:
        print(f"  {value:2d} {name:12s} {why}")
    print()
    header = (f"{'port':6s} {'title':28s} {'grade':7s} {'chars':>5s} "
              f"{'max items':>9s} {'max traits':>10s} {'to 16':>6s} "
              f"{'to 10':>6s}")
    print(header)
    print("-" * len(header))
    by = collections.defaultdict(list)
    for row in rows:
        by[(row.port, row.title, row.grade)].append(row)
    for (port, title, grade), group in sorted(by.items()):
        most = max(r.items for r in group)
        wide = max(r.trait_demand for r in group)
        print(f"{port:6s} {title:28s} {grade:7s} {len(group):5d} "
              f"{most:9d} {wide:10d} {item_ceiling - most:6d} "
              f"{trait_ceiling - wide:6d}")
    print()
    for label, key, ceiling in (("items", lambda r: r.items, item_ceiling),
                                ("trait slots",
                                 lambda r: r.trait_demand, trait_ceiling)):
        hist = collections.Counter(key(r) for r in rows)
        print(f"{label}: " + "  ".join(
            f"{n}x{hist[n]}" for n in sorted(hist)))
        at = [r for r in rows if key(r) >= ceiling]
        print(f"  {len(at)} of {len(rows)} at or over the ceiling of {ceiling}")
        for row in sorted(at, key=lambda r: -key(r))[:20]:
            print(f"    {row.grade:7s} {row.port:6s} {row.title:28s} "
                  f"{row.who:16s} {key(row):3d}  {row.where}")
        print()
    grades = collections.Counter(r.grade for r in rows)
    print("provenance:", dict(sorted(grades.items())))
    print("  engine  a specimen made by driving the game, never edited after")
    print("  edited  a specimen or a play directory an editor has been in")
    print("  ours    a record one of this project's own writers produced")
    print("  found   a disk or an archive nobody watched being written")
    if problems:
        print(f"\n{len(problems)} thing(s) this sweep could not read:")
        for line in problems:
            print(f"  {line}")


def census(problems: list[str], extra_disks=()) -> list[Carried]:
    """Every character this machine can reach, on all three ports."""
    grades = _specimen_grades()
    rows: list[Carried] = []
    rows += list(c64_rows(grades, problems, extra_disks))
    rows += list(dos_rows(grades, problems))
    rows += list(amiga_rows(grades, problems))
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--items", action="store_true",
                    help="the DOS item_count histogram only")
    ap.add_argument("--grants", action="store_true",
                    help="the effect-granting item templates only")
    ap.add_argument("--census", action="store_true",
                    help="the per-port carried census only")
    ap.add_argument("--json", metavar="FILE",
                    help="write one JSON row per character found")
    ap.add_argument("--disk", action="append", default=[], metavar="D64",
                    help="another C64 disk image to read; repeatable")
    args = ap.parse_args(argv)
    both = not (args.items or args.grants or args.census)

    if both or args.grants:
        print("Effect-granting item templates: byte +15 bit 7, which is the "
              "only gate READY dispatches through")
        for game, key in C64_TITLES:
            disks = gamedisks.find(key)
            if disks is None:
                print(f"  {game.title}: no disks")
                continue
            grants = grant_templates(pathlib.Path(disks), game)
            total = all_templates(pathlib.Path(disks), game)
            ids = sorted(set(grants.values()))
            print(f"  {game.title}: {len(grants)} of {total} distinct "
                  f"templates grant, effect ids {ids}")
        print("  The C64 record has 10 trait slots and a racial seed of 0 to "
              "4 ids, so overflowing one needs 6 or more granted ids at once "
              "on a human and 7 or more on a dwarf or a gnome")
        print()

    if both or args.census or args.items or args.json:
        problems: list[str] = []
        rows = census(problems, args.disk)
        if both or args.census:
            report(rows, problems)
        if args.items:
            hist = collections.Counter(
                r.items for r in rows if r.port == "dos")
            print(f"DOS item_count, over every readable DOS record "
                  f"(the C64 record holds {c64items.ITEMS_PER_CHARACTER})")
            for n in sorted(hist):
                print(f"  {n:3d} items  {hist[n]:5d} records")
        if args.json:
            pathlib.Path(args.json).write_text(json.dumps(
                [dataclasses.asdict(r) | {"trait_demand": r.trait_demand}
                 for r in rows], indent=1))
            print(f"\n{len(rows)} rows written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
