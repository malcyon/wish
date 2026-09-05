"""The areas of Pool of Radiance, and the names to put on a map.

This module is the *single source of truth* for the area table. It replaces the
hand-written dictionary that used to live in `automap/state.py`, and the
thirty-row table in `docs/118-debug-mode.md` is the same data written out.

**The key is the area id, not the map file.** An area is a script -- `ECL<id>`,
with the id in hex, so area 21 is `ECL15` -- and the game's own transition
opcode `NEWECL` takes exactly that id. The map is a consequence of the script,
not the other way round, and the relation is not a bijection:

* **thirty scripts, twenty-nine maps.** `ECL0C` does not exist at all, so id 12
  is absent from the table;
* **four areas have no map.** `ECL08` (Phlan City Hall), `ECL0B` (the training
  hall), `ECL13` (Cave of Diogenes) and `ECL1E` issue no `LOADFILES` and never
  put a `GEO` on the screen;
* **three areas carry two maps each.** `ECL10`, `ECL18` and `ECL1D` each load
  two `GEO`s from the one script;
* **three areas are outdoors.** Areas 25-27 load a `SQRDATA` as well as a
  `GEO`; `LOADFILES` picks the file type from `$49E6`, not from the operand.

So `Area.geos` is a tuple, which is empty for the four mapless areas and holds
two entries for the three doubled ones, and `areas_for_geo` returns a tuple as
well -- there is nothing in the format that stops two scripts naming one map,
and `ECL07` already loads `GEO03` on its way into area 5.

Names come from `docs/88-map-files.md` and two write-ups since lost,
`work/reports/world-map.md` and `work/reports/quest-flags.md`; arrival squares were harvested from the
departing scripts' `SAVE <n>, mapX` and the arriving scripts' entry 4. Fourteen
areas have no known arrival square and say so with `arrival = None`. FastTraveling
into all fifteen that had none at the time and watching where the party ends up
P20, whose write-up `work/reports/p20-arrivals.md` is lost: it found area 21's
square in `ECL15`'s own bytecode, and `landing_square` at the foot of this module is the fallback that
measurement put in place of "the first square with a passable edge".

**A name is a title, so it is title-cased**, leading article included: "The
Slums", not "the Slums". The table used to mix the two -- proper names in
capitals, descriptions in lower case -- and the seam showed in the dropdown,
which is a list of titles and nothing else. Short function words inside a name
stay down ("Valjevo Castle, a Floor", "Temple of Bane").

## Titles

`GEO15` exists in **both** Pool of Radiance and Curse of the Azure Bonds and
means a different place in each (`docs/120-curse-testing.md`), so a table keyed
by map file alone cannot help lying. `GEO_NAMES` is therefore keyed by game
title first, and `area_name` degrades an unrecognised title -- or an
unrecognised map -- to `"area 21"`, read straight off the file's own hex
digits, rather than to a confident wrong answer.

`AREAS_SILVER_BLADES` is the second table, built for
`#20 (Build an area table for Silver Blades)` and read off that title's own
six sides by `tools/areatable.py`. It shares the `Area` shape and nothing else:
sparse ids, no names, disk sides 1-6, and five areas whose map is not their own
id. Its own comment carries what does not carry over, and every row is
PROBABLE.

Enumerating maps by count or assuming a `GEO00` is wrong for every Gold Box
title after this one: Curse's ids are sparse and chapter-grouped, and Silver
Blades, Champions and Death Knights start at `$10` or `$20`
(write-up lost, `work/reports/goldbox-inventory.md`; the per-title base
addresses are asserted in
`tests/test_curse.py::test_the_addresses_are_the_ones_measured`). Scan a
directory; never a range.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Iterator, Mapping

from goldbox.layout import Confidence

__all__ = [
    "Confidence",
    "POOL_OF_RADIANCE",
    "CURSE_OF_THE_AZURE_BONDS",
    "SECRET_OF_THE_SILVER_BLADES",
    "Arrival",
    "Area",
    "AREAS",
    "AREAS_SILVER_BLADES",
    "AREAS_BY_ID",
    "TABLES",
    "areas_for",
    "areas_for_title",
    "MISSING_ID",
    "area",
    "area_in",
    "areas_for_geo",
    "geos_for_area",
    "geo_number",
    "geo_name",
    "GEO_NAMES",
    "area_name",
    "components",
    "landing_square",
]


#: Game titles this module knows about. Plain strings on purpose, and the seam
#: with `goldbox/games.py`: these are `Game.title`, so a caller holding a descriptor
#: writes `areas.area_name(geo, game.title)` and neither module imports the
#: other. `tests/test_areas.py` pins the two spellings together.
POOL_OF_RADIANCE = "Pool of Radiance"
CURSE_OF_THE_AZURE_BONDS = "Curse of the Azure Bonds"
SECRET_OF_THE_SILVER_BLADES = "Secret of the Silver Blades"

#: `ECL0C` is not on any of the nine disks, so there is no area 12. Kept as a
#: named constant because "the ids are 0-30 with one hole" is a fact about the
#: game that a caller iterating a range would otherwise have to rediscover.
MISSING_ID = 12

#: Facing, as the game stores it in `$C04D`.
FACINGS = "NESW"


@dataclass(frozen=True)
class Arrival:
    """The square the game itself puts the party on when it enters an area.

    `facing` is None where the departing script sets the square but not the
    direction -- area 7 is the one such case.
    """

    x: int
    y: int
    facing: int | None = None

    @property
    def facing_letter(self) -> str:
        if self.facing is None:
            return ""
        return FACINGS[self.facing] if 0 <= self.facing < 4 else "?"

    def __str__(self) -> str:
        letter = self.facing_letter
        return f"{self.x},{self.y} {letter}".strip()


@dataclass(frozen=True)
class Area:
    """One `ECL` script, and whatever map or maps it loads."""

    id: int
    #: None for `ECL1E`, which has no `LOADFILES`, no `NEWECL` pointing at it
    #: and no name anybody has been able to attach to it.
    name: str | None
    #: Which disk side carries the script -- 1-8 in Pool of Radiance, 1-6 in
    #: Secret of the Silver Blades. This is what a fasttravel writes to the
    #: loader's disk byte (`$6E12` in Pool of Radiance, `$7F12` in Silver
    #: Blades) and what the loader will prompt for.
    disk: int
    #: The `GEO` files the script statically loads, in the order it loads them.
    #: Empty for the four mapless Pool of Radiance areas, and for the two
    #: Silver Blades areas whose map is loaded by the script that sends the
    #: party to them.
    geos: tuple[str, ...] = ()
    #: The overland square-data file, for areas 25-27 only.
    sqrdata: str | None = None
    arrival: Arrival | None = None
    #: Where a fast travel puts the party on the travel grid, window-local
    #: (x, y), for areas 25-27 only -- written to `$49C3`/`$49C4`.
    #: `arrival` is the `GEO` square in `$C04B`, and stays None for these
    #: three: `$C04B` is not `GDRIVE00`'s square outdoors, so a caller must
    #: never write one there for a window. `newecl_writes` in
    #: `automap/actions.py` writes this field instead
    #: (`#178 (Fast Travel to the wilderness leaves the party on whatever
    #: overland square it last stood on)`).
    #:
    #: **`confidence` below does not grade this field.** It is one grade for
    #: the row and it was written for the area itself, so a row could read
    #: CONFIRMED while its `overland` was still inferred. All three are now
    #: CONFIRMED in the running game -- a party arrived on each square and
    #: walked off it -- but the two gradings remain separate things, and the
    #: per-square evidence is in the comment beside the rows. Anything that
    #: ever shows a confidence to a user must not read this field's
    #: trustworthiness off `confidence`; raised in the code review of #178 on
    #: 2026-09-02, when nothing displayed it yet and the trap was one
    #: dropdown column away.
    overland: tuple[int, int] | None = None
    confidence: Confidence = Confidence.UNKNOWN
    #: Names for individual maps of a two-map area, where the second map is a
    #: place in its own right -- area 29's `GEO20` is the catacombs under
    #: Kuto's Well, not Kuto's Well.
    geo_names: Mapping[str, str] = field(default_factory=dict)
    #: **`geos` may be incomplete: do not pick a square off `geos[0]`.** Two
    #: different mechanisms set it, one per title.
    #:
    #: Pool of Radiance areas 3 and 5 issue no static `LOADFILES` at all and
    #: choose their map at run time with `GETTABLE ..., mapDir`; their `geos`
    #: entry is the doc's inference from the id, not something the bytecode
    #: says. Silver Blades areas `$31` and `$32` issue none either, and their
    #: map is loaded by `ECL30`, the script that sends the party to them --
    #: `geos` is empty there rather than a guess.
    #:
    #: **And the inference is wrong for both.** FastTraveled into, area 3 loaded
    #: `GEO05` and area 5 loaded `GEO04` -- `$6E15` and the bytes at `$0400`
    #: agreeing (write-up lost, `work/reports/p20-arrivals.md`). So a square
    #: chosen off
    #: `geos[0]` is a square off a map the game was never going to show, and a
    #: caller with no arrival square should write none for these two and let
    #: the arriving script place the party, which is what it does.
    dynamic_geo: bool = False
    #: Whether a debug fasttravel may enter this area at all. False for `ECL1E`
    #: alone: it is the attract-mode demo, and fasttraveling there ends the session.
    #: `$C04B`-`$C04D` read `254, 127, 16`, no `GEO` is resident, no status
    #: line and no command bar appear, and the program counter never returns
    #: to `DUNGEON`'s key-wait loop, so **no later fasttravel can be started**
    #: (write-up lost, `work/reports/p20-arrivals.md`).
    fasttravelable: bool = True
    #: How this title names a disk side, for `label`. Pool of Radiance's sides
    #: are `POOL1`-`POOL8` and Silver Blades' are `SILVER-1`-`SILVER-6`, and a
    #: dropdown that said `POOL3` under a Silver Blades session would be
    #: naming a disk the player does not own.
    side_name: str = "POOL{}"

    @property
    def ecl(self) -> str:
        return f"ECL{self.id:02X}"

    @property
    def geo(self) -> str | None:
        """The one map, where there is exactly one. None for none *and* for two.

        Callers that cannot cope with an area having two maps should be reading
        `geos` and deciding what to do, not silently taking the first.
        """
        return self.geos[0] if len(self.geos) == 1 else None

    @property
    def has_map(self) -> bool:
        return bool(self.geos)

    @property
    def outdoors(self) -> bool:
        return self.sqrdata is not None

    def name_for(self, geo: str) -> str | None:
        """This area's name for one of its maps."""
        return self.geo_names.get(geo, self.name)

    @property
    def label(self) -> str:
        """One line for a dropdown: `New Phlan - GEO00, POOL3`."""
        maps = ", ".join(self.geos) or "no map"
        if self.sqrdata:
            maps = f"{maps}, {self.sqrdata}"
        return (f"{self.name or self.ecl} - {maps}, "
                f"{self.side_name.format(self.disk)}")


