"""Where the script variables of an Amiga title sit in memory, read-only.

Each variable range is a table whose address is a 32-bit pointer held in the
title's data hunk, so a variable's address is the pointer's value plus an index
(bytes on Pools of Darkness, big-endian words on Curse). A variable with no
fixed address, or in no range of the title, is reported unreadable with the
reason rather than guessed.
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
    "curse-of-the-azure-bonds": VarMap(
        ranges=(
            VarRange(0x4B00, 0x4EFF, 0x3D00, 2, 0x4B00),
            VarRange(0x7A00, 0x7BFF, 0x588A, 2, 0x7A00),
            VarRange(0x7C00, 0x7FFF, 0x3DBE, 2, 0x7C00),
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

    def as_log(self) -> dict:
        return {"var": f"${self.var:04X}", "address": None if self.address is None
                else hex(self.address), "size": self.size, "value": self.value,
                "unreadable": self.unreadable}


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


def read_variable(target, title: str, var: int) -> VarReading:
    """Read one variable through the title's map; never writes."""
    table = MAPS.get(title)
    if table is None:
        return VarReading(var, None, 0, None, f"no variable map for {title}")
    for first, last, why in table.unaddressed:
        if first <= var <= last:
            return VarReading(var, None, 0, None, f"not readable: {why}")
    for rng in table.ranges:
        if rng.first <= var <= rng.last:
            base = target.data_base
            if base is None:
                return VarReading(var, None, rng.size, None, "data base not located")
            head = int.from_bytes(target.read(base + rng.pointer, 4), "big")
            address = head + rng.size * (var - rng.origin)
            value = int.from_bytes(target.read(address, rng.size), "big")
            return VarReading(var, address, rng.size, value)
    return VarReading(var, None, 0, None, f"${var:04X} is in no range mapped for {title}")


def read_variables(target, title: str, variables) -> list[VarReading]:
    return [read_variable(target, title, v) for v in variables]
