"""The character sheet's portrait, and the enumeration three ports share.

A Pool of Radiance character is drawn on the sheet as a **head over a body**,
chosen at creation from a menu of fourteen heads and twelve bodies.  All
three ports store that choice in the character record, and they store it
differently:

* the **C64** keeps the art's own id -- `portrait_head` at `0x0FE` is the two
  hex digits of a filename, so `$2D` is the file `HEAD2D` (`docs/140-loaded-
  files-cache.md`, loader slots 13 and 14);
* **DOS** keeps the **menu position**, one-based -- `portrait_head` at `0x0BB`
  is 1 to 14 and `portrait_body` at `0x0BC` is 1 to 12;
* the **Amiga** keeps the menu position too: its record is the DOS one with
  three insertions (`goldbox.amiga_por.AMIGA_POR_SHIFTS`), so the same pair is at
  `0x0BD` and `0x0BE`, and the six records in `save/` on the Amiga's own disk
  1 hold 1-14 and 1-12 there.

The art itself is the same art with the same numbering.  DOS packs it into one
`.DAX` container per disk instead of one file per portrait, and the block ids
inside `HEAD<n>.DAX` are exactly the ids of the `HEAD*` files on the C64's
`POOL<n>.D64` -- 41 head ids and 21 body ids, equal as sets and equal disk by
disk, all sixteen containers (`docs/117-save-conversion.md`, "The portrait").
The Amiga packs the same art into one `/head.dax` and one `/body.dax` on its
data disk, 39 head ids and 21 body ids, and the twenty-six the menu names are
all among them.

So the ports are joined by the menu: **DOS position n is C64 art id
`heads[n - 1]`**, and the table of ids is in the player's own files on every
side.  This module can read it off any of them -- `tables_from_dos`,
`tables_from_c64`, `tables_from_disks`, `tables_from_amiga` and
`tables_from_amiga_disks` -- and **also carries the twenty-six numbers
themselves**, `POOL_OF_RADIANCE_MENU` and `AMIGA_POOL_OF_RADIANCE_MENU`, read
off each port once and typed out, so a conversion needs no disk in reach to
give a character his own face.  `stored_tables` is the fallback; the block
above it says why a handful of integers with their provenance is a
measurement and not a copy of a game file.

**Every port offers the same twelve bodies, in the same order, and stores its
own numbering of them.**  The C64's and DOS's tables are the same table byte
for byte; the Amiga's differs at one entry -- position 8 is art `0x05` there
and `0x18` on the other two, because two art teams numbered their own files
differently and drew that figure differently (#194, #480).  `differences`
names that row and `agrees_with` answers False for the pair.

**Neither of those is a question a conversion has to answer.**  The menu
position is the player's choice and the character's identity; the stored byte
is only an index into one port's art.  So a conversion maps **position to
position** and drops nothing, and
:func:`neutral_menu` is the single table it resolves against, whatever the
ports on either end -- the neutral record spells a menu position as the C64's
art id for that position, so the C64's and DOS's shared table is what turns
one into the other.  `AMIGA_POOL_OF_RADIANCE_MENU` names the Amiga's own
**art**, for drawing the Amiga's own pictures, and is not a conversion table.
`docs/188-the-sheet-portrait-per-title.md` opens with the whole of it and with
the published seven-port picture behind it; it is settled and is not to be
raised again.
"""

from __future__ import annotations

import dataclasses
import pathlib

from .dos_savegame import DaxError, dax_index

#: The menu is fourteen heads and twelve bodies in both ports' binaries.
HEAD_COUNT = 14
BODY_COUNT = 12

#: Where each table is, in the file that carries it.  Both are a run of
#: **strictly increasing** art ids, and the two tables are adjacent -- DOS
#: writes the heads first, the C64's `GEN` the bodies first.  Nothing here
#: depends on a file offset: the run is found by its shape and every value in
#: it is checked against the art that exists beside it, so a table found is a
#: table that names real portraits.
_DOS_EXECUTABLE = "START.EXE"
_C64_OVERLAY = b"GEN"


class PortraitError(ValueError):
    """The portrait tables could not be read out of the files given."""