def _a(id: int, name: str | None, disk: int, geos: tuple[str, ...],
       arrival: Arrival | None, confidence: Confidence, **kw) -> Area:
    return Area(id=id, name=name, disk=disk, geos=geos, arrival=arrival,
                confidence=confidence, **kw)


C = Confidence.CONFIRMED
P = Confidence.PROBABLE
U = Confidence.UNKNOWN

#: The table. Ordered by id, with 12 absent because `ECL0C` is absent.
#:
#: The five POOL5 floors are a castle because `ECL07` writes ledger flag 20 and
#: prints the party leaving one; **which floor is which is not known**, which is
#: why they are PROBABLE and why four of them share a name.
AREAS: tuple[Area, ...] = (
    _a(0, "New Phlan", 3, ("GEO00",), Arrival(15, 1, 3), C),
    _a(1, "Buccaneer Base", 6, ("GEO01",), Arrival(8, 0, 2), C),
    _a(2, "Cadorna Textile House", 4, ("GEO02",), Arrival(0, 4, 3), C),
    _a(3, "Valjevo Castle, a Floor", 5, ("GEO03",), None, P, dynamic_geo=True),
    _a(4, "Valjevo Castle, a Floor", 5, ("GEO04",), None, P),
    _a(5, "Valjevo Castle, a Floor", 5, ("GEO05",), None, P, dynamic_geo=True),
    _a(6, "Valjevo Castle, a Floor", 5, ("GEO06",), Arrival(4, 15, 0), P),
    _a(7, "Valjevo Castle, the Pool", 5, ("GEO07",), Arrival(5, 7), P),
    _a(8, "Phlan City Hall", 3, (), None, C),
    _a(9, "Stojanow Gate", 2, ("GEO09",), None, C),
    _a(10, "Valhingen Graveyard", 4, ("GEO0A",), Arrival(0, 4, 3), C),
    _a(11, "The Training Hall", 3, (), None, C),
    _a(13, "The Kobold Caves", 8, ("GEO0D",), Arrival(6, 15, 0), C),
    _a(14, "Kovel Mansion", 3, ("GEO0E",), Arrival(4, 0, 2), C),
    _a(15, "Mendor's Library", 2, ("GEO0F",), None, C),
    _a(16, "The Lizardman Keep", 8, ("GEO10", "GEO1E"), Arrival(8, 14, 0), C),
    _a(17, "The Nomad Camp", 7, ("GEO11",), Arrival(1, 14, 1), C),
    _a(18, "Podol Plaza", 1, ("GEO12",), Arrival(0, 4, 3), C),
    _a(19, "Cave of Diogenes", 6, (), None, C),
    _a(20, "The Slums", 2, ("GEO14",), None, C),
    # `ECL15 $9A92` reads `SAVE 1, [$4A02] / SAVE 0, mapDir / SAVE 8, mapX /
    # SAVE 14, mapY`, immediately before the boat message, so the square is
    # the script's own and is gated on the scratch flag `$4A02` being zero.
    # Watched placing a fasttraveled-in party (write-up lost,
    # `work/reports/p20-arrivals.md`).
    _a(21, "Sokol Keep", 4, ("GEO15",), Arrival(8, 14, 0), C),
    _a(22, "Yarash's Pyramid", 7, ("GEO16",), Arrival(15, 7, 1), C),
    _a(23, "Yarash's Pyramid, Lower", 7, ("GEO17",), Arrival(15, 0, 2), P),
    _a(24, "Temple of Bane", 1, ("GEO18", "GEO1F"), Arrival(15, 4, 3), C),
    # `overland`: window-local (x, y), written to $49C3/$49C4 by a fast
    # travel (#178).
    #
    # West Window CONFIRMED in the running game, 2026-09-02, by
    # `tools/windowsquare.py` on pool slot 0: a fast travel out of the Slums
    # with $49C3/$49C4 seeded (0, 0) came up on (14, 29) reading `OUTDOORS
    # 21:15 14,29`, with the movement bar up and no event, and all eight
    # compass digits walked the party off it. No script names an (x, y) in
    # this window at all, so until that run the square was argued from the
    # crossing column and the row the other two windows use.
    #
    # Middle Window CONFIRMED -- ECL00 $9C04's WEST boat landing, watched in
    # the same run: arrived on (7, 29) and walked off it north, north-east,
    # east, west and north-west.
    #
    # East Window CONFIRMED -- ECL00 $9C2E's EAST boat landing, watched in
    # the same run: arrived on (9, 29) and walked off it north, north-east,
    # west and north-west.
    #
    # **Both are event squares and the West one is not.** Arriving on (7, 29)
    # or (9, 29) draws the boat and asks whether to sail back to Phlan, and
    # the player answers STAY before walking anywhere; each window's script
    # words that question differently, so they are two events and not one.
    # Arriving on (14, 29) puts up the movement bar and nothing else.
    _a(25, "Wilderness, West Window", 6, ("GEO19",), None, C,
       sqrdata="SQRDATA04", overland=(14, 29)),
    _a(26, "Wilderness, Middle Window", 7, ("GEO1A",), None, C,
       sqrdata="SQRDATA05", overland=(7, 29)),
    _a(27, "Wilderness, East Window", 8, ("GEO1B",), None, C,
       sqrdata="SQRDATA06", overland=(9, 29)),
    _a(28, "Zhentil Keep Outpost", 6, ("GEO1C",), Arrival(7, 0, 2), C),
    _a(29, "Kuto's Well", 8, ("GEO1D", "GEO20"), None, C,
       geo_names=MappingProxyType({"GEO20": "Kuto's Well Catacombs"})),
    _a(30, None, 1, (), None, U, fasttravelable=False),
)

