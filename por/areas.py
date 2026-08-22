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

Names come from `docs/88-map-files.md`, `work/reports/world-map.md` and
`work/reports/quest-flags.md`; arrival squares were harvested from the
departing scripts' `SAVE <n>, mapX` and the arriving scripts' entry 4. Fifteen
areas have no known arrival square and say so with `arrival = None`.

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

Enumerating maps by count or assuming a `GEO00` is wrong for every Gold Box
title after this one: Curse's ids are sparse and chapter-grouped, and Silver
Blades, Champions and Death Knights start at `$10` or `$20`
(`work/reports/goldbox-inventory.md`). Scan a directory; never a range.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Iterator, Mapping

from por.layout import Confidence

__all__ = [
    "Confidence",
    "POOL_OF_RADIANCE",
    "CURSE_OF_THE_AZURE_BONDS",
    "Arrival",
    "Area",
    "AREAS",
    "AREAS_BY_ID",
    "MISSING_ID",
    "area",
    "areas_for_geo",
    "geos_for_area",
    "geo_number",
    "geo_name",
    "GEO_NAMES",
    "area_name",
]


#: Game titles this module knows about. Plain strings on purpose, and the seam
#: with `por/games.py`: these are `Game.title`, so a caller holding a descriptor
#: writes `areas.area_name(geo, game.title)` and neither module imports the
#: other. `tests/test_areas.py` pins the two spellings together.
POOL_OF_RADIANCE = "Pool of Radiance"
CURSE_OF_THE_AZURE_BONDS = "Curse of the Azure Bonds"

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
    #: Which `POOL` disk carries the script, 1-8. This is what a warp writes to
    #: `$6E12` and what the loader will prompt for.
    disk: int
    #: The `GEO` files the script statically loads, in the order it loads them.
    #: Empty for the four mapless areas.
    geos: tuple[str, ...] = ()
    #: The overland square-data file, for areas 25-27 only.
    sqrdata: str | None = None
    arrival: Arrival | None = None
    confidence: Confidence = Confidence.UNKNOWN
    #: Names for individual maps of a two-map area, where the second map is a
    #: place in its own right -- area 29's `GEO20` is the catacombs under
    #: Kuto's Well, not Kuto's Well.
    geo_names: Mapping[str, str] = field(default_factory=dict)
    #: The script also chooses a map at run time, with `GETTABLE ..., mapDir`,
    #: so `geos` may be incomplete. True for areas 3 and 5, whose scripts issue
    #: no static `LOADFILES` at all; their `geos` entry is the doc's inference
    #: from the id, not something the bytecode says.
    dynamic_geo: bool = False

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
        return f"{self.name or self.ecl} - {maps}, POOL{self.disk}"


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
    _a(21, "Sokol Keep", 4, ("GEO15",), None, C),
    _a(22, "Yarash's Pyramid", 7, ("GEO16",), Arrival(15, 7, 1), C),
    _a(23, "Yarash's Pyramid, Lower", 7, ("GEO17",), Arrival(15, 0, 2), P),
    _a(24, "Temple of Bane", 1, ("GEO18", "GEO1F"), Arrival(15, 4, 3), C),
    _a(25, "Wilderness, West Window", 6, ("GEO19",), None, C,
       sqrdata="SQRDATA04"),
    _a(26, "Wilderness, Middle Window", 7, ("GEO1A",), None, C,
       sqrdata="SQRDATA05"),
    _a(27, "Wilderness, East Window", 8, ("GEO1B",), None, C,
       sqrdata="SQRDATA06"),
    _a(28, "Zhentil Keep Outpost", 6, ("GEO1C",), Arrival(7, 0, 2), C),
    _a(29, "Kuto's Well", 8, ("GEO1D", "GEO20"), None, C,
       geo_names=MappingProxyType({"GEO20": "Kuto's Well Catacombs"})),
    _a(30, None, 1, (), None, U),
)

AREAS_BY_ID: Mapping[int, Area] = MappingProxyType({a.id: a for a in AREAS})


def _by_geo() -> Mapping[str, tuple[Area, ...]]:
    index: dict[str, list[Area]] = {}
    for a in AREAS:
        for name in a.geos:
            index.setdefault(name, []).append(a)
    return MappingProxyType({k: tuple(v) for k, v in index.items()})


_BY_GEO = _by_geo()


def area(id: int) -> Area | None:
    """The area with this id, or None -- id 12 has no script."""
    return AREAS_BY_ID.get(id)


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


#: Game title -> map file -> the name to show. Curse is present and empty: its
#: sixteen maps are not named anywhere yet, and an empty table degrades to
#: `"area 21"` where a missing title would degrade to the same thing. Listing
#: it is the difference between "we know we do not know" and "we never looked".
GEO_NAMES: Mapping[str, Mapping[str, str]] = MappingProxyType({
    POOL_OF_RADIANCE: _names_for_pool(),
    CURSE_OF_THE_AZURE_BONDS: MappingProxyType({}),
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