@dataclasses.dataclass(frozen=True)
class PortraitTables:
    """The fourteen heads and twelve bodies the creation menu offers.

    `heads` and `bodies` are art ids in menu order, so the index into either
    is the DOS record's value less one, and the value at that index is the
    C64 record's byte.
    """

    heads: tuple[int, ...]
    bodies: tuple[int, ...]
    source: str

    # -- C64 art id -> the DOS record's one-based menu position --------------
    def head_position(self, art_id: int) -> int | None:
        """Where a C64 `portrait_head` sits in the menu, or `None`."""
        return self._position(self.heads, art_id)

    def body_position(self, art_id: int) -> int | None:
        """Where a C64 `portrait_body` sits in the menu, or `None`."""
        return self._position(self.bodies, art_id)

    # -- the DOS record's position -> the C64 art id -------------------------
    def head_art(self, position: int) -> int | None:
        """The C64 `HEAD<xx>` id a DOS `portrait_head` names, or `None`."""
        return self._art(self.heads, position)

    def body_art(self, position: int) -> int | None:
        """The C64 `BODY<xx>` id a DOS `portrait_body` names, or `None`."""
        return self._art(self.bodies, position)

    @staticmethod
    def _position(table: tuple[int, ...], art_id: int) -> int | None:
        try:
            return table.index(int(art_id)) + 1
        except ValueError:
            return None

    @staticmethod
    def _art(table: tuple[int, ...], position: int) -> int | None:
        n = int(position)
        return table[n - 1] if 1 <= n <= len(table) else None

    def agrees_with(self, other: "PortraitTables") -> bool:
        """Whether another port's tables are the same menu in the same order."""
        return self.heads == other.heads and self.bodies == other.bodies

    def differences(self, other: "PortraitTables"
                    ) -> tuple[tuple[str, int, int, int], ...]:
        """Every menu position where two ports offer different art.

        `(what, position, mine, theirs)` per row, `what` being `"head"` or
        `"body"` and `position` one-based, so a caller can say *which* row of
        the menu two ports number differently rather than only that they do.
        The Amiga's Pool of Radiance menu differs from the C64's and DOS's in
        exactly one row -- `("body", 8, 0x05, 0x18)` read from the Amiga's
        side (#194).

        **A row here is not a loss a converted character suffers**, and an
        earlier version of this docstring said it was.  Both ports offer that
        eighth choice; they draw it differently and number it differently.  A
        conversion converts position 8 to position 8 and this method is for
        naming the art, not for gating the crossing (#480).

        A table of a different **length** is reported position by position
        for as far as the two overlap, and each position past the shorter
        one's end as art `0` on that side, since no menu can offer it.
        """
        out: list[tuple[str, int, int, int]] = []
        for what, mine, theirs in (("head", self.heads, other.heads),
                                   ("body", self.bodies, other.bodies)):
            for i in range(max(len(mine), len(theirs))):
                a = mine[i] if i < len(mine) else 0
                b = theirs[i] if i < len(theirs) else 0
                if a != b:
                    out.append((what, i + 1, a, b))
        return tuple(out)


# ---------------------------------------------------------------------------
# Finding the tables
# ---------------------------------------------------------------------------
def _runs(data: bytes, first: int, first_ok: set[int],
          second: int, second_ok: set[int],
          second_increasing: bool = True) -> list[int]:
    """Offsets where `first` then `second` ids sit, both naming real art.

    The first run must be strictly increasing and every byte of both must
    name art that exists, which is what makes the search a *reading* rather
    than a guess -- and what makes it single-valued in every file we have.

    `second_increasing` is the Amiga's exception and the reason this
    argument exists.  The C64's and DOS's twelve bodies climb; the Amiga's
    run `01 02 03 04 07 08 12 05 1A 21 23 25`, because its menu offers art
    `0x05` at position 8 where the other two offer `0x18` and the entry was
    swapped in place rather than re-sorted (#194).  With the run required
    only to be twelve **distinct** ids naming art the disk carries, the
    search is still single-valued: one hit in the Amiga's 459,028-byte
    `/program`, at `0x6D68F`.
    """
    out = []
    span = first + second
    # `- span + 1`: the last position a run of `span` bytes still fits at
    # is `len(data) - span`, and `range` excludes its stop. A buffer that
    # *is* the run returned nothing before this.
    for i in range(max(0, len(data) - span + 1)):
        a, b = data[i:i + first], data[i + first:i + first + second]
        if not (set(a) <= first_ok and set(b) <= second_ok):
            continue
        if not all(x < y for x, y in zip(a, a[1:])):
            continue
        if all(x < y for x, y in zip(b, b[1:])) if second_increasing \
           else len(set(b)) == second:
            out.append(i)
    return out


def _only(hits: list[int], where: str) -> int:
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise PortraitError(
            f"{where}: no run of {HEAD_COUNT} head ids and {BODY_COUNT} body "
            f"ids in it -- this is not a title whose creation menu the "
            f"portraits beside it belong to")
    raise PortraitError(
        f"{where}: {len(hits)} runs of {HEAD_COUNT} head ids and "
        f"{BODY_COUNT} body ids, at {hits}; the table cannot be told from "
        f"the others by shape alone")