AREAS_BY_ID: Mapping[int, Area] = MappingProxyType({a.id: a for a in AREAS})


def _s(id: int, disk: int, geos: tuple[str, ...],
       arrival: Arrival | None,
       confidence: Confidence = Confidence.PROBABLE, **kw) -> Area:
    """One Silver Blades row. No name is known for any of them yet.

    `confidence` grades the **id, the side and the map** -- the three columns
    a driven arrival measures. It does not grade `arrival`; see the table's
    own comment, where five of ten measured squares differ from the static
    reading because the arriving script computes them.
    """
    return Area(id=id, name=None, disk=disk, geos=geos, arrival=arrival,
                confidence=confidence, side_name="SILVER-{}", **kw)


#: Secret of the Silver Blades, read off its own six sides by
#: `tools/areatable.py` (`#20 (Build an area table for Silver Blades)`).
#: Twenty-two scripts, seventeen maps, `ECL64` and `ECL65` excluded because
#: their first four bytes do not decode as the `GOTO` an area script opens
#: with -- they are on every side and are the machine, not a place.
#:
#: **Every row is CONFIRMED**, and each one the same way: a party has been put
#: in that area on a running machine and the landing measured. Twenty-one were
#: entered by a trip through `automap.actions.FastTravel` -- 22 hops across
#: nine driven sessions -- and `$11` is where a loaded party starts, so it was
#: read where it stood. `#20 (Build an area table for Silver Blades)`,
#: `work/issue20/land1`-`land9`.
#:
#: **The map column is 21 of 21 exact**, an unmasked 1024-byte compare of
#: `$0400` against the copy on the player's own disk, no fingerprint and no
#: filename. That includes all five rows where an area's map is not its own id
#: -- `$04` and `$10` both loaded `GEO10`, `$30` and `$33` both `GEO31`, `$34`
#: `GEO32`, `$63` `GEO62` -- and `$11`, where a sweep of all of RAM found none
#: of the seventeen maps anywhere, which is what a row with no `geos` claims.
#:
#: **The side column was confirmed by the game asking for it.** This loader
#: letters its sides: `INSERT SIDE A` through `INSERT SIDE F` for sides 1 to
#: 6. Six letters, six sides, each drawn when a party was sent to an area
#: this table puts on that side, each answered by attaching it.
#:
#: **`confidence` grades the id, the side and the map, and not `arrival`.**
#: Twelve arrivals into a row that carries a square have been measured, with
#: `(1, 1, 2)` -- a square no row carries -- written into `$C04B` first, so
#: that a table square read back afterwards could only be the arriving
#: script's own doing. **Five reproduce the static reading, six land somewhere
#: else, and one writes no square at all**:
#:
#: | area | came from | this table | where the party actually landed |
#: |---|---|---|---|
#: | `$30` | `$11` | 3,3 E | 3,3 E |
#: | `$41` | `$60` | 13,9 E | 13,9 E |
#: | `$44` | `$60` | 7,15 N | 7,15 N |
#: | `$50` | `$11` | 1,11 E | 1,11 E |
#: | `$62` | `$11` | 0,15 E | 0,15 E |
#: | `$10` | `$11` | 15,8 W | 3,3 S |
#: | `$42` | `$11` | 12,13 N | 0,7 W |
#: | `$60` | `$50` | 15,0 W | 0,7 E |
#: | `$60` | `$42` | 15,0 W | 15,9 W |
#: | `$61` | `$63` | 15,0 W | 0,15 E |
#: | `$04` | `$52` | 10,8 E | 9,8 W |
#: | `$63` | `$62` | 0,0 S | **nothing written** |
#:
#: Four rows with no `arrival` at all placed the party anyway, from the one
#: came-from each was entered with: `$20` at 10,14 W from `$21`, `$21` at
#: 15,9 N from `$61`, `$40` at 15,7 W from `$44` and `$34` at 4,0 S from
#: `$11`. They are recorded here rather than in the rows, because one
#: measurement from one came-from is exactly the evidence `$60` below shows to
#: be insufficient. Four more wrote nothing and left the deliberately wrong
#: square standing: `$31`, `$32`, `$33` and `$51`.
#:
#: `$60` twice, from two different areas, landing in two different places, is
#: the proof rather than an argument: **an arrival square here can depend on
#: `$4BF2`**, and a fast travel hands the arriving script a came-from it may
#: have no branch for. `ECL34` and `ECL51` were already known to branch that
#: way when the table was built; `ECL10`, `ECL42`, `ECL60` and `ECL61` do it
#: too and `tools/areatable.py` recorded the constant on the branch it
#: happened to walk. `ECL63` writes no square at all on this path: the
#: deliberately wrong square survived it untouched.
#:
#: None of that makes the field harmful -- the arriving script wins wherever
#: it writes one -- but it is not a promise about where a fast-travelled
#: party ends up. The disk column is the strongest part of the table: the
#: side is where the file sits in the directory, 29 of 29 static
#: `SAVE <n>, [$7F12]` before a `NEWECL` name that same side with 0
#: disagreeing, and the loader has now asked for six of them out loud.
#:
#: Four things do **not** carry over from Pool of Radiance, and each is a trap
#: for anything that reads this table expecting the older shape.
#:
#: * **The ids are sparse and blocked by side.** `$04`, `$10`-`$11`,
#:   `$20`-`$22`, `$30`-`$34`, `$40`-`$42`, `$44`, `$50`-`$52`, `$60`-`$63`.
#:   The high nibble is the side for twenty-one of the twenty-two, and `ECL04`
#:   is the exception: it sits on side 1. Never enumerate by range.
#: * **An area's map is not its own id in the `$3x` block.** `ECL30` loads
#:   `GEO31`, `ECL33` loads `GEO31` as well, `ECL34` loads `GEO32`, `ECL04`
#:   loads `GEO10` and `ECL63` loads `GEO62`. Pool of Radiance's rule --
#:   every script's `LOADFILES` first operand is its own id -- is false here
#:   in five of the twenty-two.
#: * **The arriving script places the party, not the departing one.** All
#:   twelve squares here come from the area's own entry 4; exactly one
#:   `NEWECL` in the whole title writes a square before it (`ECL44` sends the
#:   party to area `$40` at 7,15 N), and that one contradicts `ECL40`'s own
#:   entry 4, so area `$40` gets no square. Pool of Radiance harvested most of
#:   its sixteen the other way round.
#: * **A square is often computed rather than constant.** `ECL21` reads its
#:   through `GETTABLE` indexed by a variable, `ECL34` and `ECL51` branch on
#:   the came-from area `$4BF2`, and `ECL34` *adds* 3 to whatever `$C04B`
#:   already holds. Nine rows have no `arrival` for that reason, and writing
#:   one for them would be inventing it.
AREAS_SILVER_BLADES: tuple[Area, ...] = (
    # Nothing in any script issues a `NEWECL 4`, and `ECL04` has no re-entry
    # guard (`COMPARE [$4BF2], own id / IF= / EXIT`) where twenty of the
    # other twenty-one do. It looks like the opening scene and not a place
    # the game returns to.
    #
    # **It can be entered.** A party fast-travelled here from `$52` and the
    # game did the ordinary thing: it asked for side 1, `GEO10` came up at
    # `$0400` byte for byte, and `ECL04` ran and placed the party -- at 9,8 W
    # rather than the 10,8 E its entry 4 reads as. So the UNKNOWN this comment
    # carried is answered; what is still unknown is whether the opening scene
    # leaves anything in a state a later area minds.
    _s(0x04, 1, ("GEO10",), Arrival(10, 8, 1), Confidence.CONFIRMED),
    _s(0x10, 1, ("GEO10",), Arrival(15, 8, 3), Confidence.CONFIRMED),
    _s(0x11, 1, (), None, Confidence.CONFIRMED),
    _s(0x20, 2, ("GEO20",), None, Confidence.CONFIRMED),
    _s(0x21, 2, ("GEO21",), None, Confidence.CONFIRMED),
    _s(0x22, 2, ("GEO22",), Arrival(14, 14, 0), Confidence.CONFIRMED),
    # `ECL30` is a twelve-option menu that dispatches on to `$31`, `$32`,
    # `$33` and `$20`, storing which option was chosen in `[$4C69]` -- and
    # `ECL31`'s entry 4 reads `[$4C69]` back. So one script and one map serve
    # several places, and a fast travel into `$31` or `$32` that does not set
    # `[$4C69]` arrives on a level nobody chose. It is also the only script
    # anywhere that names `GEO30`, in a subroutine it calls before
    # `NEWECL 49` and `NEWECL 50` under a condition, which is why `$31` and
    # `$32` have no map of their own here.
    #
    # `geos` says what the script loads, so `ECL30` carries both -- `GEO31`
    # from its entry 4 and `GEO30` from the subroutine above. **They are
    # probably not both this area's**: the `GEO30` load is what `$31` and
    # `$32` walk on, and a caller picking a landing square off `geos` for
    # area `$30` should take `geos[0]`. Pool of Radiance's three two-map areas
    # are a genuinely different thing -- one place with two floors.
    #
    # Driven, `geos[0]` is right and `$30` does not hold the party. A fast
    # travel here ran `ECL30`'s entry 4 -- `GEO31` resident, byte for byte,
    # and the party at 3,3 E -- and then `NEWECL 51` on the spot, so `$7F1B`
    # read `$33` a moment later. `GEO30` was never loaded. So the row is right
    # about what `ECL30` does and a caller must not assume the party stays.
    _s(0x30, 3, ("GEO31", "GEO30"), Arrival(3, 3, 1), Confidence.CONFIRMED),
    # **Measured, and it is worse than "no map of their own".** Fast-travelled
    # into `$31` and then `$32` from `$33`, the block at `$0400` stayed
    # `GEO31` -- `$33`'s map, left behind -- through both, because neither
    # script issues a `LOADFILES` and nothing else loads one. So a party
    # arriving here walks on whatever map the area it came from was showing.
    # `dynamic_geo` is what stops a caller picking a landing square off a map
    # the game was never going to draw, and it is doing real work.
    #
    # And both printed `LEVEL 0` on arrival, which is `ECL31` reading
    # `[$4C69]` -- the option chosen from `ECL30`'s twelve-item menu -- out of
    # the scratch a fast travel has just wiped. The warning above this table
    # said a trip that does not set `[$4C69]` arrives on a level nobody chose;
    # the game says so itself.
    _s(0x31, 3, (), None, Confidence.CONFIRMED, dynamic_geo=True),
    _s(0x32, 3, (), None, Confidence.CONFIRMED, dynamic_geo=True),
    _s(0x33, 3, ("GEO31",), None, Confidence.CONFIRMED),
    _s(0x34, 3, ("GEO32",), None, Confidence.CONFIRMED),
    # `ECL44` writes 7,15 N before `NEWECL 64`; `ECL40`'s own entry 4 writes
    # 12,0 S. Two routes in, two squares, and nothing says which a fast
    # travel should imitate -- so neither.
    _s(0x40, 4, ("GEO40",), None, Confidence.CONFIRMED),
    _s(0x41, 4, ("GEO41",), Arrival(13, 9, 1), Confidence.CONFIRMED),
    _s(0x42, 4, ("GEO42",), Arrival(12, 13, 0), Confidence.CONFIRMED),
    _s(0x44, 4, ("GEO44",), Arrival(7, 15, 0), Confidence.CONFIRMED),
    _s(0x50, 5, ("GEO50",), Arrival(1, 11, 1), Confidence.CONFIRMED),
    _s(0x51, 5, ("GEO51",), None, Confidence.CONFIRMED),
    _s(0x52, 5, ("GEO52",), None, Confidence.CONFIRMED),
    _s(0x60, 6, ("GEO60",), Arrival(15, 0, 3), Confidence.CONFIRMED),
    _s(0x61, 6, ("GEO61",), Arrival(15, 0, 3), Confidence.CONFIRMED),
    _s(0x62, 6, ("GEO62",), Arrival(0, 15, 1), Confidence.CONFIRMED),
    # `ECL63` loads `GEO62`, one of the five rows where the map is not the
    # area's own id -- CONFIRMED, the block at `$0400` was `GEO62` byte for
    # byte after a driven arrival in `$63`.
    _s(0x63, 6, ("GEO62",), Arrival(0, 0, 2), Confidence.CONFIRMED),
)

