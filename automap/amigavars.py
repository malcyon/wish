"""Where the script variables of an Amiga title sit in memory, read-only.

Each variable range is a table whose address is a 32-bit pointer held in the
title's data hunk, so a variable's address is the pointer's value plus an index
(bytes on Pools of Darkness, big-endian words on Curse). A variable with no
fixed address, or in no range of the title, is reported unreadable with the
reason rather than guessed. A range whose value the game may take from elsewhere
first (Curse `$7C00`-`$7FFF`, the current member's field; Pool `$6B00`-`$6EFF`,
about thirty offsets) carries a `note` into every reading.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VarRange:
    """Script variables `first`..`last`, held at `[data_base + pointer] + scale * (var - origin)`."""

    first: int
    last: int
    pointer: int
    size: int
    origin: int = 0
    #: A caveat the reading carries into the log.
    note: str | None = None


@dataclass(frozen=True)
class VarMap:
    ranges: tuple[VarRange, ...]
    #: Ranges that exist but live in no fixed place, with the reason to report.
    unaddressed: tuple[tuple[int, int, str], ...] = ()


#: Keyed by `amiga.MACHINES` key. The 0x8000 range's address is the table plus
#: the variable number, which includes the 0x8000 itself.
MAPS: dict[str, VarMap] = {
    "pools-of-darkness": VarMap(
        ranges=(
            VarRange(0x1, 0x400, 0x57AC, 1),
            VarRange(0x8000, 0x9DFF, 0x6EA6, 1),
        ),
        unaddressed=((0x401, 0x800, "a field of the current member's record"),),
    ),
    # Pool's `$6E82` is the word at offset 0xF04 of `savgam?.dat`.
    "pool-of-radiance": VarMap(
        ranges=(
            VarRange(0x4900, 0x4CFF, 0x98, 2, 0x4900),
            VarRange(0x6B00, 0x6EFF, 0x9C, 2, 0x6B00,
                     note="about thirty offsets are read from member records "
                          "by the game, not from this table"),
            VarRange(0x9700, 0x98FF, 0xA0, 2, 0x9700),
            VarRange(0x9900, 0xB6FF, 0xA4, 1, 0x9900),
        ),
    ),
    "curse-of-the-azure-bonds": VarMap(
        ranges=(
            VarRange(0x4B00, 0x4EFF, 0x3D00, 2, 0x4B00),
            VarRange(0x7A00, 0x7BFF, 0x588A, 2, 0x7A00),
            VarRange(0x7C00, 0x7FFF, 0x3DBE, 2, 0x7C00,
                     note="the game reads the current member's field first "
                          "and falls back to this table"),
            VarRange(0x8000, 0x9DFF, 0x5006, 1),
        ),
    ),
}


@dataclass(frozen=True)
class VarReading:
    var: int
    address: int | None
    size: int
    value: int | None
    unreadable: str | None = None
    note: str | None = None

    def as_log(self) -> dict:
        return {"var": f"${self.var:04X}", "address": None if self.address is None
                else hex(self.address), "size": self.size, "value": self.value,
                "unreadable": self.unreadable, "note": self.note}


def parse(text: str) -> int:
    """A variable number from hex, with or without a `$` or `0x` prefix."""
    cleaned = text.strip()
    for prefix in ("$", "0x", "0X"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break
    return int(cleaned, 16)


def parse_list(text: str) -> list[int]:
    return [parse(part) for part in text.split(",") if part.strip()]


class VarError(Exception):
    """A variable that has no guest address, with the reason."""


def resolve(target, title: str, var: int) -> tuple[int, VarRange]:
    """The guest address and range of script variable `var` on `title`."""
    table = MAPS.get(title)
    if table is None:
        raise VarError(f"no variable map for {title}")
    for first, last, why in table.unaddressed:
        if first <= var <= last:
            raise VarError(f"not readable: {why}")
    for rng in table.ranges:
        if rng.first <= var <= rng.last:
            base = target.data_base
            if base is None:
                raise VarError("data base not located")
            head = int.from_bytes(target.read(base + rng.pointer, 4), "big")
            return head + rng.size * (var - rng.origin), rng
    raise VarError(f"${var:04X} is in no range mapped for {title}")


def read_variable(target, title: str, var: int) -> VarReading:
    """Read one variable through the title's map; never writes."""
    try:
        address, rng = resolve(target, title, var)
    except VarError as exc:
        size = 0
        table = MAPS.get(title)
        if table is not None and str(exc) == "data base not located":
            size = next(r.size for r in table.ranges if r.first <= var <= r.last)
        return VarReading(var, None, size, None, str(exc))
    value = int.from_bytes(target.read(address, rng.size), "big")
    return VarReading(var, address, rng.size, value, note=rng.note)


def read_variables(target, title: str, variables) -> list[VarReading]:
    return [read_variable(target, title, v) for v in variables]