def dos_art_ids(game: str | pathlib.Path) -> tuple[set[int], set[int]]:
    """Every head and body id the DOS game directory's containers hold."""
    game = pathlib.Path(game)
    found: list[set[int]] = []
    for stem in ("HEAD", "BODY"):
        ids: set[int] = set()
        for path in sorted(game.glob(f"{stem}[0-9].DAX")):
            try:
                ids |= {block for block, *_ in dax_index(path.read_bytes(),
                                                         path.name)}
            except DaxError as e:
                raise PortraitError(f"{path.name}: {e}") from e
        if not ids:
            raise PortraitError(
                f"{game}: no {stem}<n>.DAX in it, so the portrait art is not "
                f"here to check a table against")
        found.append(ids)
    return found[0], found[1]


def tables_from_dos(game: str | pathlib.Path) -> PortraitTables:
    """The menu tables out of the DOS game directory's own executable.

    `game` is the directory holding `START.EXE` and the `HEAD<n>.DAX` files
    -- the one `goldbox.dos_codec.write_dos_save` already takes so the party's own
    area script can be staged.
    """
    game = pathlib.Path(game)
    heads_ok, bodies_ok = dos_art_ids(game)
    exe = game / _DOS_EXECUTABLE
    try:
        data = exe.read_bytes()
    except OSError as e:
        raise PortraitError(f"{exe}: {e}") from e
    at = _only(_runs(data, HEAD_COUNT, heads_ok, BODY_COUNT, bodies_ok),
               str(exe))
    return PortraitTables(
        heads=tuple(data[at:at + HEAD_COUNT]),
        bodies=tuple(data[at + HEAD_COUNT:at + HEAD_COUNT + BODY_COUNT]),
        source=f"{exe.name} @{at}")


def _side_art_ids(image) -> dict[str, set[int]]:
    """Every `HEAD<xx>`/`BODY<xx>` id one open `D64` image's directory names."""
    ids: dict[str, set[int]] = {"HEAD": set(), "BODY": set()}
    for entry in image.directory():
        name = entry.raw_name.rstrip(b"\xa0").decode("latin1")
        for stem in ids:
            if name.startswith(stem) and len(name) == len(stem) + 2:
                try:
                    ids[stem].add(int(name[len(stem):], 16))
                except ValueError:
                    pass
    return ids


def _all_art_ids(sides: list[pathlib.Path]) -> dict[str, set[int]]:
    """The union of `_side_art_ids` over every side given.

    A title's `GEN` does not have to share a disk with its `HEAD*`/`BODY*`
    files -- Curse keeps `GEN` on its first side and the art on the rest --
    so a table found on one side is checked against every side of the same
    title, not only the one it came from.
    """
    from .d64 import D64

    out: dict[str, set[int]] = {"HEAD": set(), "BODY": set()}
    for side in sides:
        try:
            image = D64(side.read_bytes())
        except OSError:
            continue
        found = _side_art_ids(image)
        out["HEAD"] |= found["HEAD"]
        out["BODY"] |= found["BODY"]
    return out


def _table_from_gen(data: bytes, ids: dict[str, set[int]],
                     source: str) -> PortraitTables:
    """The heads-then-bodies-swapped `GEN` layout, checked against `ids`."""
    at = _only(_runs(data, BODY_COUNT, ids["BODY"], HEAD_COUNT, ids["HEAD"]),
               source)
    return PortraitTables(
        heads=tuple(data[at + BODY_COUNT:at + BODY_COUNT + HEAD_COUNT]),
        bodies=tuple(data[at:at + BODY_COUNT]),
        source=f"{source} @{at}")


def tables_from_c64(disk: str | pathlib.Path) -> PortraitTables:
    """The same tables out of the C64 `GEN` overlay, for a cross-check.

    `GEN` is on `POOL3`, the character-creation side, beside the `HEAD*` and
    `BODY*` files its two tables name.  The order is the other way round
    there -- bodies first -- which is the only difference between the ports.

    This checks a found table against the **one** disk given, which is right
    for `POOL3` -- `GEN` and the art it names are both there.  A title that
    keeps them on different sides needs `tables_from_disks`, which checks
    against every side of the title instead of just this one.
    """
    from .d64 import D64, D64Error

    disk = pathlib.Path(disk)
    image = D64(disk.read_bytes())
    ids = _side_art_ids(image)
    if not ids["HEAD"] or not ids["BODY"]:
        raise PortraitError(
            f"{disk.name}: no HEAD<xx>/BODY<xx> files on it, so this is not "
            f"the side that carries the creation menu")
    try:
        data = image.read_file(_C64_OVERLAY)
    except D64Error as e:
        # `D64Error`, not `Exception`: every way `read_file` can fail on a
        # real image derives from it, and the broader catch turned an
        # unrelated bug into "no GEN on it" -- a wrong answer that reads
        # like a measurement.
        raise PortraitError(f"{disk.name}: no GEN on it ({e})") from e
    return _table_from_gen(data, ids, f"{disk.name}:GEN")