#: Game title -> that title's areas. Curse is absent rather than empty: its
#: twenty-three scripts read the same way and nobody has built the table yet,
#: and an empty tuple would say we had looked and found none.
TABLES: Mapping[str, tuple[Area, ...]] = MappingProxyType({
    POOL_OF_RADIANCE: AREAS,
    SECRET_OF_THE_SILVER_BLADES: AREAS_SILVER_BLADES,
})


def _by_geo() -> Mapping[str, tuple[Area, ...]]:
    index: dict[str, list[Area]] = {}
    for a in AREAS:
        for name in a.geos:
            index.setdefault(name, []).append(a)
    return MappingProxyType({k: tuple(v) for k, v in index.items()})


_BY_GEO = _by_geo()


def areas_for(title: str | None) -> tuple[Area, ...]:
    """Every area of this title that anybody has written down.

    **This is the knowledge, not the permission.** It answers with Silver
    Blades' twenty-two rows; `areas_for_title` below is the one a fast travel
    asks, and it still refuses them. Use this for labelling a map, for a
    report, or for anything that only reads.
    """
    return TABLES.get(title or "", ())


def areas_for_title(title: str | None) -> tuple[Area, ...]:
    """Every area a fast travel may offer, which is nothing for four of six.

    **`AREAS` is Pool of Radiance's and only Pool of Radiance's.** Every row
    carries a `POOL` disk number and an `ECL` id, and neither means anything in
    another title -- Curse's disks are not numbered like Pool of Radiance's and
    its `ECL` ids have never been decoded (`docs/138-multiple-games.md` §§2, 6).
    A caller that is about to *write* one of those numbers into a running
    machine must ask this rather than reading `AREAS`, and must offer nothing
    when it comes back empty. Falling back to Pool of Radiance's list is the
    one answer that corrupts.

    **Silver Blades is offered now, and it was not before.** Two things had to
    be true and both are. `#15 (Fast Travel for more than one Gold Box title)`
    moved the addresses off Pool of Radiance's, so `automap/actions.py` writes
    `$7F12`, `$7F1B`, `$4BF2`, the wipe at `$4C00`, the sixth write at `$4BFB`
    and the tail `$210C` when the title is this one. And **a party has been
    fast-travelled into fourteen of these twenty-two areas on a running
    machine**, each landing checked by an exact 1024-byte compare of `$0400`
    against the map on the player's own disk, 15 hops and 15 matches
    (`#20 (Build an area table for Silver Blades)`). Offering rows nobody had
    driven was what the PROBABLE grade on the whole table was warning about,
    and that is what stopped being true.

    Curse still answers nothing here and for the older reason: nobody has
    built its table. `areas_for` above is the accessor for everything that
    only reads, and answers for every title that has a table at all.
    """
    return TABLES.get(title or "", ())


