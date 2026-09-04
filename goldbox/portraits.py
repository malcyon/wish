"""The character sheet's portrait, and the one enumeration both ports share.

A Pool of Radiance character is drawn on the sheet as a **head over a body**,
chosen at creation from a menu of fourteen heads and twelve bodies.  Both
ports store that choice in the character record, and they store it
differently:

* the **C64** keeps the art's own id -- `portrait_head` at `0x0FE` is the two
  hex digits of a filename, so `$2D` is the file `HEAD2D` (`docs/140-loaded-
  files-cache.md`, loader slots 13 and 14);
* **DOS** keeps the **menu position**, one-based -- `portrait_head` at `0x0BB`
  is 1 to 14 and `portrait_body` at `0x0BC` is 1 to 12.

The art itself is the same art with the same numbering.  DOS packs it into one
`.DAX` container per disk instead of one file per portrait, and the block ids
inside `HEAD<n>.DAX` are exactly the ids of the `HEAD*` files on the C64's
`POOL<n>.D64` -- 41 head ids and 21 body ids, equal as sets and equal disk by
disk, all sixteen containers (`docs/117-save-conversion.md`, "The portrait").

So the two ports are joined by the menu: **DOS position n is C64 art id
`heads[n - 1]`**, and the table of ids is in the player's own files on both
sides.  This module reads it rather than carrying a copy, the way
`goldbox/iconparts.py` reads the icon menu's option tables out of `SPELLE64`.
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


# ---------------------------------------------------------------------------
# Finding the tables
# ---------------------------------------------------------------------------
def _runs(data: bytes, first: int, first_ok: set[int],
          second: int, second_ok: set[int]) -> list[int]:
    """Offsets where `first` then `second` strictly increasing ids sit.

    Both runs must be strictly increasing and every byte of each must name
    art that exists, which is what makes the search a *reading* rather than a
    guess -- and what makes it single-valued in both files we have.
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
        if all(x < y for x, y in zip(a, a[1:])) and \
           all(x < y for x, y in zip(b, b[1:])):
            out.append(i)
    return out


def _only(hits: list[int], where: str) -> int:
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise PortraitError(
            f"{where}: no run of {HEAD_COUNT} head ids and {BODY_COUNT} body "
            f"ids in it -- this is not the Pool of Radiance the portraits "
            f"beside it belong to")
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
    -- the one `goldbox.dos.write_dos_save` already takes so the party's own
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


def tables_from_c64(disk: str | pathlib.Path) -> PortraitTables:
    """The same tables out of the C64 `GEN` overlay, for a cross-check.

    `GEN` is on `POOL3`, the character-creation side, beside the `HEAD*` and
    `BODY*` files its two tables name.  The order is the other way round
    there -- bodies first -- which is the only difference between the ports.
    """
    from .d64 import D64, D64Error

    disk = pathlib.Path(disk)
    image = D64(disk.read_bytes())
    ids: dict[str, set[int]] = {"HEAD": set(), "BODY": set()}
    for entry in image.directory():
        name = entry.raw_name.rstrip(b"\xa0").decode("latin1")
        for stem in ids:
            if name.startswith(stem) and len(name) == len(stem) + 2:
                try:
                    ids[stem].add(int(name[len(stem):], 16))
                except ValueError:
                    pass
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
    at = _only(_runs(data, BODY_COUNT, ids["BODY"], HEAD_COUNT, ids["HEAD"]),
               f"{disk.name}:GEN")
    return PortraitTables(
        heads=tuple(data[at + BODY_COUNT:at + BODY_COUNT + HEAD_COUNT]),
        bodies=tuple(data[at:at + BODY_COUNT]),
        source=f"{disk.name}:GEN @{at}")