def tables_from_disks(disks: str | pathlib.Path) -> PortraitTables:
    """The menu tables off the player's C64 game sides, whichever holds `GEN`.

    The **import** direction -- a DOS save becoming a `.d64` -- needs the
    tables to turn the DOS record's menu position into the art id the C64
    record stores, and the thing it has in its hand is the directory this
    title's sides live in -- the one `goldbox.dos_codec.write_dos_save` already
    reads the combat icon and `ANIMATE00` out of.  `tables_from_c64` wants
    the one side that carries `GEN`; this finds it, for whichever of the
    three importable titles the directory turns out to hold (#300).

    Every side of the matching title is tried and the first that answers
    wins, rather than hardcoding `POOL3` or a `POOL<n>.D64` name: which side
    carries `GEN` is the game's business, and Curse keeps `GEN` on one side
    and its `HEAD*`/`BODY*` art on the others.  So the ids a found table is
    checked against are pooled from **every side of the title**, not only
    the one `GEN` happened to be on -- a table found is still a table naming
    portraits that exist somewhere on the player's own disks.
    """
    from .c64_port import GAMES
    from .d64 import D64, D64Error

    disks = pathlib.Path(disks)
    # `dict.fromkeys` rather than a set: several titles could share one glob
    # and the order patterns are tried in should not depend on a set's
    # unordered hashing.
    patterns = tuple(dict.fromkeys(g.disk_glob for g in GAMES))
    any_sides = False
    why: list[str] = []
    for pattern in patterns:
        sides = sorted(disks.glob(pattern))
        if not sides:
            continue
        any_sides = True
        ids = _all_art_ids(sides)
        if not ids["HEAD"] or not ids["BODY"]:
            why.append(
                f"{len(sides)} side(s) matching {pattern!r} carry no "
                f"HEAD<xx>/BODY<xx> file between them, so this title's "
                f"sheet-portrait art is not on any of the player's disks")
            continue
        for side in sides:
            try:
                image = D64(side.read_bytes())
                data = image.read_file(_C64_OVERLAY)
            except (D64Error, OSError) as e:
                why.append(f"{side.name}: no GEN on it ({e})")
                continue
            try:
                return _table_from_gen(data, ids, f"{side.name}:GEN")
            except PortraitError as e:
                why.append(str(e))
        why.append(f"none of the {len(sides)} sides matching {pattern!r} "
                   f"carries the creation menu")
    if not any_sides:
        raise PortraitError(
            f"{disks}: no {' or '.join(patterns)} in it, so the creation "
            f"menu's tables are not here to read")
    raise PortraitError(
        f"{disks}: none of the sides here carries the creation menu "
        f"({'; '.join(why)})")


# ---------------------------------------------------------------------------
# The Amiga
# ---------------------------------------------------------------------------
#: The Amiga Pool of Radiance files the menu is read out of: the executable
#: on the game disk and the two art containers on the data disk.  Named
#: rather than searched for, because both disks are the player's own and a
#: name is what a failure can then be reported against.
AMIGA_PROGRAM = "program"
AMIGA_HEAD_DAX = "head.dax"
AMIGA_BODY_DAX = "body.dax"


def amiga_art_ids(head: bytes, body: bytes) -> tuple[set[int], set[int]]:
    """The block ids the Amiga's own `head.dax` and `body.dax` hold."""
    from . import amiga_dax

    found = []
    for data, name in ((head, AMIGA_HEAD_DAX), (body, AMIGA_BODY_DAX)):
        try:
            ids = set(amiga_dax.block_ids(data, name))
        except amiga_dax.AmigaDaxError as e:
            raise PortraitError(f"{name}: {e}") from e
        if not ids:
            raise PortraitError(
                f"{name}: no blocks in it, so the portrait art is not here "
                f"to check a table against")
        found.append(ids)
    return found[0], found[1]