def area(id: int) -> Area | None:
    """The area with this id in Pool of Radiance, or None -- id 12 has no
    script."""
    return AREAS_BY_ID.get(id)


def area_in(id: int, title: str | None) -> Area | None:
    """The area with this id **in this title**, or None.

    `area` above is Pool of Radiance's, and an id means a different place in
    each game: `$21` is Sokol Keep there and a Silver Blades area on side 2
    here. A caller holding a title must ask this one.
    """
    for a in areas_for(title):
        if a.id == id:
            return a
    return None


def areas_for_geo(geo: str) -> tuple[Area, ...]:
    """Every area that loads this map. Usually one; never assume it."""
    return _BY_GEO.get(geo, ())


def geos_for_area(id: int) -> tuple[str, ...]:
    """The maps this area loads: two, one, or none."""
    a = AREAS_BY_ID.get(id)
    return a.geos if a else ()


def iter_areas() -> Iterator[Area]:
    return iter(AREAS)


# -- names, per title --------------------------------------------------------


def geo_number(geo: str) -> int | None:
    """`GEO15` -> 21. The digits are hex, which is why `GEO0A` exists."""
    if not geo.startswith("GEO"):
        return None
    try:
        return int(geo[3:], 16)
    except ValueError:
        return None


def _names_for_pool() -> Mapping[str, str]:
    out: dict[str, str] = {}
    for a in AREAS:
        for name in a.geos:
            label = a.name_for(name)
            if label:
                out[name] = label
    return MappingProxyType(out)


