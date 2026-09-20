"""Helpers `test_debugmode` shares with the test files that reuse them."""
from __future__ import annotations

import pytest

from automap import actions, c64
from automap.target import MemoryTarget

WORLD, COMBAT = 1, 2                    # $6E11: DUNGEON, COMBAT
IN_THE_LOOP = 0x10C2                    # a PC the fasttravel will accept


class Machine(MemoryTarget):
    """A `MemoryTarget` that also has a CPU, which is all a fasttravel adds.

    `Target` is `read` and `write` and deliberately nothing else, so the
    program counter is reached through the same optional hook a real backend
    would offer.
    """

    def __init__(self, memory=None, pc: int = IN_THE_LOOP):
        super().__init__(memory)
        self._pc = pc
        self.jumps: list[int] = []

    def pc(self) -> int:
        return self._pc

    def set_pc(self, address: int) -> None:
        self._pc = address
        self.jumps.append(address)


def machine(mode: int = WORLD, area: int = 0, disk: int = 3,
            pc: int = IN_THE_LOOP, indoors: int = 1) -> Machine:
    """A machine standing in an area, ready to be fasttraveled out of."""
    return Machine({c64.MODE_FLAG_POOL: bytes([mode]),
                    actions.FASTTRAVEL_SLOT: bytes([area]),
                    actions.FASTTRAVEL_DISK: bytes([disk]),
                    actions.FASTTRAVEL_INDOORS: bytes([indoors]),
                    actions.FASTTRAVEL_X: bytes([5, 6, 1])}, pc=pc)


def area(id: int = 20):
    row = actions.area_by_id(id)
    if row is None:                     # pragma: no cover - the table is there
        pytest.skip("goldbox/areas.py has no such area")
    return row