def tables_from_amiga(program: bytes, head: bytes, body: bytes,
                      source: str = AMIGA_PROGRAM) -> PortraitTables:
    """The menu tables out of the Amiga's own executable.

    `program` is the game disk's `/program`, `head` and `body` the data
    disk's `/head.dax` and `/body.dax`.  Bytes rather than paths because the
    Amiga keeps them on two different disks and a caller may have them from
    an `.adf`, from a zip, or from a directory somebody copied them into --
    :func:`tables_from_amiga_disks` is the convenience over a folder of
    `.adf` files.

    The table is at file offset `0x6D68F` on the release read for #194, in
    data hunk 31, heads first as DOS has them.  Nothing here depends on that
    offset: the run is found by its shape and every id in it is checked
    against the art on the disk beside it, exactly as the other two ports'
    readers do.
    """
    heads_ok, bodies_ok = amiga_art_ids(head, body)
    at = _only(_runs(program, HEAD_COUNT, heads_ok, BODY_COUNT, bodies_ok,
                     second_increasing=False), source)
    return PortraitTables(
        heads=tuple(program[at:at + HEAD_COUNT]),
        bodies=tuple(program[at + HEAD_COUNT:at + HEAD_COUNT + BODY_COUNT]),
        source=f"{source} @{at}")


def _amiga_files(disks: str | pathlib.Path) -> dict[str, tuple[str, bytes]]:
    """`/program`, `/head.dax` and `/body.dax` off a folder of `.adf` files."""
    from .amiga_adf import AmigaDisk, AmigaDiskError

    wanted = {AMIGA_PROGRAM, AMIGA_HEAD_DAX, AMIGA_BODY_DAX}
    out: dict[str, tuple[str, bytes]] = {}
    for side in sorted(pathlib.Path(disks).glob("*")):
        if side.suffix.lower() != ".adf" or not side.is_file():
            continue
        try:
            image = AmigaDisk.open(side)
            paths = [path for path, _entry in image.walk()]
        except (AmigaDiskError, ValueError, OSError):
            continue
        for path in paths:
            name = path.strip("/").split("/")[-1].lower()
            if name in wanted and name not in out:
                try:
                    out[name] = (f"{side.name}:{path}", image.read_file(path))
                except (AmigaDiskError, ValueError):
                    pass
    return out


def tables_from_amiga_disks(disks: str | pathlib.Path) -> PortraitTables:
    """The menu tables off the player's own Amiga sides, whichever holds what.

    The Amiga splits what the C64 keeps on one side: `/program` is on the
    game disk (`poolgame`) and the art on the data disk (`POOLDATA`), so a
    caller hands over the folder both `.adf` files are in and this finds
    them by name.  A folder holding neither says which of the three it could
    not find, rather than "no menu here" -- the two failures a player can
    actually cause are a missing disk and the wrong game's disks, and they
    read differently.
    """
    found = _amiga_files(disks)
    missing = [n for n in (AMIGA_PROGRAM, AMIGA_HEAD_DAX, AMIGA_BODY_DAX)
               if n not in found]
    if missing:
        names = (missing[0] if len(missing) == 1 else
                 f"{', '.join(missing[:-1])} or {missing[-1]}")
        raise PortraitError(
            f"{disks}: no Amiga side here carries {names}, so the creation "
            f"menu's tables are not here to read")
    where, program = found[AMIGA_PROGRAM]
    return tables_from_amiga(program, found[AMIGA_HEAD_DAX][1],
                             found[AMIGA_BODY_DAX][1], where)


# ---------------------------------------------------------------------------
# Which titles have a sheet portrait at all
# ---------------------------------------------------------------------------
#: The game keys whose C64 character sheet draws a portrait.
#:
#: **Only Pool of Radiance's does**, and that is a fact about the engine
#: rather than about the art on a player's disks: its `LIBRARY $48A4` reads
#: `portrait_head` and `portrait_body` out of the live record, asks the
#: loader for the `HEAD<xx>` and `BODY<xx>` files they name, and draws them
#: with `ANIMATE00`'s `$8406` and `$8409` entries at screen `$CC44`.  Curse
#: of the Azure Bonds' and Secret of the Silver Blades' `LIBRARY` never call
#: the loader at all, and no file on any of their twelve sides calls either
#: of those two `ANIMATE` entries -- 558 and 571 files searched
#: (`tools/portraitdraw.py`, which prints the census).
#:
#: Watched as well as read: a Curse sheet and a Silver Blades sheet with
#: `$41` -- art that exists on `CURSE_B` -- written into both record bytes
#: draw exactly as they do with the pair at zero, and loader slots 13 and 14
#: stay `$FF`, so no art was even asked for.  The runs are in
#: `docs/188-the-sheet-portrait-per-title.md` and the screenshots on `#300`.
#:
#: Kept here rather than in the conversion so both directions read one fact:
#: `goldbox.dos_codec` decides today with `shape is POOL_OF_RADIANCE` in the
#: C64-to-DOS direction and does not decide at all in the other, which is
#: why a Curse import reports a portrait it never could have written.
#: Spelled out rather than imported from `goldbox.c64_port`: `goldbox.traits`
#: does the same and says why -- this package duck-types on `.key` to keep
#: the import graph acyclic.
POOL_OF_RADIANCE_KEY = "pool-of-radiance"