#: Game title -> map file -> the name to show. Curse and Silver Blades are
#: present and empty: their maps are not named anywhere yet -- Silver Blades'
#: twenty-two areas are decoded down to the map and the disk side and not one
#: of them has a name -- and an empty table degrades to `"area 21"` where a
#: missing title would degrade to the same thing. Listing them is the
#: difference between "we know we do not know" and "we never looked".
GEO_NAMES: Mapping[str, Mapping[str, str]] = MappingProxyType({
    POOL_OF_RADIANCE: _names_for_pool(),
    CURSE_OF_THE_AZURE_BONDS: MappingProxyType({}),
    SECRET_OF_THE_SILVER_BLADES: MappingProxyType({}),
})


def geo_name(geo: str, title: str | None = POOL_OF_RADIANCE) -> str | None:
    """The place this map is, in this game -- or None if we cannot say."""
    if not title:
        return None
    return GEO_NAMES.get(title, {}).get(geo)


def area_name(geo: str, title: str | None = POOL_OF_RADIANCE) -> str:
    """A name for a map that is never a lie about another game.

    `GEO15` is Sokol Keep in Pool of Radiance and somewhere else entirely in
    Curse of the Azure Bonds. With no title, or a title with no table, this
    falls back to the file's own number -- `"area 21"` -- which says exactly as
    much as we know.
    """
    known = geo_name(geo, title)
    if known:
        return known
    n = geo_number(geo)
    return f"area {n}" if n is not None else geo


