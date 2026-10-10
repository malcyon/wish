"""The departures Fast Travel reproduces, and nothing else.

Fast Travel goes straight to the destination. A departing area's own script
can do something a walking party would trigger on the way out (drop a
companion, set a quest byte); a row here says that a title's area does, how
to tell whether it applies, and how a trip reproduces it. An area with no
row is left by the plain jump.

Rows are keyed by title key and departing area, never by area id alone: area
16 is a Pool of Radiance cave and a Silver Blades town.

`route_to` rows reproduce the departure by walking out through
`automap.fasttravel.EXIT_ROUTES[(area, route_to)]`, so the game's own handler
runs. `writes` rows reproduce it by writing the bytes the script writes: on
the C64 `(address, value)` is a memory byte, on the Amiga it is an ECL
script variable that the trip's prologue stores.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

POOL_OF_RADIANCE = "pool-of-radiance"
POOLS_OF_DARKNESS = "pools-of-darkness"
CURSE_OF_THE_AZURE_BONDS = "curse-of-the-azure-bonds"
SECRET_OF_THE_SILVER_BLADES = "secret-of-the-silver-blades"

C64 = "c64"
AMIGA = "amiga"


@dataclass(frozen=True)
class Guard:
    """One test the departing script makes on a byte. `op` is `==`, `!=`,
    `>=`, `in` or `not in` (`value` is a tuple) or `bits` (the mask `value`
    is non-zero)."""

    address: int
    op: str
    value: int | tuple[int, ...]

    def holds(self, byte: int) -> bool:
        if self.op == "==":
            return byte == self.value
        if self.op == "!=":
            return byte != self.value
        if self.op == ">=":
            return byte >= self.value
        if self.op == "in":
            return byte in self.value
        if self.op == "not in":
            return byte not in self.value
        if self.op == "bits":
            return bool(byte & self.value)
        raise ValueError(f"unknown guard operation {self.op!r}")


@dataclass(frozen=True)
class Departure:
    title: str
    areas: frozenset[int]
    ports: frozenset[str]
    #: All of them must hold.
    guards: tuple[Guard, ...] = ()
    #: A party member's name that must be in the party.
    member: str | None = None
    #: Destinations that skip the departure: the script's own other exits.
    not_to: frozenset[int] = frozenset()
    #: Walk out through `EXIT_ROUTES[(area, route_to)]`.
    route_to: int | None = None
    #: `(address, value)`, in the order the script makes them before its
    #: `NEWECL`.
    writes: tuple[tuple[int, int], ...] = ()
    #: Whether the destination must be (True) or must not be (False) an
    #: overland area, or None for either.
    to_overland: bool | None = None
    #: Whether a trip may reproduce this row. A row that is built and tested
    #: but not yet shown to match the walk stays False and `find` skips it.
    enabled: bool = True
    #: Whether the script's exit also runs `CLEAR BOX` after its `SAVE`s.
    clear_box: bool = False
    #: Names the script drops from the roster on the way out. A slot matches
    #: on its record's name.
    dismiss: tuple[str, ...] = ()
    #: A match must also have record `0x0B8` bit 7 set (an NPC).
    dismiss_npc_only: bool = False
    #: Stop at the first match.
    dismiss_first_only: bool = False
    #: `(address, value)` written when the first match's roster status is not
    #: 1, the byte the script sets before it asks its question.
    dismiss_status_flag: tuple[int, int] | None = None
    #: The stub dismisses through the game's own `$3E` body instead of the
    #: trip writing the two stored bytes.
    stub_dismiss: bool = False
    #: The stub runs the restart's NPC coin wipe first.
    stub_coin_wipe: bool = False
    #: Item types the stub removes through the game's `$40`, in the script's
    #: order. Non-empty means the trip enters the stub, not `NEWECL`'s tail.
    item_cleanup: tuple[int, ...] = ()


#: Each row's comment names the script that makes the departure.
DEPARTURES: tuple[Departure, ...] = (
    # `ECL0D $9A9D` drops Princess Fatima from the party and the roster on the
    # way out of the Kobold Caves. Walking out runs it, and asks the player
    # whether to leave. Only Return reaches this row, because Fast Travel does
    # not leave the Kobold Caves.
    Departure(POOL_OF_RADIANCE, frozenset({13}), frozenset({C64, AMIGA}),
              member="PRINCESS FATIMA", route_to=27),
    # Lizardman Keep's exit, `ECL10 $9CBD-$9CCF`, pays the commission once: it
    # sets `$4AB5` to 254 unless it is already 255, and only for a party with
    # 40 kills (`$4A5D`). Every walked way out passes it.
    Departure(POOL_OF_RADIANCE, frozenset({16}), frozenset({C64, AMIGA}),
              guards=(Guard(0x4A5D, ">=", 40), Guard(0x4AB5, "!=", 255)),
              writes=((0x4AB5, 254),)),
    # The Buccaneer Base's edge exit, `ECL01 $9936-$993D`, sets `$4AA9` from 1
    # to 254. The other way out is the pirate fight, which sets 128 itself.
    Departure(POOL_OF_RADIANCE, frozenset({1}), frozenset({C64, AMIGA}),
              guards=(Guard(0x4AA9, "==", 1),), writes=((0x4AA9, 254),)),
    # The Nomad Camp's shared exit block, `ECL11 $A1B9-$A1ED`, sets `$4AB7` to
    # 254 when bit 4 or bit 1 of `$4A7C` is set and it is not already 255.
    Departure(POOL_OF_RADIANCE, frozenset({17}), frozenset({C64, AMIGA}),
              guards=(Guard(0x4A7C, "bits", 5), Guard(0x4AB7, "!=", 255)),
              writes=((0x4AB7, 254),)),
    # The Zhentil Keep Outpost's edge and leave-menu exits, `ECL1C $993C` and
    # `$B4F9-$B5EE`, set `$4AB4` to 253 whatever it held. Its fight exits do
    # not, and Fast Travel never starts in a fight.
    Departure(POOL_OF_RADIANCE, frozenset({28}), frozenset({C64, AMIGA}),
              writes=((0x4AB4, 253),)),
    # A cave in window 25, 26 or 27 keeps `$4A9E` at 255 while the party is
    # in it, and its exit menu (`ECL19 $AB31`, `ECL1A $AAF4`, `ECL1B $A83C`)
    # sets it to 0, which puts the next window arrival on the grid. One case
    # is not confirmed: a camp interrupted inside a window-25 cave can leave
    # for area 1 with the flag still 255.
    Departure(POOL_OF_RADIANCE, frozenset({25, 26, 27}),
              frozenset({C64, AMIGA}), guards=(Guard(0x4A9E, "==", 255),),
              writes=((0x4A9E, 0),)),
    # New Verdigris' leave question, `ECL10 $84F7-$84FE` and `$9A25-$9A2C`,
    # sets `$4CD9` from 1 to `$FF`. Amiga Silver Blades has no Fast Travel.
    # Off until a live run shows the skip breaks game state: Fast Travel goes
    # straight to the destination otherwise.
    Departure(SECRET_OF_THE_SILVER_BLADES, frozenset({0x10}), frozenset({C64}),
              guards=(Guard(0x4CD9, "==", 1),), writes=((0x4CD9, 0xFF),),
              enabled=False),
    # Off until a live run shows the skip breaks game state: Fast Travel goes
    # straight to the destination otherwise.
    # Every way out of the `$5x` group (`ECL50`, `ECL51`'s exits to `$50` and
    # `$52`, and `ECL52`) stores 9 and 12 through `GOSUB $9BE2`/`$9BBA`, which
    # `GDRIVE01` reads. A trip inside the group does not leave it.
    Departure(SECRET_OF_THE_SILVER_BLADES, frozenset({0x50, 0x51, 0x52}),
              frozenset({C64}), not_to=frozenset({0x50, 0x51, 0x52}),
              writes=((0xC059, 9), (0xC05A, 12)), enabled=False),
    # Pools of Darkness areas 17, 25, 51 and 80 hand the party to a parent
    # script, and a trip to a non-overland area skips what that script leaves
    # in script variables `$24` and `$22`. All four exit subroutines are the
    # same 13 bytes, `SAVE 0,[$24]`, `SAVE 1,[$22]`, `CLEAR BOX`, `RETURN`:
    # 17 `$9653`, 25 `$8BA2`, 51 `$87AE`, 80 `$87FC`.
    Departure(POOLS_OF_DARKNESS, frozenset({17, 25, 51, 80}),
              frozenset({AMIGA}), writes=((0x24, 0), (0x22, 1)),
              to_overland=False, clear_box=True),
    # The Pit of Moander's exit, `ECL11 $82E1-$84F3`, drops ALIAS and
    # DRAGONBAIT (NPCs only) and sets `$4C5B` to 255. It runs only when
    # `$4C5B` is not 255, `$4C2D` is 128 or 255 and `$4C2E` is not 0; the
    # second level, `ECL12`, leads only back to area `$11`.
    Departure(CURSE_OF_THE_AZURE_BONDS, frozenset({0x11}), frozenset({C64}),
              guards=(Guard(0x4C5B, "!=", 255), Guard(0x4C2D, "in", (128, 255)),
                      Guard(0x4C2E, "!=", 0)),
              not_to=frozenset({0x12}), writes=((0x4C5B, 255),),
              dismiss=("ALIAS", "DRAGONBAIT"), dismiss_npc_only=True,
              enabled=False),
    # The Compound's edge exit, `ECL44 $82A4-$8360` and `$98CB`, drops the
    # first member named SIR DERIC, with no test of the NPC bit, and sets
    # `$4C05` to 1 first when his status is not 1.
    Departure(SECRET_OF_THE_SILVER_BLADES, frozenset({0x44}),
              frozenset({C64}), dismiss=("SIR DERIC",),
              dismiss_first_only=True, dismiss_status_flag=(0x4C05, 1),
              enabled=False),
    # Every arrival in `$30` runs `ECL30` entry 4 (`$8014-$8098`): the restart's
    # coin wipe, Akabar's `$3E`, then `$40` for types 94, 96 and 97. A trip
    # inside Haptooth does not run it.
    Departure(CURSE_OF_THE_AZURE_BONDS, frozenset({0x31, 0x32, 0x33}),
              frozenset({C64}), not_to=frozenset({0x30, 0x31, 0x32, 0x33}),
              dismiss=("AKABAR BEL AKAS",), dismiss_npc_only=True,
              dismiss_first_only=True, stub_dismiss=True,
              stub_coin_wipe=True, item_cleanup=(94, 96, 97), enabled=False),
    # The exits of the Cave of the Beholder (`ECL22 $94CB`), Oxam's Tower
    # (`ECL25 $821F`) and the dale dungeons (`ECL35 $8538`) run `$40`
    # unconditionally.
    Departure(CURSE_OF_THE_AZURE_BONDS, frozenset({0x22}), frozenset({C64}),
              item_cleanup=(97, 96), enabled=False),
    Departure(CURSE_OF_THE_AZURE_BONDS, frozenset({0x25}), frozenset({C64}),
              item_cleanup=(97, 96), enabled=False),
    Departure(CURSE_OF_THE_AZURE_BONDS, frozenset({0x35}), frozenset({C64}),
              item_cleanup=(94, 96, 97), enabled=False),
)


def find(title: str, port: str, here: int, to: int,
         to_overland: bool | None = None,
         include_disabled: bool = False) -> Departure | None:
    """The departure a trip from `here` to `to` reproduces, or None.

    A row that depends on the destination being overland (or not) matches
    only when the caller says which. A disabled row is skipped unless
    `include_disabled`, which is for tests of the rows themselves.
    """
    for row in DEPARTURES:
        if ((row.enabled or include_disabled) and row.title == title
                and port in row.ports and here in row.areas
                and to not in row.not_to
                and (row.to_overland is None
                     or row.to_overland == to_overland)):
            return row
    return None


def applies(row: Departure, read_byte: Callable[[int], int | None],
            names: Iterable[str] | None) -> bool | None:
    """Whether the row's guards and member hold, or None when a byte or the
    party cannot be read and so nothing can be said."""
    for guard in row.guards:
        byte = read_byte(guard.address)
        if byte is None:
            return None
        if not guard.holds(byte):
            return False
    if row.member is not None:
        if names is None:
            return None
        if row.member not in set(names):
            return False
    return True