SHEET_PORTRAIT_TITLES = frozenset({POOL_OF_RADIANCE_KEY})


def draws_sheet_portrait(game=None) -> bool:
    """Whether this title's C64 character sheet draws a portrait at all.

    `game` is a `goldbox.c64_port.C64Container`, anything else carrying a `key`, or the
    key itself.  A title this answers False for has nothing to convert and
    nothing to report: a character arriving there without a face is a
    character arriving correct, because the engine draws none for any
    character, including one it made itself.

    **`None` means Pool of Radiance**, which is the answer every other
    resolver in this package gives -- `goldbox.spells.for_game`,
    `goldbox.levels.for_game`, `goldbox.traits.for_game`,
    `goldbox.c64_save.container_for` and `goldbox.c64_codec.record_shape` all
    resolve it that way, because every caller that passes no title predates
    the second game and means the first.  Answering False for `None` here
    would have been the one predicate in the family that disagreed, and it
    would disagree in the direction that silently drops a portrait Pool of
    Radiance really does draw.
    """
    key = getattr(game, "key", game)
    if key is None:
        key = POOL_OF_RADIANCE_KEY
    return str(key) in SHEET_PORTRAIT_TITLES


# ---------------------------------------------------------------------------
# The menu, stored
# ---------------------------------------------------------------------------
#: Pool of Radiance's creation menu: the fourteen head ids and the twelve
#: body ids in menu order, **read out of the game's own binaries once and
#: written down here as numbers**, so a conversion needs no disk in reach
#: to give a character his own face.  Donald, 2026-09-06: *"Can we not just
#: store all these art id tables ourselves?  ...  It's just a handful of
#: numbers, right?  Just pull them from each title so you can cross
#: reference them.  Then you don't need the disks at all."*  And, asked
#: whether that crossed `AGENTS.md`'s line: *"We don't need to refuse game
#: disks.  Just store the IDs we would otherwise be looking up.  They are
#: 40 years old and they are not going to change."*  And, the same day:
#: *"A table of 26 numbers doesn't break any rules.  It's not art, it's
#: just two dozen numbers."*  (`.claude/rules/conversions.md`, "A small
#: table of numbers read out of the game is a measurement".)
#:
#: **Why this is a measurement and not a copy of a data file.**  `AGENTS.md`
#: bans the game's *data files* -- a map, a table, a script, a record -- as
#: committed bytes, because a slice of a game file under a new name is the
#: file.  What is below is not a slice of anything: it is twenty-six
#: integers that :func:`tables_from_c64` found in `GEN` and
#: :func:`tables_from_dos` found in `START.EXE`, by the shape of the run and
#: by checking every value against the art beside it, and then *typed out*
#: -- the same class of thing as the field offsets in `goldbox/layout.py`,
#: the `$49FF` switch below, and every address cited in `docs/`.  It
#: describes where the menu's fourteenth head lives; it does not carry the
#: head.  No byte of `GEN`, of `START.EXE` or of any `HEAD<xx>` file is
#: here, and nothing here would let anybody rebuild one.
#:
#: **Where the numbers came from, so anybody can re-derive them.**
#: `tools/portraitmenu.py` reads both binaries and prints this block;
#: `tools/portraitmenu.py --check` says whether the disks on the machine
#: still agree with it.  Read 2026-09-06 off:
#:
#: * the C64's `POOL3.D64:GEN`, run at file offset 2877, bodies first --
#:   the one Pool of Radiance rip on this machine, present at two paths
#:   with the same SHA-256 (`51b6fac7...`);
#: * DOS's `START.EXE`, run at file offset 58297, heads first -- the
#:   *Forgotten Realms: The Archives* release, and the same bytes again in
#:   Donald's play directory.
#:
#: The C64 and DOS agree byte for byte
#: (`tests/test_portraits.py::test_the_menu_found_from_the_disks_is_the_one_dos_offers`),
#: and `test_the_stored_menu_is_what_the_disks_carry` pins this block to
#: what the disks say wherever the disks are present, so the two cannot
#: drift apart in silence.  **One release of each port has been read.**  A
#: release whose `GEN` orders the menu differently would make this table
#: wrong for its owner; none is known, and the check above is how one would
#: be found.
#:
#: **Only Pool of Radiance needs one.**  Curse of the Azure Bonds' and Secret
#: of the Silver Blades' C64 sheets draw no portrait for any character
#: (`SHEET_PORTRAIT_TITLES`, `#300`), neither title's `GEN` or `START.EXE`
#: carries a fourteen-and-twelve run -- `tables_from_disks` and
#: `tables_from_dos` both raise on both, measured 2026-09-06 on every copy
#: on this machine -- so there is nothing to store and nothing a stored
#: table would give a player.
POOL_OF_RADIANCE_MENU = PortraitTables(
    heads=(0x00, 0x08, 0x09, 0x0D, 0x10, 0x12, 0x16,
           0x22, 0x2D, 0x33, 0x35, 0x39, 0x43, 0x44),
    bodies=(0x01, 0x02, 0x03, 0x04, 0x07, 0x08,
            0x12, 0x18, 0x1A, 0x21, 0x23, 0x25),
    source="the stored Pool of Radiance creation menu (goldbox/portraits.py)",
)