# -- where to put a party that arrives with no arrival square ---------------


def components(geo) -> list[set[tuple[int, int]]]:
    """The map's squares grouped by what can walk to what.

    A `GEO` is not one room. `GEO19` breaks into 42 pieces, `GEO0D` into 21,
    and a square picked without regard to which piece it is in can be a place
    the party cannot walk out of.
    """
    from goldbox.geo import GRID, STEP

    seen: set[tuple[int, int]] = set()
    out: list[set[tuple[int, int]]] = []
    for sy in range(GRID):
        for sx in range(GRID):
            if (sx, sy) in seen:
                continue
            stack = [(sx, sy)]
            seen.add((sx, sy))
            comp: set[tuple[int, int]] = set()
            while stack:
                x, y = stack.pop()
                comp.add((x, y))
                for d, (dx, dy) in STEP.items():
                    if not geo.is_passable(x, y, d):
                        continue
                    n = (x + dx, y + dy)
                    if not (0 <= n[0] < GRID and 0 <= n[1] < GRID) or n in seen:
                        continue
                    seen.add(n)
                    stack.append(n)
            out.append(comp)
    return out


def landing_square(geo) -> tuple[int, int, int] | None:
    """Where to drop a party on a map that has no arrival square of its own.

    **What `FastTravel` uses**, in place of the old rule -- the first square with any
    passable edge at all, which therefore took `(0, 0)` on every one of the
    twenty-nine maps (write-up lost, `work/reports/p20-arrivals.md`; the pocket
    sizes are asserted in `tests/test_p20.py`'s `POCKETS`). That was legal in the
    narrow sense on most
    maps and wrong on four: `(0, 0)` is in a pocket of 32 squares in `GEO05`,
    30 in `GEO19`, 16 in `GEO1A` and 48 in `GEO1B`, cut off from the rest of
    the map, and a party fasttraveled there can walk but cannot get out.

    So: the largest connected component, and within it a square off the outer
    ring where one exists, facing a passable edge. Returns None for a map with
    no passable edge anywhere, which is also what an area with no map gets.

    Two kinds of area the caller must not call this for at all, because the
    answer would be meaningless rather than merely imperfect: the **three
    overland** areas, where the position is `$49C3`/`$49C4`, not a `GEO`
    square -- `Area.overland` carries it and `FastTravel` writes it directly
    (`#178 (Fast Travel to the wilderness leaves the party on whatever
    overland square it last stood on)`; this used to say every arriving
    script writes `[$4A18]`/`[$4A19]`, "the world-map cell" -- those bytes are
    scratch, and the only writers copy an *indoor* square into `$C04B` on the
    way into a window's own cave, corrected while fixing #178); and the two
    **`dynamic_geo`** areas, which load a map `geos` does not name.
    """
    from goldbox.geo import GRID

    comps = [c for c in components(geo) if len(c) > 1]
    if not comps:
        return None
    best = max(comps, key=len)
    inner = [p for p in best if 0 < p[0] < GRID - 1 and 0 < p[1] < GRID - 1]
    for x, y in sorted(inner or best, key=lambda p: (p[1], p[0])):
        for facing in range(4):
            if geo.is_passable(x, y, facing):
                return (x, y, facing)
    return None
