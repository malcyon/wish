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

C64 = "c64"
AMIGA = "amiga"


@dataclass(frozen=True)
class Guard:
    """One test the departing script makes on a byte. `op` is `==`, `!=`,
    `not in` (`value` is a tuple) or `bits` (the mask `value` is non-zero)."""

    address: int
    op: str
    value: int | tuple[int, ...]

    def holds(self, byte: int) -> bool:
        if self.op == "==":
            return byte == self.value
        if self.op == "!=":
            return byte != self.value
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


#: Each row's comment names the script that makes the departure.
DEPARTURES: tuple[Departure, ...] = (
    # `ECL0D $9A9D` drops Princess Fatima from the party and the roster on the
    # way out of the Kobold Caves. Walking out runs it, and asks the player
    # whether to leave.
    Departure(POOL_OF_RADIANCE, frozenset({13}), frozenset({C64, AMIGA}),
              member="PRINCESS FATIMA", route_to=27),
    # Lizardman Keep's exit sets `$4AB5`. Until its guard is read from the
    # script, the exit is walked whenever the byte is not 254 or 255, the
    # values it holds once the exit has run.
    Departure(POOL_OF_RADIANCE, frozenset({16}), frozenset({C64, AMIGA}),
              guards=(Guard(0x4AB5, "not in", (254, 255)),), route_to=27),
    # Pools of Darkness areas 17, 25, 51 and 80 hand the party to a parent
    # script, and a trip to a non-overland area skips what that script leaves
    # in script variables `$24` and `$22`. Nothing reads this row yet: the
    # Amiga trip gate keeps every such trip from starting.
    Departure(POOLS_OF_DARKNESS, frozenset({17, 25, 51, 80}),
              frozenset({AMIGA}), writes=((0x24, 0), (0x22, 1)),
              to_overland=False),
)


def find(title: str, port: str, here: int, to: int,
         to_overland: bool | None = None) -> Departure | None:
    """The departure a trip from `here` to `to` reproduces, or None.

    A row that depends on the destination being overland (or not) matches
    only when the caller says which.
    """
    for row in DEPARTURES:
        if (row.title == title and port in row.ports and here in row.areas
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