#: **The Amiga's own numbering of the same twelve choices** (#194).  The
#: fourteen heads are the block above's byte for byte and in the same order;
#: the twelve bodies differ in one entry -- position 8 is art `0x05` here and
#: `0x18` on the C64 and in DOS.
#:
#: **This is an art table, not a conversion table.**  Use it to find the
#: Amiga's own picture for a menu position -- what `tools/bodychoices.py` and
#: `tools/amigaportraitmenu.py` draw with -- and never to move a character
#: between ports.  A conversion maps position to position and resolves both
#: ends against :func:`neutral_menu`; wiring this table into a writer is what
#: made `#480 (An Amiga character whose body is the menu's eighth arrives on
#: the C64 or DOS wearing a different body, because the Amiga reader uses the
#: C64 and DOS menu)` report a drop for a choice both ports offer.
#:
#: Read 2026-09-08 off Amiga Pool of Radiance's `/program`, at file offset
#: `0x6D68F` in data hunk 31, heads first as DOS has them.  Three `.adf`
#: images of the game are on this machine -- a 1995 rip and two 2000/2001
#: cracked releases -- and their `/program` is the same 459,028 bytes with
#: the same SHA-256 (`b1cbbecc...`) in all three, so this is one release
#: read three times rather than three readings.
#:
#: **What says it is the same table and not a coincidence.**  The sixty
#: bytes before it are byte for byte DOS's `START.EXE`, and what follows it
#: is the eight direction keys in each port's own spelling -- PC scancodes
#: there, the ASCII digits `1234 6789` here.  So the neighbourhood is a data
#: block the two ports share, with the parts that had to change changed.
#:
#: **And the difference is a different picture, not a renumbering.**  Both
#: ports ship both blocks, and the Amiga's `body.dax` holds `0D`, `18` and
#: `22` as one repeated block where DOS's `0D` and `18` are one picture and
#: its `22` another -- 19 distinct bodies of 21 ids on the Amiga against
#: DOS's 20.  Rendered in menu order the twelve agree position by position
#: on eleven of twelve.  `tools/amigaportraitmenu.py` re-derives all of it.
AMIGA_POOL_OF_RADIANCE_MENU = PortraitTables(
    heads=POOL_OF_RADIANCE_MENU.heads,
    bodies=(0x01, 0x02, 0x03, 0x04, 0x07, 0x08,
            0x12, 0x05, 0x1A, 0x21, 0x23, 0x25),
    source="the stored Amiga Pool of Radiance creation menu "
           "(goldbox/portraits.py)",
)

#: The port keys :func:`stored_tables` knows.  The C64 and DOS share a menu
#: and the Amiga has its own, so this is two tables rather than three.
C64_PORT, DOS_PORT, AMIGA_PORT = "c64", "dos", "amiga"

#: The stored menu per game key.  A title with no entry has no sheet
#: portrait to convert, and :func:`stored_tables` answers `None` for it.
STORED_MENUS: dict[str, PortraitTables] = {
    POOL_OF_RADIANCE_KEY: POOL_OF_RADIANCE_MENU,
}

#: The same, for the Amiga, which numbers its eighth body differently.  Kept
#: as a second dictionary rather than as a `(key, port)` one so that every
#: caller written before the Amiga was read keeps the menu it was written
#: against.
STORED_AMIGA_MENUS: dict[str, PortraitTables] = {
    POOL_OF_RADIANCE_KEY: AMIGA_POOL_OF_RADIANCE_MENU,
}

#: The port whose art ids the **neutral record** spells a menu position with.
#:
#: `goldbox/neutral.py`'s `portrait_head` and `portrait_body` are described
#: there as "the art's own id -- the C64 record's spelling", and that is what
#: makes this constant necessary rather than decorative: the neutral value is
#: a menu **position**, written down as the id the C64 gives that position.
#: So every reader turns its own record's byte into a position and then into
#: that spelling, and every writer does the reverse -- and the table that
#: does the spelling is the C64's on all three ports, including the Amiga's
#: own codec (#480).
NEUTRAL_MENU_PORT = C64_PORT


def stored_tables(game=None, port: str | None = None
                  ) -> PortraitTables | None:
    """The creation menu this module carries for `game`, or `None`.

    `game` is a `goldbox.c64_port.C64Container`, anything else carrying a `key`, or the
    key itself, and `None` means Pool of Radiance for the same reason
    :func:`draws_sheet_portrait` says it does.  This is what a conversion
    falls back to when nobody handed it tables read off the player's own
    disks: `goldbox.dos_codec.to_neutral` asks here before it gives up on the
    portrait, so a DOS Pool of Radiance party converts with every face its
    own whether or not a `POOL<n>.D64` is anywhere in reach.  Reading the
    player's disks (:func:`tables_from_disks`, :func:`tables_from_amiga_disks`)
    is still there for anybody who wants the table off their own copy.

    `port` is `"c64"`, `"dos"`, `"amiga"` or `None`.  **`None` is the C64's
    and DOS's shared menu**, which is what every caller written before the
    Amiga was read means, and asking for `"amiga"` is what gets that port's
    own numbering of the same twelve choices (#194).  An unknown port name
    raises rather than quietly answering with another port's table.

    **A conversion wants :func:`neutral_menu` and not this**, whichever ports
    are on its two ends.  Asking here for `"amiga"` and then looking a
    neutral value up in the answer is the mistake `#480 (An Amiga character
    whose body is the menu's eighth arrives on the C64 or DOS wearing a
    different body, because the Amiga reader uses the C64 and DOS menu)`
    is about.
    """
    key = getattr(game, "key", game)
    if key is None:
        key = POOL_OF_RADIANCE_KEY
    if port is None or port in (C64_PORT, DOS_PORT):
        return STORED_MENUS.get(str(key))
    if port == AMIGA_PORT:
        return STORED_AMIGA_MENUS.get(str(key))
    raise PortraitError(
        f"{port!r} is not a port this module carries a creation menu for: "
        f"{C64_PORT!r}, {DOS_PORT!r}, {AMIGA_PORT!r} or None")


def neutral_menu(game=None) -> PortraitTables | None:
    """The menu a conversion resolves against, in every direction.

    The neutral record's `portrait_head` and `portrait_body` hold a **menu
    position**, spelled as the art id the C64 gives that position
    (:data:`NEUTRAL_MENU_PORT`, and `goldbox/neutral.py`'s own description of
    the two fields).  So this is the table that turns one into the other, and
    it is the same table on every port:

    * a **C64** record already stores that id, so its codec copies the byte;
    * a **DOS** record stores the position, and `goldbox.dos_codec.to_neutral` and
      `goldbox.dos_codec.write` cross it with `body_art` and `body_position` here;
    * an **Amiga** record stores the position too, and `amiga_por.py` and
      `amiga_later.py`'s writers cross it with the same two methods and the same table.

    **The Amiga's own table is not used for this and must not be.** The
    twelve slots correspond across all seven ports of Pool of Radiance and
    the slot is the character's identity; the Amiga's stored byte is only its
    own index into its own art, and `AMIGA_POOL_OF_RADIANCE_MENU` exists to
    say which picture that is.  Resolving a neutral value in it reports
    position 8 as a body the Amiga cannot hold, which is
    `#480 (An Amiga character whose body is the menu's eighth arrives on the
    C64 or DOS wearing a different body, because the Amiga reader uses the
    C64 and DOS menu)` and is settled:
    `docs/188-the-sheet-portrait-per-title.md` opens with it.

    `game` is what :func:`stored_tables` takes, and `None` answers `None` for
    a title with no sheet portrait, the same way.
    """
    return stored_tables(game, port=NEUTRAL_MENU_PORT)
